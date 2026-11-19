# Basilisk V4 Pro im KDE-Systemtray

[English](README.md) · [Installationspakete](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases)

Die Tray-App zeigt Akkustand, aktive DPI-Stufe und Pollingrate einer Razer Basilisk V4 Pro am HyperSpeed-Dongle (`1532:00E3`). Die Zahl im Symbol steht für die DPI-Stufe, der Balken für den Akku. Im Tooltip und im Kontextmenü stehen alle drei Werte.

Ein Klick auf das Symbol öffnet die Einstellungen. Dort kannst du bis zu fünf DPI-Stufen mit getrennten X- und Y-Werten bearbeiten, die aktive Stufe und Pollingrate wählen sowie Akku-Warnschwelle und Ruhezustand einstellen. Im Reiter **Beleuchtung** haben Logo, Scrollrad und Unterboden eigene Regler für Helligkeit und Effekt. Zur Auswahl stehen Aus, statische Farbe, Farbwechsel und Welle.

## Voraussetzungen

- Eine KDE-Plasma-Sitzung mit Benutzer-D-Bus und Systemtray
- OpenRazer-Kerneltreiber, Daemon und passende Python-Bibliothek mit Unterstützung für den **HyperSpeed-Dongle der Basilisk V4 Pro**. Die separate Unterbodenbeleuchtung braucht zusätzlich die entsprechenden Treiber- und Daemon-Funktionen.

Die Pakete auf dieser Seite installieren die Tray-App und ihre Desktop-Einträge. Richte zuerst einen für deine Distribution passenden OpenRazer-Build ein und prüfe, ob er `1532:00E3` erkennt. Das [zugehörige OpenRazer-Repository](https://github.com/ashrynsilkstone-ui/openrazer-basilisk-v4-pro) enthält die Änderungen für Dongle und Unterboden, mit denen die App entwickelt wurde. Die [OpenRazer-Anleitung zur Distribution](https://openrazer.github.io/#download) beschreibt die Treiberinstallation.

## Installation unter Debian oder Ubuntu

Lade die `.deb`-Datei unter [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) herunter und führe im Downloadordner aus:

```sh
sudo apt install ./basilisk-v4-tray_0.1.0_all.deb
```

Das Paket unterstützt die Qt-Bibliotheken aus Debian 13 und Ubuntu ab 24.04 LTS. Wenn APT unter Ubuntu das Qt-Binding nicht findet, aktiviere die Paketquelle **Universe**. Eine passende OpenRazer-Installation stellt `python3-openrazer` bereit.

Deinstallation:

```sh
sudo apt remove basilisk-v4-tray
```

## Installation unter Fedora

Richte OpenRazer zuerst nach der [Fedora-Anleitung](https://openrazer.github.io/#download) ein. Fedora bezieht `python3-openrazer` aus der OpenRazer-Paketquelle. Lade die `.rpm`-Datei unter [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) herunter und führe aus:

```sh
sudo dnf install ./basilisk-v4-tray-0.1.0-1.noarch.rpm
```

Deinstallation:

```sh
sudo dnf remove basilisk-v4-tray
```

## Start und Autostart

Öffne **Basilisk V4 Pro** im KDE-Anwendungsmenü, um die App sofort zu starten. Beide Pakete richten den Start bei der KDE-Anmeldung ein. Unter **Systemeinstellungen → Autostart** lässt er sich abschalten.

Eine frühere Installation im Benutzerkonto kann Vorrang vor den Einträgen des Pakets haben. Wenn KDE weiterhin eine ältere Kopie startet, prüfe die Dateien namens `local.razer.BasiliskTray.desktop` in `~/.config/autostart` und `~/.local/share/applications`.

## Start und Paketbau aus dem Quellcode

Wenn Python 3, dbus-python, die passende OpenRazer-Bibliothek sowie PySide6 oder PyQt6 eingerichtet sind, starte die App mit:

```sh
python3 razer_tray.py
```

`python3 install.py` legt das Anwendungsmenü und den Autostart für das aktuelle Benutzerkonto an. Der Installer nutzt `$XDG_DATA_HOME` und `$XDG_CONFIG_HOME`, standardmäßig `~/.local/share` und `~/.config`. Unter CachyOS und Arch heißen die Abhängigkeiten `pyside6`, `python-dbus` und `python-openrazer`.

Die Pakete lassen sich im Repository-Verzeichnis nachbauen. Der erste Befehl benötigt `dpkg-deb`, der zweite `rpmbuild` und GNU tar:

```sh
sh packaging/build-deb.sh
sh packaging/build-rpm.sh
```

Die Skripte legen die Pakete standardmäßig in `dist/` ab. Als erstes Argument kannst du ein anderes Zielverzeichnis angeben.
