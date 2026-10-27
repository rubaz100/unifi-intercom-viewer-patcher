#!/usr/bin/env python3
"""
UniFi Access Intercom Viewer — firmware patcher.

Takes the *official firmware OTA zip that you already possess*, extracts the
viewer APK from it, patches it so it installs/runs/adopts on an ordinary
non-rooted Android phone, and re-signs it.

This tool ships NO Ubiquiti code or binaries. It only transforms files it
extracts from your own firmware at run time. You are responsible for your right
to use that firmware.

Usage:
    python3 patch.py <firmware.zip> [-o OUTPUT.apk] [options]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

from patcher import ext4read, macgen, patches, sign, toolchain
from patcher.payload import Payload


def log(msg: str) -> None:
    print(f"[*] {msg}", flush=True)


def extract_payload(zip_path: str, work: str) -> str:
    log(f"reading OTA zip: {os.path.basename(zip_path)}")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "payload.bin" not in names:
            raise SystemExit("error: payload.bin not found in zip (is this an A/B OTA?)")
        out = os.path.join(work, "payload.bin")
        with z.open("payload.bin") as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1 << 20)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch the UniFi Intercom Viewer firmware APK.")
    ap.add_argument("firmware", help="official firmware OTA .zip (you must own it)")
    ap.add_argument("-o", "--output", default="IntercomViewer-portable.apk",
                    help="output APK path (default: ./IntercomViewer-portable.apk)")
    ap.add_argument("--mac", default=None,
                    help="MAC to advertise (default: random Ubiquiti-OUI MAC via genmac). "
                         "Use a unique one per device.")
    ap.add_argument("--oui", default=None,
                    help="restrict the generated MAC to this Ubiquiti OUI (AA:BB:CC)")
    ap.add_argument("--keystore", default=None,
                    help="signing keystore (default: ./portable.keystore, created if absent). "
                         "Reuse the same keystore to upgrade without a data wipe.")
    ap.add_argument("--partition", default="system", help="partition holding the APK")
    ap.add_argument("--apk-path", default=None,
                    help="path of the APK inside the image (default: auto-detect by package)")
    ap.add_argument("--package", default="com.ui.da.viewer.app",
                    help="package name to locate when auto-detecting the APK")
    ap.add_argument("--no-adopt", action="store_true",
                    help="skip the discovery/adoption identity patches")
    ap.add_argument("--no-optimize", action="store_true",
                    help="skip fullscreen / keep-screen-on / gradient patches")
    ap.add_argument("--gradient", action="store_true",
                    help="use the dark gradient backdrop instead of the default black")
    ap.add_argument("--black-backdrop", action="store_true",
                    help="force the solid-black backdrop (this is the default)")
    ap.add_argument("--no-gradient", action="store_true",
                    help="don't apply any backdrop; leave the app's original (black) background")
    ap.add_argument("--sleep", choices=patches.SLEEP_MODES, default="screensaver",
                    help="after the app's idle timeout: 'screensaver' = black overlay, "
                         "tap to wake; 'never' = screen always on (default: screensaver)")
    ap.add_argument("--letterbox", action="store_true",
                    help="keep the original centered 9:16 layout instead of filling the screen")
    ap.add_argument("--keep-work", action="store_true", help="keep the temp work dir")
    ap.add_argument("--work", default=None, help="work directory (default: a temp dir)")
    args = ap.parse_args()

    if not os.path.exists(args.firmware):
        raise SystemExit(f"error: firmware not found: {args.firmware}")

    # fail fast if the toolchain is missing
    apktool = toolchain.find_apktool()
    toolchain.find_zipalign()
    toolchain.find_apksigner()

    work = args.work or tempfile.mkdtemp(prefix="uvp-")
    os.makedirs(work, exist_ok=True)
    mac = args.mac or macgen.generate(args.oui)

    try:
        payload_bin = extract_payload(args.firmware, work)

        log("parsing payload + extracting system image")
        pl = Payload(payload_bin)
        system_img = os.path.join(work, f"{args.partition}.img")
        size = pl.extract_partition(args.partition, system_img)
        pl.close()
        log(f"  {args.partition}.img: {size:,} bytes")

        log("opening ext4 image")
        vol = ext4read.open_volume(system_img)

        apk_in_image = args.apk_path
        if not apk_in_image:
            log("locating viewer APK")
            apks = ext4read.find_apks(vol)
            cands = [p for p, _ in apks if "DoorAccess" in p or "Intercom" in p or "viewer" in p.lower()]
            if not cands:
                # fall back to the largest priv-app apk
                cands = [p for p, _ in sorted(apks, key=lambda t: -t[1]) if "priv-app" in p]
            if not cands:
                raise SystemExit("error: could not locate the viewer APK; pass --apk-path")
            apk_in_image = cands[0]
        log(f"  {apk_in_image}")

        apk_orig = os.path.join(work, "viewer-original.apk")
        ext4read.read_file(vol, apk_in_image, apk_orig)

        props = ext4read.read_build_prop(vol)
        fw_id = props.get("ro.ubnt.firmware.id", "")
        fw_version = props.get("ro.ubnt.firmware.version", "")
        fw_product = props.get("ro.ubnt.firmware.product", "")
        log(f"  firmware: product={fw_product or '?'} version={fw_version or '?'}")

        log("decoding APK (apktool)")
        decoded = os.path.join(work, "decoded")
        shutil.rmtree(decoded, ignore_errors=True)
        toolchain.run(apktool + ["d", "-f", apk_orig, "-o", decoded],
                      stdout=open(os.path.join(work, "apktool-d.log"), "w"))

        log("applying patches")
        patches.patch_manifest(decoded)
        log("  + installable manifest (dropped system shared-uid / persistent)")

        if not args.no_adopt:
            patches.patch_mac(decoded, mac)
            patches.patch_wlan0(decoded)
            patches.patch_multicast_lock(decoded)
            if fw_id and fw_version:
                patches.patch_identity(decoded, fw_id, fw_version)
                log(f"  + adoption identity (MAC {mac}, fw {fw_version})")
            else:
                log(f"  + adoption identity (MAC {mac}; firmware id/version not in build.prop)")
            patches.patch_reset(decoded)
            log("  + removing the device in UniFi resets the app (factory reset)")

        if not args.no_optimize:
            patches.patch_screen(decoded)
            patches.patch_sleep(decoded, args.sleep)
            if args.no_gradient:
                log(f"  + fullscreen + sleep={args.sleep} (no backdrop)")
            else:
                use_gradient = args.gradient and not args.black_backdrop
                patches.patch_gradient(decoded, black=not use_gradient)
                backdrop = "gradient" if use_gradient else "black"
                log(f"  + fullscreen + sleep={args.sleep} + {backdrop} background")

        if not args.letterbox:
            patches.patch_fullscreen_layout(decoded)
            log("  + full-screen layout (no 9:16 letterbox)")

        log("rebuilding APK (apktool)")
        unsigned = os.path.join(work, "viewer-unsigned.apk")
        toolchain.run(apktool + ["b", decoded, "-o", unsigned],
                      stdout=open(os.path.join(work, "apktool-b.log"), "w"))

        log("signing")
        keystore = args.keystore or os.path.abspath("portable.keystore")
        sign.ensure_keystore(keystore)
        sign.align_and_sign(unsigned, os.path.abspath(args.output), keystore)

        log(f"done -> {args.output}")
        log(f"install with:  adb install -r -g {args.output}")
        print()
        print(f"    This device advertises MAC {mac}  (id {macgen.device_id(mac)})")
        print("    Adopt it from UniFi Access on the SAME subnet/VLAN as the phone.")
        return 0
    finally:
        if not args.keep_work and not args.work:
            shutil.rmtree(work, ignore_errors=True)
        else:
            log(f"work dir kept: {work}")


if __name__ == "__main__":
    sys.exit(main())
