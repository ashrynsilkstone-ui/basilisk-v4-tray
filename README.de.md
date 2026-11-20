# OpenRazer Mouse Tray für KDE

[English](README.md) · [CachyOS und Arch](#installation-unter-cachyos-oder-arch-linux) · [Debian und Ubuntu](#installation-unter-debian-oder-ubuntu) · [Fedora](#installation-unter-fedora) · [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases)

Für **CachyOS mit KDE** gibt es ein natives Pacman-Paket und ein [PKGBUILD im Repository](packaging/cachyos/PKGBUILD).

Die Tray-App erkennt automatisch Mäuse und unterstützte Empfänger, die OpenRazer meldet. Sind mehrere Geräte angeschlossen, wählst du das gewünschte Gerät im Tray-Menü oder in den Einstellungen aus. Das Symbol zeigt, soweit verfügbar, die aktive DPI-Stufe und den Akkustand. Im Tooltip und im Menü steht zusätzlich die Pollingrate.

Ein Klick auf das Symbol öffnet die Einstellungen. Welche Regler erscheinen, hängt vom gewählten Gerät und dessen OpenRazer-Treiber ab. Je nach Maus kannst du DPI oder DPI-Stufen, Pollingrate, Akkuwarnung, Ruhezustand, Scrollrad und Beleuchtung einstellen. Bei der Viper V4 Pro am HyperSpeed-Empfänger (`1532:00E6`) lassen sich unter **Dongle** drei Status-LEDs einzeln einstellen. Klicke auf **Übernehmen**, um Änderungen zu speichern.

## Basilisk V4 Pro

Die Basilisk V4 Pro wird per USB (`1532:00E2`) und HyperSpeed (`1532:00E3`) unterstützt. Sind beide Verbindungen vorhanden, wählt der Tray standardmäßig USB. Logo, Scrollrad und Unterboden haben eigene Regler für Effekt und Helligkeit. Um eine statische Farbe erneut zu senden, bestätige sie im Farbdialog und klicke auf **Übernehmen**.

Im Reiter **Scrollrad** legst du unter **Modi beim Umschalten** fest, welche Modi die bereits belegte Maustaste im aktiven Profil durchläuft. Klick auf **Übernehmen**, um deine Änderungen zu speichern. Liegt der aktuelle Radmodus außerhalb der neuen Auswahl, wechselt der Tray in einen der freigegebenen Modi.

Smart Reel, seine fünf Empfindlichkeitsstufen und die Scrollbeschleunigung sind bei diesen Kombinationen verfügbar.

- **24 Rastpunkte und Freilauf**
- **48 Rastpunkte und Freilauf**
- **Alle drei Modi**

Smart Reel wechselt aus einem Rastmodus kurz in den Freilauf, wenn du das Rad schnell drehst. Die Scrollbeschleunigung wirkt im Freilauf. Wenn du **24 und 48 Rastpunkte** übernimmst, werden beide Funktionen ausgeschaltet.

Liefert die Maus keine Auswahl zurück, zeigt der Tray die zuletzt für dieses Profil und diese Verbindung gespeicherte Auswahl. Weist die Maus einen Modus zurück, sendet der Tray die ausgewählten Modi erneut. Die udev-Regel im Paket gibt der lokalen Desktop-Sitzung Zugriff auf die USB-Steuerschnittstelle beider Verbindungen. Falls der Zugriff nach der Installation fehlt, stecke das USB-Kabel oder den Dongle neu ein.

## Voraussetzungen

- Eine KDE-Plasma-Sitzung mit Benutzer-D-Bus und Systemtray
- OpenRazer-Kerneltreiber, Daemon und passende Python-Bibliothek mit Unterstützung für deine Maus. Die separate Unterbodenbeleuchtung der Basilisk benötigt die entsprechenden Treiber- und Daemon-Funktionen.

Die Pakete auf dieser Seite installieren die Tray-App und ihre Desktop-Einträge. Richte zuerst einen für deine Distribution passenden OpenRazer-Build ein und prüfe, ob er die Maus erkennt. Im zugehörigen Repository findest du den OpenRazer-Build, mit dem USB, HyperSpeed und die Unterbodenbeleuchtung getestet wurden. [Zugehöriges OpenRazer-Repository](https://github.com/ashrynsilkstone-ui/openrazer-basilisk-v4-pro) · [OpenRazer-Anleitung zur Treiberinstallation](https://openrazer.github.io/#download)

## Installation unter CachyOS oder Arch Linux

Lade die `.pkg.tar.zst`-Datei unter [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) herunter und führe im Downloadordner aus:

```sh
sudo pacman -U ./basilisk-v4-tray-0.2.0-1-any.pkg.tar.zst
```

Das Tray-Paket verwendet die installierte Python-Bibliothek `python-openrazer` und den vorhandenen OpenRazer-Daemon. Der [zugehörige OpenRazer-Zweig](https://github.com/ashrynsilkstone-ui/openrazer-basilisk-v4-pro/tree/basilisk-v4-pro-local) enthält die unter CachyOS getesteten Änderungen am Treiber und Daemon.

Zum Nachbauen aus dem lokalen Klon führst du `sh packaging/build-cachyos.sh` mit deinem normalen Benutzerkonto aus. Das Skript baut den lokalen Quellcode mit dem [PKGBUILD für CachyOS und Arch](packaging/cachyos/PKGBUILD).

Deinstallation:

```sh
sudo pacman -R basilisk-v4-tray
```

## Installation unter Debian oder Ubuntu

Lade die `.deb`-Datei unter [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) herunter und führe im Downloadordner aus:

```sh
sudo apt install ./basilisk-v4-tray_0.2.0_all.deb
```

Das Paket unterstützt die Qt-Bibliotheken aus Debian 13 und Ubuntu ab 24.04 LTS. Wenn APT unter Ubuntu das Qt-Binding nicht findet, aktiviere die Paketquelle **Universe**. Eine passende OpenRazer-Installation stellt `python3-openrazer` bereit.

Deinstallation:

```sh
sudo apt remove basilisk-v4-tray
```

## Installation unter Fedora

Richte OpenRazer zuerst nach der [Fedora-Anleitung](https://openrazer.github.io/#download) ein. Fedora bezieht `python3-openrazer` aus der OpenRazer-Paketquelle. Lade die `.rpm`-Datei unter [Releases](https://github.com/ashrynsilkstone-ui/basilisk-v4-tray/releases) herunter und führe aus:

```sh
sudo dnf install ./basilisk-v4-tray-0.2.0-1.noarch.rpm
```

Deinstallation:

```sh
sudo dnf remove basilisk-v4-tray
```

## Start und Autostart

Öffne **OpenRazer Mouse Tray** im KDE-Anwendungsmenü, um die App sofort zu starten. Jedes Paket richtet den Start bei der KDE-Anmeldung ein. Unter **Systemeinstellungen → Autostart** lässt er sich abschalten.

Eine frühere Installation im Benutzerkonto kann Vorrang vor den Einträgen des Pakets haben. Wenn KDE weiterhin eine ältere Kopie startet, prüfe die Dateien namens `local.razer.BasiliskTray.desktop` in `~/.config/autostart` und `~/.local/share/applications`.

## Start und Paketbau aus dem Quellcode

Wenn Python 3, dbus-python, die passende OpenRazer-Bibliothek sowie PySide6 oder PyQt6 eingerichtet sind, starte die App mit:

```sh
python3 razer_tray.py
```

`python3 install.py` legt das Anwendungsmenü und den Autostart für das aktuelle Benutzerkonto an. Der Installer nutzt `$XDG_DATA_HOME` und `$XDG_CONFIG_HOME`, standardmäßig `~/.local/share` und `~/.config`. Unter CachyOS und Arch heißen die Abhängigkeiten `pyside6`, `python-dbus` und `python-openrazer`.

Wähle im Repository-Verzeichnis den Befehl für deine Distribution. Der CachyOS-Build verwendet `makepkg` und GNU tar, der DEB-Build `dpkg-deb` und der RPM-Build `rpmbuild` und GNU tar.

```sh
sh packaging/build-cachyos.sh
sh packaging/build-deb.sh
sh packaging/build-rpm.sh
```

Die Skripte legen die Pakete standardmäßig in `dist/` ab. Als erstes Argument kannst du ein anderes Zielverzeichnis angeben.
