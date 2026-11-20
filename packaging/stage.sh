#!/bin/sh
set -eu

project=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
root=${1:?Usage: stage.sh DESTDIR}
desktop_id=local.razer.BasiliskTray.desktop

install -Dm 0644 "$project/razer_tray.py" "$root/usr/share/basilisk-v4-tray/razer_tray.py"
install -Dm 0755 "$project/packaging/basilisk-v4-tray" "$root/usr/bin/basilisk-v4-tray"
install -Dm 0644 "$project/packaging/launcher.desktop" "$root/usr/share/applications/$desktop_id"
install -Dm 0644 "$project/packaging/autostart.desktop" "$root/etc/xdg/autostart/$desktop_id"
install -Dm 0644 "$project/packaging/69-basilisk-v4-tray.rules" \
    "$root/usr/lib/udev/rules.d/69-basilisk-v4-tray.rules"
install -Dm 0644 "$project/README.md" "$root/usr/share/doc/basilisk-v4-tray/README.md"
install -Dm 0644 "$project/README.de.md" "$root/usr/share/doc/basilisk-v4-tray/README.de.md"
