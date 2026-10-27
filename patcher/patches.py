"""
Patch definitions for the UniFi Access Intercom Viewer APK.

These operate on an apktool-decoded tree of *the user's own* extracted APK. This
module contains NO Ubiquiti code: the injected smali below is ordinary Android
framework code (window flags, WifiManager.MulticastLock, immersive mode) written
for this project; identity values are read from the user's firmware at run time.
Each patch locates an anchor and fails loudly if the target structure is not
found, so a mismatched firmware never yields a silently-broken APK.
"""
from __future__ import annotations

import glob
import os
import re


class PatchError(RuntimeError):
    pass


def _find_smali(decoded: str, rel: str) -> str:
    hits = glob.glob(os.path.join(decoded, "smali*", rel))
    if not hits:
        raise PatchError(f"smali not found: {rel}")
    return hits[0]


def _read(path: str) -> str:
    # Normalize line endings to "\n" so our anchors match regardless of how
    # apktool wrote the file — on Windows it emits CRLF ("\r\n"), which otherwise
    # breaks the "\n"-based method/anchor matching. Edited files are written
    # back as "\n", which smali/aapt2 assemble fine on every platform.
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _replace_once(text: str, old: str, new: str, what: str) -> str:
    if old not in text:
        raise PatchError(f"anchor not found: {what}")
    return text.replace(old, new, 1)


def _edit_method(path: str, method_name: str, old: str, new: str, what: str) -> None:
    """Replace `old` with `new` inside a single smali method body (robust to the
    surrounding formatting/line-directive differences between apktool versions)."""
    text = _read(path)
    m = re.search(r"\.method[^\n]*\b" + re.escape(method_name) + r"\(", text)
    if not m:
        raise PatchError(f"method not found: {what}")
    end = text.find("\n.end method", m.start())
    if end == -1:
        raise PatchError(f"malformed method: {what}")
    body = text[m.start():end]
    if old not in body:
        raise PatchError(f"anchor not found in method: {what}")
    body = body.replace(old, new, 1)
    _write(path, text[:m.start()] + body + text[end:])


def _inject_method_start(path: str, signature: str, code: str, what: str) -> None:
    """Insert `code` right after the .locals line of the method whose
    declaration ends with `signature` (e.g. "W(Z)V")."""
    text = _read(path)
    m = re.search(r"\.method[^\n]* " + re.escape(signature) + r"\n\s*\.locals \d+\n", text)
    if not m:
        raise PatchError(f"method not found: {what}")
    _write(path, text[:m.end()] + "\n" + code + text[m.end():])


# --- 1. Manifest: make it installable as a normal app ----------------------

def patch_manifest(decoded: str) -> None:
    path = os.path.join(decoded, "AndroidManifest.xml")
    text = _read(path)
    before = text
    for attr in (
        r'\s+android:sharedUserId="[^"]*"',
        r'\s+android:sharedUserMaxSdkVersion="[^"]*"',
        r'\s+android:persistent="true"',
    ):
        text = re.sub(attr, "", text)
    if text == before:
        raise PatchError("manifest: nothing removed (already patched?)")
    _write(path, text)


# --- 2. Device identity for UniFi discovery/adoption -----------------------

def _early_return_string(path: str, method_sig: str, value: str, what: str) -> None:
    text = _read(path)
    pat = re.compile(
        r"(\.method[^\n]*\b" + re.escape(method_sig) + r"\n\s*\.locals \d+\n)"
    )
    m = pat.search(text)
    if not m:
        raise PatchError(f"method not found: {what}")
    inject = f'    const-string v0, "{value}"\n\n    return-object v0\n\n'
    text = text[: m.end()] + inject + text[m.end():]
    _write(path, text)


def patch_mac(decoded: str, mac: str) -> None:
    """Advertise a fixed MAC instead of the off-device placeholder."""
    path = _find_smali(decoded, os.path.join("ce", "g.smali"))
    _early_return_string(path, "d()Ljava/lang/String;", mac.lower(), "ce/g.d (MAC)")


