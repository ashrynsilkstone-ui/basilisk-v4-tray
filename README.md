# Basilisk V4 Pro Tray for KDE

[Deutsch](README.de.md) · [CachyOS and Arch](#install-on-cachyos-or-arch-linux) · [Debian and Ubuntu](#install-on-debian-or-ubuntu) · [Fedora](#install-on-fedora) · [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases)

**CachyOS KDE** has a native Pacman package and a [PKGBUILD in this repository](packaging/cachyos/PKGBUILD).

See the battery level, active DPI stage and polling rate of a Razer Basilisk V4 Pro connected through its HyperSpeed receiver (`1532:00E3`). The number in the tray icon is the DPI stage and the bar is the battery level. Hover over the icon or open its context menu for all three readings.

Click the icon to open the settings. You can configure up to five DPI stages with separate X and Y values, select the active stage and polling rate, and adjust the low-battery warning and sleep timeout. On the **Beleuchtung** tab, the logo, scroll wheel and underglow each have their own brightness and effect. The available effects are off, static color, color cycling and wave. To resend a static color, confirm it again in the color picker and click **Übernehmen**.

In **Scrollrad** (scroll wheel), choose free spin or a tactile mode with 24 or 48 notches. You can also set scroll acceleration and Smart Reel, which switches to free spin automatically when you scroll quickly. Click **Übernehmen** to apply. If the mouse rejects a mode, the tray reenables all three modes in the active mouse profile and tries again. The packaged udev rule gives the local desktop session access to the receiver’s control interface for this repair. Reconnect the receiver after installation if access is denied.

## Requirements

- A KDE Plasma session with a working user D-Bus and system tray
- OpenRazer's kernel driver, daemon and matching Python client with support for the **Basilisk V4 Pro HyperSpeed receiver**. Separate underglow controls require the corresponding driver and daemon support.

The packages on this page install the tray app and its desktop entries. Set up a compatible OpenRazer build for your distribution and confirm that it sees `1532:00E3` before using the tray. The [companion OpenRazer repository](https://github.com/ashrynsilkstone-ui/openrazer-basilisk-v4-pro) contains the receiver and underglow changes used to develop the app. See [OpenRazer's distribution instructions](https://openrazer.github.io/#download) for driver setup.

## Install on CachyOS or Arch Linux

Download the `.pkg.tar.zst` from [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) and run this in the download directory:

```sh
sudo pacman -U ./basilisk-v4-tray-0.1.4-1-any.pkg.tar.zst
```

The tray package uses `python-openrazer` and the OpenRazer daemon already installed on the system. The [companion OpenRazer branch](https://github.com/ashrynsilkstone-ui/openrazer-basilisk-v4-pro/tree/basilisk-v4-pro-local) contains the driver and daemon changes tested with CachyOS.

To build the Pacman package from this checkout, run `sh packaging/build-cachyos.sh` as your regular user. The script builds from the local source using [the CachyOS/Arch PKGBUILD](packaging/cachyos/PKGBUILD).

To uninstall:

```sh
sudo pacman -R basilisk-v4-tray
```

## Install on Debian or Ubuntu

Download the `.deb` from [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases), then run this in the download directory:

```sh
sudo apt install ./basilisk-v4-tray_0.1.4_all.deb
```

The package supports the Qt libraries available on Debian 13 and Ubuntu 24.04 LTS or newer. On Ubuntu, enable the **Universe** repository if APT cannot find the Qt binding. A compatible OpenRazer installation provides `python3-openrazer`.

To uninstall:

```sh
sudo apt remove basilisk-v4-tray
```

## Install on Fedora

Set up OpenRazer first using its [Fedora instructions](https://openrazer.github.io/#download). Fedora obtains `python3-openrazer` from the OpenRazer package repository. Download the `.rpm` from [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases), then run:

```sh
sudo dnf install ./basilisk-v4-tray-0.1.4-1.noarch.rpm
```

To uninstall:

```sh
sudo dnf remove basilisk-v4-tray
```

## Start the app and manage autostart

Open **Basilisk V4 Pro** from the KDE application menu to start it immediately. Each package adds a KDE login autostart entry. Use **System Settings → Autostart** to turn it off.

A previous per-user installation can override the packaged desktop entries. If KDE still launches an older copy, check the entries named `local.razer.BasiliskTray.desktop` in `~/.config/autostart` and `~/.local/share/applications`.

## Install or build from source

With Python 3, dbus-python, a compatible OpenRazer client and either PySide6 or PyQt6 installed, run:

```sh
python3 razer_tray.py
```

Run `python3 install.py` to add a menu entry and autostart for the current user. It uses `$XDG_DATA_HOME` and `$XDG_CONFIG_HOME`, which default to `~/.local/share` and `~/.config`. On CachyOS and Arch, the dependencies are `pyside6`, `python-dbus` and `python-openrazer`.

Build from the repository root using the command for your distribution. The CachyOS build uses `makepkg` and GNU tar, the DEB build uses `dpkg-deb`, and the RPM build uses `rpmbuild` and GNU tar.

```sh
sh packaging/build-cachyos.sh
sh packaging/build-deb.sh
sh packaging/build-rpm.sh
```

The build scripts place the packages in `dist/` by default. Pass a directory as the first argument to use another destination.
