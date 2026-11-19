# Basilisk V4 Pro im KDE-Systemtray

Die Tray-App zeigt Akkustand, aktive DPI-Stufe und Pollingrate einer Razer Basilisk V4 Pro am HyperSpeed-Dongle (`1532:00E3`) an. Die Zahl im Symbol steht für die DPI-Stufe, der Balken für den Akku. Im Tooltip und Kontextmenü stehen alle drei Werte.

Im Einstellungsfenster lassen sich DPI-Stufen, Pollingrate, Akku-Warnschwelle und Ruhezustand ändern. Der Reiter **Beleuchtung** steuert Helligkeit, Farbe und Effekt von Logo, Scrollrad und Unterboden separat.

## Voraussetzungen

- KDE Plasma mit einer laufenden D-Bus-Benutzersitzung
- OpenRazer mit Unterstützung für die Basilisk V4 Pro und ihre Unterbodenbeleuchtung
- Python 3 mit PySide6, dbus-python und der passenden OpenRazer-Clientbibliothek. Unter CachyOS und Arch heißen die Pakete `pyside6`, `python-dbus` und `python-openrazer`.

## Start und Installation

Zum direkten Start aus dem Klon:

```sh
python3 razer_tray.py
```

Für den Eintrag im KDE-Anwendungsmenü und den Autostart bei der Anmeldung:

```sh
python3 install.py
```

Danach lässt sich **Basilisk V4 Pro** im Anwendungsmenü öffnen. Ein Klick auf das Tray-Symbol öffnet die Einstellungen.

Der Installer schreibt unter `$XDG_DATA_HOME` und `$XDG_CONFIG_HOME`. Ohne diese Variablen liegen die Dateien unter `~/.local/share` und `~/.config`. Der Autostart lässt sich in den KDE-Systemeinstellungen unter **Autostart** deaktivieren.