def patch_identity(decoded: str, fw_id: str, fw_version: str) -> None:
    """Report the real firmware id/version (read from the user's firmware)."""
    path = _find_smali(decoded, os.path.join("ce", "e$a.smali"))
    _early_return_string(path, "f()Ljava/lang/String;", fw_id, "ce/e$a.f (firmware id)")
    _early_return_string(path, "i()Ljava/lang/String;", fw_version, "ce/e$a.i (fw version)")
    _early_return_string(path, "j()Ljava/lang/String;", fw_version, "ce/e$a.j (version)")


def patch_wlan0(decoded: str) -> None:
    """Join the discovery multicast on wlan0 (phones have no eth0)."""
    path = _find_smali(
        decoded,
        os.path.join("com", "ui", "da", "viewer", "app", "cmpts", "discovery",
                     "ResponderImpl.smali"),
    )
    text = _read(path)
    if '"eth0"' not in text:
        raise PatchError("ResponderImpl: eth0 anchor not found")
    _write(path, text.replace('"eth0"', '"wlan0"'))


def patch_multicast_lock(decoded: str) -> None:
    """Hold a Wi-Fi MulticastLock so inbound discovery multicast is delivered."""
    path = _find_smali(decoded, os.path.join("com", "ui", "da", "viewer", "app", "App.smali"))
    text = _read(path)
    # add a static field to retain the lock
    text = _replace_once(
        text,
        "# static fields\n",
        "# static fields\n"
        ".field public static mcastLock:Landroid/net/wifi/WifiManager$MulticastLock;\n\n",
        "App: static fields header",
    )
    # acquire in onCreate, right after the singleton is stored
    anchor = "    sput-object p0, Lcom/ui/da/viewer/app/App;->X:Lcom/ui/da/viewer/app/App;\n"
    inject = (
        '    const-string v6, "wifi"\n\n'
        "    invoke-virtual {p0, v6}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;\n\n"
        "    move-result-object v6\n\n"
        "    check-cast v6, Landroid/net/wifi/WifiManager;\n\n"
        '    const-string v7, "uv-mcast"\n\n'
        "    invoke-virtual {v6, v7}, Landroid/net/wifi/WifiManager;->createMulticastLock(Ljava/lang/String;)Landroid/net/wifi/WifiManager$MulticastLock;\n\n"
        "    move-result-object v6\n\n"
        "    sput-object v6, Lcom/ui/da/viewer/app/App;->mcastLock:Landroid/net/wifi/WifiManager$MulticastLock;\n\n"
        "    invoke-virtual {v6}, Landroid/net/wifi/WifiManager$MulticastLock;->acquire()V\n\n"
    )
    text = _replace_once(text, anchor, anchor + inject, "App.onCreate singleton store")
    _write(path, text)


# --- 3. Device optimizations: keep screen on + immersive fullscreen --------

MAIN_ONCREATE_SUPER = (
    "    invoke-super {p0, p1}, Lcom/ui/da/viewer/app/Hilt_MainActivity;->"
    "onCreate(Landroid/os/Bundle;)V\n"
)


