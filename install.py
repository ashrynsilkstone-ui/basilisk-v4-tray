import os
from pathlib import Path
from shutil import copyfile
import sys


DESKTOP_FILE = "local.razer.BasiliskTray.desktop"


def desktop_argument(value):
    argument = str(value).replace("%", "%%")
    argument = "".join("\\" + char if char in '\\"$`' else char for char in argument)
    return '"' + argument.replace("\\", "\\\\") + '"'


def main():
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    if not data.is_absolute() or not config.is_absolute():
        raise SystemExit("XDG_DATA_HOME und XDG_CONFIG_HOME müssen absolute Pfade sein.")

    source = Path(__file__).with_name("razer_tray.py")
    target = data / "razer-basilisk-tray" / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    copyfile(source, target)
    command = f"{desktop_argument(sys.executable)} {desktop_argument(target)}"

    launcher = data / "applications" / DESKTOP_FILE
    autostart = config / "autostart" / DESKTOP_FILE
    entry = (
        "[Desktop Entry]\nType=Application\nName=OpenRazer Mouse Tray\n"
        "Comment=Live-Status und Einstellungen für die Razer-Maus\n"
        "Icon=input-mouse\nTerminal=false\nStartupNotify=false\n"
    )
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(entry + f"Exec={command} --settings\nCategories=Settings;HardwareSettings;\n")
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text(entry + f"Exec={command}\nOnlyShowIn=KDE;\n")
    print("OpenRazer Mouse Tray ist im KDE-Anwendungsmenü und im Autostart eingerichtet.")


if __name__ == "__main__":
    main()
