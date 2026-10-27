# Quick Guide

Patch the UniFi Access Intercom Viewer firmware into an APK you can run on a
normal Android phone — in about 5 minutes. Works on **Debian/Linux**,
**Windows**, and **macOS**.

> You supply the official firmware `.zip` yourself. This tool ships no Ubiquiti
> code or firmware. See the [README](README.md) for the full details.

---

## 1. Install the prerequisites

You need: **Python 3.11+**, a **JDK (17+)**, **apktool**, Android **build-tools**
(`apksigner` + `zipalign`), and **adb** to push the APK to a phone.

### Debian / Ubuntu / Linux

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv default-jdk apktool apksigner zipalign adb
```

> `python3` must be 3.11 or newer (Debian 12+, Ubuntu 23.04+); check with
> `python3 --version`.
>
> Older Debian/Ubuntu without an `apktool` package: download `apktool.jar` from
> <https://apktool.org/>, then `export APKTOOL_JAR=/path/to/apktool.jar`.
> No `apksigner`/`zipalign` packages? Install the Android command-line tools and
> `sdkmanager "build-tools;34.0.0"`, then
> `export ANDROID_BUILD_TOOLS=$HOME/Android/Sdk/build-tools/34.0.0`.

### Windows (PowerShell) — the easy way

You only need **Python** and **adb**. The patcher can download the rest
(a portable JDK, Android build-tools, and apktool) for you.

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Google.PlatformTools      # adb
```

Then, after cloning (step 2), run the bootstrapper once — it drops the required
binaries into a local `tools\` folder, no system install needed:

```powershell
py bootstrap.py
```

> That's it — skip the JDK / Android Studio / apktool installs. The binaries live
> in `tools\` (git-ignored) and are used automatically. `bootstrap.py` works on
> Linux and macOS too if you'd rather not install the tools system-wide.

### macOS

```bash
brew install python openjdk apktool android-platform-tools
# build-tools: Android Studio SDK Manager, or:
brew install --cask android-commandlinetools && sdkmanager "build-tools;34.0.0"
```

---

## 2. Get the patcher

```bash
git clone https://github.com/rubaz100/unifi-intercom-viewer-patcher.git
cd unifi-intercom-viewer-patcher
```

Set up the one Python dependency (a virtual environment keeps it tidy):

**Linux / macOS**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
py -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Don't want to install the JDK / Android tools system-wide?** Run the
bootstrapper — it downloads a portable JDK, Android build-tools, and apktool
into a local `tools/` folder (required for the easy Windows path above; optional
elsewhere):

```bash
python3 bootstrap.py        # Windows: py bootstrap.py
```

---

## 3. Patch the firmware

Point it at your firmware zip:

**Linux / macOS**
```bash
python3 patch.py /path/to/IntercomViewerFirmware.zip -o IntercomViewer-portable.apk
```

**Windows (PowerShell)**
```powershell
py patch.py C:\path\to\IntercomViewerFirmware.zip -o IntercomViewer-portable.apk
```

It prints the MAC the device will advertise (a random Ubiquiti-OUI MAC). Running
it for **more than one phone?** Give each a unique MAC — see step 6.

---

## 4. Install on the phone

Enable **Developer options → USB debugging** on the phone, plug it in, accept the
prompt, then:

```bash
adb install -r -g IntercomViewer-portable.apk
```

Requirements: an **arm64 (arm64-v8a) phone on Android 9+**.

> Reinstalling later? Keep the **same keystore** (`--keystore portable.keystore`)
> so `adb install -r` upgrades it without wiping the adoption.

---

## 5. Adopt it in UniFi Access

The app opens to **“Ready to Adopt.”** Adopt it from the UniFi Access app or
`unifi.ui.com`, with the **controller on the same subnet/VLAN as the phone** —
UniFi discovery is subnet-local multicast and won’t cross VLANs or Wi-Fi client
isolation.

---

## 6. Multiple devices (unique MACs)

```bash
python3 genmac.py                 # one random Ubiquiti-OUI MAC
python3 genmac.py -n 5 --with-id  # five, with device ids
python3 patch.py fw.zip --mac $(python3 genmac.py)   # pin one when patching
```

On Windows:
```powershell
$mac = py genmac.py ; py patch.py fw.zip --mac $mac
```

---

## Troubleshooting

| Message | Fix |
|---|---|
| `apktool not found` | Install apktool, or `set/export APKTOOL_JAR` to `apktool.jar`. |
| `'zipalign'/'apksigner' not found` | Install Android build-tools; set `ANDROID_BUILD_TOOLS` if not auto-detected. |
| `java not found` | Install a JDK 17+ and reopen the terminal. |
| `anchor not found: …` | Your firmware version differs from the supported one (`v1.5.32`); open an issue. |
| `INSTALL_FAILED_NO_MATCHING_ABIS` | The phone isn’t arm64-v8a. Use a 64-bit ARM device. |
| Doesn’t show up in UniFi | Put the controller on the **same subnet/VLAN** as the phone; disable Wi-Fi client isolation. |
| `adb: no devices` | Enable USB debugging and accept the on-device prompt; on Windows install the OEM USB driver. |