def patch_screen(decoded: str) -> None:
    path = _find_smali(decoded, os.path.join("com", "ui", "da", "viewer", "app", "MainActivity.smali"))
    text = _read(path)
    inject = (
        "\n    invoke-virtual {p0}, Landroid/app/Activity;->getWindow()Landroid/view/Window;\n\n"
        "    move-result-object v0\n\n"
        "    const/16 v1, 0x80\n\n"
        "    invoke-virtual {v0, v1}, Landroid/view/Window;->addFlags(I)V\n\n"
        "    invoke-virtual {v0}, Landroid/view/Window;->getDecorView()Landroid/view/View;\n\n"
        "    sget v1, Landroid/os/Build$VERSION;->SDK_INT:I\n\n"
        "    const/16 v2, 0x1e\n\n"
        "    if-lt v1, v2, :uvp_legacy\n\n"
        "    const/4 v1, 0x0\n\n"
        "    invoke-virtual {v0, v1}, Landroid/view/Window;->setDecorFitsSystemWindows(Z)V\n\n"
        "    invoke-virtual {v0}, Landroid/view/Window;->getInsetsController()Landroid/view/WindowInsetsController;\n\n"
        "    move-result-object v1\n\n"
        "    if-eqz v1, :uvp_done\n\n"
        "    invoke-static {}, Landroid/view/WindowInsets$Type;->systemBars()I\n\n"
        "    move-result v2\n\n"
        "    invoke-interface {v1, v2}, Landroid/view/WindowInsetsController;->hide(I)V\n\n"
        "    const/4 v2, 0x2\n\n"
        "    invoke-interface {v1, v2}, Landroid/view/WindowInsetsController;->setSystemBarsBehavior(I)V\n\n"
        "    goto :uvp_done\n\n"
        "    :uvp_legacy\n\n"
        "    invoke-virtual {v0}, Landroid/view/Window;->getDecorView()Landroid/view/View;\n\n"
        "    move-result-object v1\n\n"
        "    const/16 v2, 0x1706\n\n"
        "    invoke-virtual {v1, v2}, Landroid/view/View;->setSystemUiVisibility(I)V\n\n"
        "    :uvp_done\n"
    )
    text = _replace_once(text, MAIN_ONCREATE_SUPER, MAIN_ONCREATE_SUPER + inject,
                         "MainActivity.onCreate super call")
    _write(path, text)


# --- 4. Fill the letterbox with a gradient (keep live-view aspect) ---------

GRADIENT_DRAWABLE = """<?xml version="1.0" encoding="utf-8"?>
<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">
    <gradient
        android:type="linear"
        android:angle="270"
        android:startColor="#2A3A4D"
        android:centerColor="#141C26"
        android:endColor="#05080C" />
</shape>
"""

# pure black: AMOLED pixels stay off around the live view
BLACK_DRAWABLE = """<?xml version="1.0" encoding="utf-8"?>
<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">
    <solid android:color="#000000" />
</shape>
"""


def patch_gradient(decoded: str, black: bool = False) -> None:
    # drop in the backdrop drawable
    draw_dir = os.path.join(decoded, "res", "drawable")
    os.makedirs(draw_dir, exist_ok=True)
    _write(os.path.join(draw_dir, "viewport_gradient.xml"),
           BLACK_DRAWABLE if black else GRADIENT_DRAWABLE)

    # set it as the root layout background (attribute-order independent)
    layout = os.path.join(decoded, "res", "layout", "layout_main.xml")
    text = _read(layout)
    if "viewport_gradient" not in text:
        new_text, n = re.subn(
            r"(<FrameLayout\b)",
            r'\1 android:background="@drawable/viewport_gradient"',
            text, count=1,
        )
        if n == 0:
            raise PatchError("anchor not found: layout_main FrameLayout")
        _write(layout, new_text)

    # make the root Surface transparent so the gradient shows through.
    # In MainActivity.Z0 the Surface color arg is copied with `move-wide v5, v6`;
    # setting it to 0L = Color.Transparent. Scoped to the method so it's robust.
    main = _find_smali(decoded, os.path.join("com", "ui", "da", "viewer", "app", "MainActivity.smali"))
    _edit_method(main, "Z0", "move-wide v5, v6", "const-wide/16 v5, 0x0",
                 "MainActivity.Z0 Surface color")


# --- 5. Fill the whole screen instead of a centered 9:16 block -------------

def patch_fullscreen_layout(decoded: str) -> None:
    # MainActivity.x1 letterboxes the UI to the Viewpoint's 9:16 screen:
    #   pad = (displayHeight - displayWidth / 9 * 16) / 2
    #   composeView.setPadding(0, pad, 0, pad); rtcLayout.setPadding(0, pad, 0, pad)
    # Forcing pad to 0 lets both the Compose UI and the call view fill the screen.
    main = _find_smali(decoded, os.path.join("com", "ui", "da", "viewer", "app", "MainActivity.smali"))
    _edit_method(main, "x1", "div-int/lit8 v1, v1, 0x2", "const/4 v1, 0x0",
                 "MainActivity.x1 letterbox padding")
