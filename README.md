# UniFi Intercom Viewer — Portable Patcher

Turn the **UniFi Access Intercom Viewer** firmware into an APK that installs,
runs, and adopts on an ordinary **non-rooted Android phone** — so you can use an
old phone or tablet as an Intercom Viewer instead of the dedicated hardware.

You point this tool at the **official firmware OTA zip** (which you supply), and
it extracts the viewer app, patches it, and re-signs it into an installable APK.

Runs on **Debian/Linux, Windows, and macOS**.
**👉 New here? Follow the [Quick Guide](QUICKSTART.md).**

> [!IMPORTANT]
> **This repository contains no Ubiquiti code or binaries, and distributes none.**
> It is a *transformer*: it operates on firmware **you already possess**. You must
> download the firmware yourself and you are responsible for your right to use it.
> This project is **not affiliated with, authorized, or endorsed by Ubiquiti Inc.**
> UniFi, UniFi Access, and the firmware remain the property of Ubiquiti Inc.
> No firmware or patched APK is published here — only the patcher.

---

## What it does

| Area | Patch |
|------|-------|
| **Installable** | Removes `sharedUserId="android.uid.system"` and `persistent="true"` so it installs as a normal app (no root, no platform key), then re-signs it. |
| **Adoptable** | On non-Viewpoint hardware the app advertises a blank identity and listens for UniFi discovery only on `eth0`. The patch advertises a valid Ubiquiti‑OUI MAC + the real firmware id/version (read from *your* firmware), switches discovery to `wlan0`, and holds a Wi‑Fi `MulticastLock` so the controller's discovery probe is actually received. |
| **Fullscreen** | Hides the status/navigation bars (immersive, edge‑to‑edge). |
| **Screensaver** | After the app's idle timeout (default 60 s, set from the controller) the screen goes black at minimum brightness, like the Viewpoint's screen-off; a tap or a ring wakes it. Toggle it on/off from a **"Screensaver" switch added to Settings → Display & Brightness**. `--sleep never` omits it entirely. See [Sleep](#sleep). |
| **Full-screen layout** | Removes the 9:16 letterbox the app applies for the Viewpoint's screen, so the UI and the call view fill taller phone screens. |
| **Remove from UniFi** | The Viewpoint factory-resets itself when it's removed in UniFi Access; a normal app can't, so it stayed adopted. Now the app wipes its own data and restarts unadopted. If the device was removed while the app wasn't running (UniFi then asks you to hold the reset button), clear the app's storage instead: *Settings → Apps → Intercom Viewer → Storage → Clear data*, or `adb shell pm clear com.ui.da.viewer.app`. |
| **Backdrop** | Solid black by default (AMOLED-friendly), a dark gradient (`--gradient`), or none (`--no-gradient`). With `--letterbox` it fills the bands around the 9:16 block. |

All injected code is ordinary Android framework code written for this project.
Identity values come from your firmware at run time — nothing vendor‑specific is
baked into the tool.

## Requirements

- **Python 3.11+** and `pip install -r requirements.txt` (one dep: a pure‑Python ext4 reader)
- An **arm64 (`arm64-v8a`) device on Android 9+** to install the result, plus **adb**
- A **JDK**, **apktool**, and Android **build‑tools** (`apksigner` + `zipalign`) —
  **or just run `python3 bootstrap.py`**, which downloads all three into a local
  `tools/` folder (recommended on Windows — no system install needed).

If you'd rather install the tools yourself, they're found on `PATH` first (so
`apt`/`brew`/`choco` installs work) and then under the Android SDK; override with
`APKTOOL_JAR` and `ANDROID_BUILD_TOOLS` if needed.

Per-OS install commands (Debian/Ubuntu, Windows, macOS) are in the
**[Quick Guide](QUICKSTART.md)**. Tools are found on `PATH` first (so
`apt`/`brew`/`choco` installs just work) and then under the Android SDK; override
with `APKTOOL_JAR` and `ANDROID_BUILD_TOOLS` if needed.

## Usage

```bash
python3 patch.py /path/to/IntercomViewerFirmware.zip -o IntercomViewer-portable.apk
```

Then install on a phone with USB debugging enabled:
```bash
adb install -r -g IntercomViewer-portable.apk
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--mac AA:BB:CC:DD:EE:FF` | Advertise a specific MAC (default: random Ubiquiti‑OUI). **Use a unique MAC per device.** |
| `--oui AA:BB:CC` | Restrict the auto‑generated MAC to this Ubiquiti OUI. |
| `--keystore path.keystore` | Reuse a keystore so later versions install over the old one **without wiping adoption** (`adb install -r`). A throwaway one is generated if omitted. |
| `--no-adopt` | Install/run only; skip the discovery/adoption identity patches. |
| `--no-optimize` | Skip the fullscreen / keep‑awake / gradient patches. |
| `--gradient` | Use the dark gradient backdrop instead of the default solid black. |
| `--black-backdrop` | Force the solid-black backdrop (this is the default; pixels stay off on AMOLED). |
| `--no-gradient` | Apply no backdrop at all; leave the app's original (black) background. |
| `--sleep never` | Keep the screen on instead of the black screensaver (default: `--sleep screensaver`). |
| `--letterbox` | Keep the original centered 9:16 layout instead of filling the screen (see [Known limitation](#known-limitation)). |
| `--keep-work` | Keep the temp dir (extracted image, decoded APK, logs) for inspection. |

## Generating MAC addresses

For a device to be adoptable, it must advertise a valid **unicast** MAC in a
Ubiquiti-registered OUI so the controller recognizes it as Ubiquiti hardware.
`patch.py` does this automatically (random Ubiquiti OUI), but you can also
generate MACs yourself — handy when running the viewer on **several phones**
(each needs a unique MAC):

```bash
python3 genmac.py                      # one random Ubiquiti-OUI MAC
python3 genmac.py -n 5 --with-id       # five, with the viewer device id
python3 genmac.py --oui FC:EC:DA       # restrict to a specific Ubiquiti OUI
python3 genmac.py --sep none --upper   # bare hex (the device-id form)
python3 genmac.py --list-ouis          # list the Ubiquiti OUIs it draws from
```

Then pin it when patching:

```bash
python3 patch.py fw.zip --mac $(python3 genmac.py)
# or let patch.py pick one, optionally restricted to an OUI:
python3 patch.py fw.zip --oui 24:5A:4C
```

The generator uses only **publicly registered Ubiquiti IEEE OUIs** and random
lower bits; it keeps the unicast/globally-administered bits correct. The viewer
derives its device id from the MAC (lowercase hex, no separators), which
`--with-id` shows.

## Adopting into UniFi Access

After install, the app shows **“Ready to Adopt.”** Adopt it from the UniFi Access
app or `unifi.ui.com` **on the same subnet / VLAN as the phone** — UniFi device
discovery is subnet‑local multicast (`233.89.188.1:10001`) and will not cross
VLANs or survive Wi‑Fi client isolation.

Whether adoption *completes* can depend on controller/cloud‑side validation that
isn't in the app; a self‑hosted console on the same L2 is the most reliable case.

## Sleep

The Viewpoint turns its screen off after the app's idle timeout (default 60 s,
configurable from the controller) and wakes it for a ring, a remote view or
"Locate"; a tap wakes it too. A normal app can't switch the screen off itself,
so the patcher injects a small screensaver instead (`patcher/smali/Screensaver.smali`):

- after the timeout, a full-screen black overlay at minimum brightness covers the
  viewer; on AMOLED screens those pixels are off, so it's close to a real screen-off;
- the first tap only wakes it and is swallowed, so it can't press unlock by accident;
- the app's own wake-ups (incoming call, remote view, locate) wake it, and it stays
  awake while the call view is showing.

The app only applies its timeout on Viewpoint hardware (`Build.MODEL` check in
`SettingManager.setScreenTimeout`); the patch skips that check so the
screensaver follows the controller's setting. As on the Viewpoint, the app then
also writes it to the phone's system screen timeout.

## Known limitation

The app was designed for the Viewpoint's screen and renders its UI (clock, door
card, unlock button, call view) as a **9:16 block centered vertically**. The
letterbox comes from `MainActivity.x1`, which pads both the Compose view and the
call view by `(height - width / 9 * 16) / 2` at the top and bottom.

The patcher forces that padding to 0, so on a taller phone the UI reaches the
real screen edges. Tested on a 20:9 phone, including the live call view during a
doorbell ring. Pass `--letterbox` to keep the original centered 9:16 block; the
backdrop (solid black by default, or `--gradient`) then fills the bands around it.

## How it works

1. `payload.bin` is read from the OTA zip and the `system` partition image is
   reconstructed from its full‑OTA operations (pure‑Python CrAU parser — no
   external `payload-dumper`).
2. The viewer APK and `build.prop` are read out of the ext4 image (no mounting).
3. The APK is decoded with apktool; the patches above are applied to the smali /
   manifest / resources, validated with hard anchors (a firmware mismatch fails
   loudly rather than producing a broken APK).
4. The APK is rebuilt, zip‑aligned, and signed with apksigner.

See [`patcher/`](patcher/) — `payload.py`, `ext4read.py`, `patches.py`, `macgen.py`,
`sign.py` — and [`genmac.py`](genmac.py) for the standalone MAC generator.

## Compatibility

Written against firmware **`ua-intercom-viewer` v1.5.32** (Android 9 base). Other
firmware versions may rename obfuscated classes; the patcher will stop with a
clear “anchor not found” error if a target has moved.

## Contributing

Issues and PRs welcome — especially anchor updates for new firmware versions and
a proper responsive‑layout fix. Do **not** attach firmware or APKs to issues.

## License

[MIT](LICENSE) for the patcher code. Not for any Ubiquiti software, which this
project neither includes nor distributes.