# --- 6. Sleep: black screensaver after the app's idle timeout -------------

SLEEP_MODES = ("screensaver", "never")

SCREENSAVER_SMALI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smali", "Screensaver.smali")

DISPATCH_TOUCH = """
.method public dispatchTouchEvent(Landroid/view/MotionEvent;)Z
    .locals 1

    invoke-static {p1}, Lcom/uvp/Screensaver;->onTouch(Landroid/view/MotionEvent;)Z

    move-result v0

    if-eqz v0, :uvp_pass

    return v0

    :uvp_pass
    invoke-super {p0, p1}, Lcom/ui/da/viewer/app/Hilt_MainActivity;->dispatchTouchEvent(Landroid/view/MotionEvent;)Z

    move-result v0

    return v0
.end method
"""


def patch_sleep(decoded: str, mode: str) -> None:
    """The Viewpoint turns its screen off after the app's timeout (default 60 s,
    set from the controller) via Settings.System screen_off_timeout and
    PowerManager.goToSleep; on a phone the screen is kept on instead.

    screensaver: inject com.uvp.Screensaver, a black overlay at minimum
                 brightness that the first touch dismisses (AMOLED pixels off).
    never:       screen stays on (patch_screen's keep-on flag).
    """
    if mode not in SLEEP_MODES:
        raise PatchError(f"unknown sleep mode: {mode}")
    if mode == "never":
        return

    app = os.path.join("com", "ui", "da", "viewer", "app")
    settings = _find_smali(decoded, os.path.join(app, "cmpts", "SettingManager.smali"))

    # setScreenTimeout returns early unless Build.MODEL is the Viewpoint's
    # (t2.c() = "not a Viewpoint"); jump past that check so the timeout applies
    _edit_method(settings, "setScreenTimeout", "if-eqz v1, :cond_0", "goto :cond_0",
                 "SettingManager.setScreenTimeout Viewpoint check")

    # drop the class into the last (smallest) dex so no dex nears its method limit
    smali_root = sorted(glob.glob(os.path.join(decoded, "smali*")))[-1]
    dest = os.path.join(smali_root, "com", "uvp", "Screensaver.smali")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    _write(dest, _read(SCREENSAVER_SMALI))

    # attach the overlay once the activity exists, and route every touch through it
    main = _find_smali(decoded, os.path.join(app, "MainActivity.smali"))
    text = _read(main)
    if "dispatchTouchEvent(" in text:
        raise PatchError("anchor not found: MainActivity already overrides dispatchTouchEvent")
    attach = "\n    invoke-static {p0}, Lcom/uvp/Screensaver;->attach(Landroid/app/Activity;)V\n"
    text = _replace_once(text, MAIN_ONCREATE_SUPER, MAIN_ONCREATE_SUPER + attach,
                         "MainActivity.onCreate super call")
    _write(main, text.rstrip("\n") + "\n" + DISPATCH_TOUCH)

    # follow the app's screen timeout: setScreenTimeout computes `seconds * 1000`
    # in p1 before writing screen_off_timeout (runs at startup and on controller changes)
    _edit_method(settings, "setScreenTimeout", "mul-int/lit16 p1, p1, 0x3e8",
                 "mul-int/lit16 p1, p1, 0x3e8\n\n"
                 "    invoke-static {p1}, Lcom/uvp/Screensaver;->setTimeoutMs(I)V",
                 "SettingManager.setScreenTimeout")
    # the app's own wake-ups (incoming call, locate, remote view, OTA) wake the overlay
    _inject_method_start(settings, "wakeup(Ljava/lang/String;Ljava/lang/Long;)V",
                         "    invoke-static {}, Lcom/uvp/Screensaver;->poke()V\n",
                         "SettingManager.wakeup")

    # RtcViewContainer.W(show) shows/hides the call view: stay awake while it's up
    rtc = _find_smali(decoded, os.path.join(app, "RtcViewContainer.smali"))
    _inject_method_start(rtc, "W(Z)V",
                         "    invoke-static {p1}, Lcom/uvp/Screensaver;->setBusy(Z)V\n",
                         "RtcViewContainer.W call view visibility")

    # add a "Screensaver" on/off switch to the Display & Brightness settings
    smali_dir = os.path.dirname(SCREENSAVER_SMALI)
    for extra in ("SsSwitch.smali", "SsToggle.smali"):
        _write(os.path.join(smali_root, "com", "uvp", extra),
               _read(os.path.join(smali_dir, extra)))
    _inject_screensaver_toggle(decoded)


def _inject_screensaver_toggle(decoded: str) -> None:
    """Render com.uvp.SsSwitch.Row (a 'Screensaver' switch) right after the app's
    existing 'Location Thumbnails' switch in the Display & Brightness screen.
    The switch uses the app's own reusable switch-row composable (d0.r)."""
    ui_settings = os.path.join("com", "ui", "da", "viewer", "app", "ui", "settings")
    disp = None
    for cand in sorted(glob.glob(os.path.join(decoded, "smali*", ui_settings, "*.smali"))):
        if "settings_display_thumbnails_switch" in _read(cand):
            disp = cand
            break
    if disp is None:
        raise PatchError("Display settings screen (thumbnails switch) not found")
    text = _read(disp)
    # Inject right after the screen's title bar (always rendered, at the column's
    # top level) — the thumbnails switch sits inside a conditional branch, so it
    # isn't a reliable anchor. qe.f0.K(title, onBack, composer, I, I).
    m = re.search(
        r"invoke-static \{v\d+, v\d+, (v\d+), v\d+, v\d+\}, "
        r"Lqe/f0;->K\(Ljava/lang/String;Lfh/a;Landroidx/compose/runtime/k;II\)V",
        text,
    )
    if not m:
        raise PatchError("Display screen title bar (qe.f0.K) not found")
    composer = m.group(1)  # the Composer register
    inject = (f"\n\n    invoke-static/range {{{composer} .. {composer}}}, "
              f"Lcom/uvp/SsSwitch;->Row(Landroidx/compose/runtime/k;)V")
    at = m.end()
    _write(disp, text[:at] + inject + text[at:])


# --- 5. Remove from UniFi: factory reset -> app reset ----------------------

RESET_SMALI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smali", "Reset.smali")


def patch_reset(decoded: str) -> None:
    """Removing the device in UniFi Access sends a factory-reset RPC; the
    Viewpoint broadcasts FACTORY_RESET to the system MasterClearReceiver, which
    is silently dropped for a normal app, so it stays adopted. Inject
    com.uvp.Reset (patcher/java/com/uvp/Reset.java) instead: mark the reset and
    restart; the next start wipes the app's own data before anything opens it
    (wiping in the dying process races with it writing its preferences back)."""
    app = os.path.join("com", "ui", "da", "viewer", "app")
    mqtt = _find_smali(decoded, os.path.join(app, "cmpts", "mqtt", "LocalMqttService.smali"))
    text, n = re.subn(
        r"(invoke-static \{\}, Lce/h;->a\(\)Landroid/content/Intent;.{0,200}?)"
        r"invoke-virtual \{(\w+), \w+\}, Landroid/content/Context;->sendBroadcast\(Landroid/content/Intent;\)V",
        r"\1invoke-static {\2}, Lcom/uvp/Reset;->run(Landroid/content/Context;)V",
        _read(mqtt), count=1, flags=re.S)
    if n != 1:
        raise PatchError("anchor not found: LocalMqttService factory-reset broadcast")
    _write(mqtt, text)

    smali_root = sorted(glob.glob(os.path.join(decoded, "smali*")))[-1]
    dest = os.path.join(smali_root, "com", "uvp", "Reset.smali")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    _write(dest, _read(RESET_SMALI))
    _inject_method_start(_find_smali(decoded, os.path.join(app, "App.smali")), "onCreate()V",
                         "    invoke-static {p0}, Lcom/uvp/Reset;->onStart(Landroid/content/Context;)V\n",
                         "App.onCreate")
