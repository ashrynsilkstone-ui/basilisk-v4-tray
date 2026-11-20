from __future__ import annotations

from dataclasses import dataclass
from fcntl import ioctl
import logging
from pathlib import Path
import struct
import sys
from time import monotonic, sleep

from dbus import DBusException, Interface, SessionBus
from openrazer.client.device import RazerDeviceFactory

try:
    from PySide6.QtCore import ClassInfo, QObject, QRectF, QSettings, Qt, QThread, QTimer, Signal, Slot
    from PySide6.QtDBus import QDBus, QDBusAbstractAdaptor, QDBusConnection, QDBusMessage
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
        QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSpinBox,
        QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
    )
except ModuleNotFoundError as error:
    if not (error.name or "").startswith("PySide6"):
        raise
    from PyQt6.QtCore import QObject, QRectF, QSettings, Qt, QThread, QTimer
    from PyQt6.QtCore import pyqtClassInfo
    from PyQt6.QtCore import pyqtSignal as Signal, pyqtSlot as Slot
    from PyQt6.QtDBus import QDBus, QDBusAbstractAdaptor, QDBusConnection, QDBusMessage
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
        QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMenu, QPushButton, QSpinBox,
        QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget,
    )
    ClassInfo = None


NAME = "OpenRazer Mouse Tray"
DESKTOP_ID = "local.razer.BasiliskTray"
BUS_PATH = "/BasiliskTray"
DEVICE_ERRORS = (DBusException, OSError, ValueError, NotImplementedError)
DISCONNECTED = "Warte auf eine von OpenRazer erkannte Maus …"
RAZER_VENDOR = 0x1532
BASILISK_WIRED = 0x00E2
BASILISK_RECEIVER = 0x00E3
VIPER_RECEIVER = 0x00E6
USB_DEVICES = Path("/sys/bus/usb/devices")
DEFAULT_STAGES = (1200, 1600, 2400, 3200, 6400)
LIGHT_ZONES = {
    "global": ("Gerät", ""), "logo": ("Logo", "logo"),
    "scroll_wheel": ("Scrollrad", "scroll"), "backlight": ("Unterboden", "backlight"),
    "left": ("Linke Seite", "left"), "right": ("Rechte Seite", "right"),
    "charging": ("Laden", "charging"), "fast_charging": ("Schnellladen", "fast_charging"),
    "fully_charged": ("Voll geladen", "fully_charged"),
}
LIGHT_EFFECTS = {"none": "Aus", "static": "Statisch", "spectrum": "Farbwechsel", "wave": "Welle"}
LED_MODES = {
    1: ("Aus", "An", "Akkustand", "Verbindung", "Kopplung"),
    3: ("Aus", "Akkustand", "Verbindungsqualität", "Pollingrate", "DPI-Stufe"),
}
FREE_SPIN = 1
SCROLL_MODES = (0, 2, FREE_SPIN)
SCROLL_ASSISTS = ("scroll_acceleration", "scroll_smart_reel")
SCROLL_SETTINGS = ("scroll_mode", *SCROLL_ASSISTS)
SMART_REEL_LEVELS = range(5)
SCROLL_CYCLE_LABEL = "Modi beim Umschalten"
SCROLL_CYCLES = {
    0b101: "24 und 48 Rastpunkte",
    0b011: "24 Rastpunkte und Freilauf",
    0b110: "48 Rastpunkte und Freilauf",
    0b111: "Alle drei Modi",
}


class ScrollModeError(OSError):
    pass


def cycle_has_free_spin(cycle):
    return cycle is not None and bool(cycle & (1 << FREE_SPIN))


def feature_report(device, command_class, command, arguments, expected_prefix=b""):
    # The hidraw buffer starts with the report ID, followed by the 90-byte Razer report.
    report = bytearray(91)
    report[2] = 0x1F
    report[6:9] = bytes((len(arguments), command_class, command))
    report[9:9 + len(arguments)] = arguments
    for value in report[3:89]:
        report[89] ^= value

    for backoff in (0, 0.08, 0.15, 0.23, 0.32):
        if backoff:
            sleep(backoff)
        if ioctl(device, 0xC05B4806, report) not in (90, 91):  # HIDIOCSFEATURE(91)
            continue
        # Read promptly before the driver issues another command. Allow a busy
        # receiver time to deliver the reply before resending the request.
        for delay in (0.012, 0.024, 0.05):
            sleep(delay)
            reply = bytearray(91)
            length = ioctl(device, 0xC05B4807, reply)  # HIDIOCGFEATURE(91)
            if length != len(reply) or reply[2] != report[2] or reply[7:9] != report[7:9]:
                continue
            if reply[1] != 0x02 or reply[6] != len(arguments):
                continue
            payload = bytes(reply[9:9 + reply[6]])
            if payload.startswith(expected_prefix):
                return payload
    raise OSError(f"Keine passende Antwort auf den HID-Befehl {command_class:02x}:{command:02x}.")


def control_interfaces(product_id):
    return USB_DEVICES.glob(f"*:1.3/0003:{RAZER_VENDOR:04X}:{product_id:04X}.*")


def paired_serial_matches(hid, serial, product_id):
    # The kernel HID serial identifies the receiver. OpenRazer identifies its paired mouse.
    usb = hid.resolve().parent.parent
    prefix = f"0003:{RAZER_VENDOR:04X}:{product_id:04X}."
    for path in usb.glob(f"{usb.name}:*.*/{prefix}*/device_serial"):
        if optional(lambda: path.read_text().strip()) == serial:
            return True
    return False


def open_control_device(serial, product_id):
    nodes = []
    for hid in control_interfaces(product_id):
        identity = optional(lambda: (hid / "uevent").read_text().splitlines(), ())
        if f"HID_UNIQ={serial}" in identity or (
            product_id == VIPER_RECEIVER and paired_serial_matches(hid, serial, product_id)
        ):
            nodes.extend(hid.glob("hidraw/hidraw*"))
    if len(nodes) != 1:
        raise OSError("Die HID-Steuerschnittstelle der Maus konnte nicht eindeutig zugeordnet werden.")

    device = open(Path("/dev") / nodes[0].name, "r+b", buffering=0)
    info = bytearray(8)
    try:
        ioctl(device, 0x80084803, info)  # HIDIOCGRAWINFO
        if struct.unpack("=IHH", info) != (0x0003, RAZER_VENDOR, product_id):
            raise OSError("Der HID-Steueranschluss gehört nicht zum ausgewählten Gerät.")
    except OSError:
        device.close()
        raise
    return device


def optional(fetch, default=None):
    try:
        return fetch()
    except DEVICE_ERRORS as exc:
        logging.debug("OpenRazer-Einstellung nicht lesbar: %s", exc)
        return default


def active_scroll_profile(device):
    profile, = feature_report(device, 0x05, 0x84, b"\x00")
    if not 1 <= profile <= 5:
        raise OSError(f"Die Maus meldet ein ungültiges aktives Profil ({profile}).")
    return profile


def read_scroll_mask(device, bank):
    prefix = bytes((bank,))
    _, mask = feature_report(device, 0x15, 0x8B, prefix + b"\x00", prefix)
    return mask


def write_scroll_cycle(device, profile, cycle):
    # Update the saved profile first, then the live slot. Preserve unrelated bits.
    masks = {bank: read_scroll_mask(device, bank) for bank in (profile, 0)}
    for bank, mask in masks.items():
        arguments = bytes((bank, (mask & ~0b111) | cycle))
        feature_report(device, 0x15, 0x0B, arguments, arguments)


def read_smart_reel_level(device, bank):
    prefix = bytes((bank,))
    _, level = feature_report(device, 0x02, 0xA3, prefix + b"\x00", prefix)
    if level not in SMART_REEL_LEVELS:
        raise ScrollModeError(f"Die Maus meldet eine ungültige Smart-Reel-Stufe ({level + 1}).")
    return level


def write_smart_reel_level(device, profile, level):
    levels = {bank: read_smart_reel_level(device, bank) for bank in (profile, 0)}
    if all(previous == level for previous in levels.values()):
        return

    try:
        for bank in levels:
            arguments = bytes((bank, level))
            feature_report(device, 0x02, 0x23, arguments, arguments)
        if any(read_smart_reel_level(device, bank) != level for bank in levels):
            raise ScrollModeError("Die Maus hat die Smart-Reel-Empfindlichkeit anders zurückgemeldet.")
    except OSError:
        # A profile write can also update the live level, so restore both banks.
        for bank, previous in levels.items():
            arguments = bytes((bank, previous))
            try:
                feature_report(device, 0x02, 0x23, arguments, arguments)
            except OSError as exc:
                logging.warning("Smart-Reel-Stufe wiederherstellen: %s", exc)
        raise


@dataclass(frozen=True)
class DeviceChoice:
    serial: str
    vendor: int
    product: int
    name: str
    owner: str

    @property
    def identity(self):
        return self.serial, self.vendor, self.product

    @property
    def basilisk(self):
        return self.vendor == RAZER_VENDOR and self.product in (BASILISK_WIRED, BASILISK_RECEIVER)

    @property
    def viper_receiver(self):
        return self.vendor == RAZER_VENDOR and self.product == VIPER_RECEIVER


@dataclass(frozen=True)
class Reading:
    battery: int | None
    charging: bool
    stage: int
    dpi: tuple[tuple[int, int], ...]
    polling: int | None
    sensitivity: tuple[int, int] | None = None

    def labels(self):
        labels = []
        if self.battery is not None:
            labels.append(f"Akku {self.battery} %" + (" · lädt" if self.charging else ""))
        if 1 <= self.stage <= len(self.dpi):
            x, y = self.dpi[self.stage - 1]
            value = str(x) if x == y else f"{x} × {y}"
            labels.append(f"DPI-Stufe {self.stage}/{len(self.dpi)} · {value} DPI")
        elif self.sensitivity:
            x, y = self.sensitivity
            value = str(x) if x == y or not y else f"{x} × {y}"
            labels.append(f"{value} DPI")
        if self.polling:
            labels.append(f"Polling {self.polling} Hz")
        return tuple(labels) or ("Verbunden",)


@dataclass(frozen=True)
class Settings:
    reading: Reading
    max_dpi: int
    rates: tuple[int, ...]
    threshold: int | None
    idle: int | None
    lights: dict[str, "Light"]
    scroll: dict[str, int | bool]
    scroll_profile: int | None = None
    scroll_cycle: int | None = None
    scroll_cycle_cached: bool = False
    wired: bool = False
    smart_reel_level: int | None = None
    basilisk: bool = False
    dpi_presets: tuple[int, ...] = ()
    indicators: tuple[int, ...] | None = None
    direct_indicators: bool = False
    receiver_error: str = ""


@dataclass(frozen=True)
class Light:
    effect: str | None
    brightness: int | None
    color: tuple[int, int, int]
    direction: int
    effects: tuple[str, ...]

    @classmethod
    def read(cls, zone, prefix, brightness):
        effects = tuple(effect for effect in LIGHT_EFFECTS if zone.has(prefix + effect))
        effect = optional(lambda: zone.effect) if effects else None
        colors = optional(lambda: tuple(zone.colors[:3]), ()) if "static" in effects else ()
        direction = optional(lambda: zone.wave_dir, 1) if "wave" in effects else 1
        return cls(effect, brightness, colors if len(colors) == 3 else (0, 255, 0), direction, effects)


class MouseWorker(QObject):
    updated = Signal(object)
    devices_changed = Signal(object, object)
    settings_ready = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.mouse = None
        self.product_id = None
        self.battery = (None, False)
        self.next_battery_check = None
        self.bus = None
        self.owner = None
        self.catalog = {}
        self.selection = None
        self.preferred = None

    def detect(self):
        if self.bus is None:
            self.bus = SessionBus()
        owner = self.bus.get_name_owner("org.razer")
        root = self.bus.get_object(owner, "/org/razer", introspect=False)
        serials = Interface(root, "razer.devices").getDevices(timeout=2)
        previous = self.catalog if owner == self.owner else {}
        catalog = {}
        for serial in serials:
            try:
                obj = self.bus.get_object(owner, f"/org/razer/device/{serial}", introspect=False)
                misc = Interface(obj, "razer.device.misc")
                vendor, product = map(int, misc.getVidPid(timeout=2))
                entry = previous.get(serial)
                if entry is None or (entry[0].vendor, entry[0].product) != (vendor, product):
                    kind = str(misc.getDeviceType(timeout=2))
                    if kind not in ("mouse", "accessory", "dongle"):
                        continue
                    mouse = RazerDeviceFactory.get_device(serial)
                    if kind != "mouse" and not (
                        mouse.has("hyperpolling_indicator_led")
                        or mouse.has("hyperpolling_multi_indicator_led_modes")
                        or "dongle" in mouse.name.lower()
                        or "receiver" in mouse.name.lower()
                    ):
                        continue
                    entry = (DeviceChoice(str(serial), vendor, product, mouse.name, str(owner)), mouse)
                catalog[str(serial)] = entry
            except DEVICE_ERRORS as exc:
                logging.debug("Gerät wurde noch nicht eingelesen: %s", exc)
        choices = tuple(sorted((item[0] for item in catalog.values()), key=lambda choice: (
            not (choice.basilisk and choice.product == BASILISK_WIRED), choice.name.casefold(), choice.serial
        )))
        selection = next((choice for choice in choices
                          if self.preferred is not None and choice.identity == self.preferred.identity),
                         next(iter(choices), None))
        changed = owner != self.owner or selection != self.selection
        if changed:
            self.battery = (None, False)
            self.next_battery_check = None
        previous_choices = {item[0] for item in self.catalog.values()}
        self.owner, self.catalog, self.selection = owner, catalog, selection
        self.mouse = catalog[selection.serial][1] if selection else None
        self.product_id = selection.product if selection else None
        if changed or previous_choices != set(choices):
            self.devices_changed.emit(choices, selection)
        return changed

    @Slot(object)
    def select(self, choice):
        self.preferred = choice
        self.refresh()

    def scroll_cycle_key(self, profile):
        prefix = "scroll-cycle/wired" if self.product_id == BASILISK_WIRED else "scroll-cycle"
        return f"{prefix}/{self.mouse.serial}/{profile}"

    def read_scroll_cycle(self):
        if not getattr(self.mouse, "serial", None):
            return None, None, False
        with open_control_device(self.mouse.serial, self.product_id) as device:
            profile = active_scroll_profile(device)
            live = read_scroll_mask(device, 0) & 0b111
        if live in SCROLL_CYCLES:
            return profile, live, False
        # The firmware can echo a zero mask even after acknowledging a successful write.
        saved = QSettings("BasiliskV4Tray", "BasiliskV4Tray").value(
            self.scroll_cycle_key(profile), 0, type=int
        )
        return profile, saved if saved in SCROLL_CYCLES else None, saved in SCROLL_CYCLES

    def set_scroll_cycle(self, profile, cycle):
        if cycle not in SCROLL_CYCLES:
            raise ScrollModeError("Wähle mindestens zwei Modi zum Umschalten.")
        with open_control_device(self.mouse.serial, self.product_id) as device:
            if active_scroll_profile(device) != profile:
                raise ScrollModeError("Das Mausprofil wurde gewechselt. Wähle die Modi erneut.")
            write_scroll_cycle(device, profile, cycle)
        preferences = QSettings("BasiliskV4Tray", "BasiliskV4Tray")
        preferences.setValue(self.scroll_cycle_key(profile), cycle)
        preferences.sync()

    def set_smart_reel_level(self, wired, profile, level):
        if (self.product_id == BASILISK_WIRED) != wired:
            raise ScrollModeError("Die Verbindung wurde gewechselt. Öffne die Einstellungen erneut.")
        if level not in SMART_REEL_LEVELS:
            raise ScrollModeError("Wähle eine Smart-Reel-Stufe von 1 bis 5.")
        with open_control_device(self.mouse.serial, self.product_id) as device:
            if active_scroll_profile(device) != profile:
                raise ScrollModeError("Das Mausprofil wurde gewechselt. Wähle die Smart-Reel-Stufe erneut.")
            write_smart_reel_level(device, profile, level)

    def read(self, refresh_battery=False):
        if self.mouse is None:
            return None
        mouse = self.mouse
        stage, dpi = optional(lambda: mouse.dpi_stages, (0, ())) if mouse.has("dpi_stages") else (0, ())
        sensitivity = optional(lambda: mouse.dpi) if not dpi and mouse.has("dpi") else None
        polling = optional(lambda: mouse.poll_rate) if mouse.has("poll_rate") else None
        now = monotonic()
        if mouse.has("battery") and (
            refresh_battery or self.next_battery_check is None or now >= self.next_battery_check
        ):
            level = optional(lambda: mouse.battery_level)
            charging = optional(lambda: mouse.is_charging, False)
            self.battery = (level if level is not None and 0 <= level <= 100 else None, charging)
            self.next_battery_check = now + 10
        return Reading(*self.battery, stage, tuple(dpi), polling if polling and polling > 0 else None, sensitivity)

    def mark_disconnected(self):
        if self.catalog:
            self.devices_changed.emit((), None)
        self.catalog.clear()
        self.owner = self.selection = self.product_id = None
        self.mouse = None
        self.battery = (None, False)
        self.next_battery_check = None
        self.updated.emit(None)

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(900)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    @Slot()
    def refresh(self):
        try:
            self.detect()
            self.updated.emit(self.read())
        except DEVICE_ERRORS:
            self.mark_disconnected()

    def set_scroll_mode(self, mode, cycle):
        self.mouse.scroll_mode = mode
        sleep(0.5)
        if self.mouse.scroll_mode == mode:
            return
        repair_error = None
        try:
            with open_control_device(self.mouse.serial, self.product_id) as device:
                profile = active_scroll_profile(device)
                write_scroll_cycle(device, profile, cycle)
        except OSError as exc:
            repair_error = exc
        self.mouse.scroll_mode = mode
        sleep(0.5)
        if self.mouse.scroll_mode == mode:
            return
        if isinstance(repair_error, PermissionError):
            raise ScrollModeError(
                "Der Tray hat keinen HID-Zugriff auf die Maus. "
                "Verbinde die Maus erneut oder melde dich erneut an."
            ) from repair_error
        if repair_error is not None:
            raise ScrollModeError(
                f"Scrollradmodi konnten nicht freigegeben werden. {repair_error}"
            ) from repair_error
        raise ScrollModeError("Die Maus hat den gewählten Scrollradmodus erneut zurückgewiesen.")

    def light_zone(self, name):
        mouse = self.mouse
        if name == "global":
            return mouse.fx, "", mouse if mouse.has("brightness") else None
        _, prefix = LIGHT_ZONES[name]
        zone = getattr(mouse.fx.misc, name, None)
        return zone, prefix + "_", zone if mouse.has(f"lighting_{prefix}_brightness") else None

    def read_lights(self):
        lights = {}
        for name in LIGHT_ZONES:
            zone, prefix, brightness_owner = self.light_zone(name)
            if zone is None:
                continue
            brightness = optional(lambda: round(brightness_owner.brightness)) if brightness_owner else None
            light = Light.read(zone, prefix, brightness)
            if light.effect is not None or light.brightness is not None:
                lights[name] = light
        return lights

    def read_indicators(self):
        mouse = self.mouse
        if mouse.has("hyperpolling_multi_indicator_led_modes"):
            modes = optional(mouse.get_hyperpolling_multi_indicator_led_modes)
            if modes is not None:
                return modes, False, ""
        if self.selection.viper_receiver:
            try:
                with open_control_device(self.selection.serial, self.selection.product) as device:
                    return tuple(feature_report(device, 0x07, 0x95, b"\x00" * 3)), True, ""
            except OSError as exc:
                logging.debug("Dongle-LEDs lesen: %s", exc)
                return None, False, "Dongle-LEDs nicht lesbar. Lade die Einstellungen neu oder verbinde den Dongle erneut."
        if mouse.has("hyperpolling_indicator_led"):
            mode = optional(mouse.get_hyperpolling_indicator_led)
            if mode is not None:
                return (mode,), False, ""
        return None, False, ""

    def set_indicators(self, current, modes):
        previous = current.indicators
        if previous is None or len(modes) != len(previous) or any(
            not 0 <= mode < len(LED_MODES[len(previous)]) for mode in modes
        ):
            raise ValueError("Ungültige Dongle-LED-Modi.")
        if current.direct_indicators:
            with open_control_device(self.selection.serial, self.selection.product) as device:
                data = bytes(modes)
                feature_report(device, 0x07, 0x15, data, data)
        elif len(modes) == 3:
            self.mouse.set_hyperpolling_multi_indicator_led_modes(*modes)
        else:
            self.mouse.set_hyperpolling_indicator_led(modes[0])

    def apply(self, state, changes):
        mouse = self.mouse
        current = state.reading
        scroll_edits = changes.get("scroll", {})
        scroll = {key: scroll_edits[key] for key in SCROLL_ASSISTS if key in scroll_edits}
        for key in scroll_edits:
            if key not in state.scroll:
                raise ValueError(f"Scrollradeinstellung {key} ist nicht verfügbar.")
        for key, available in (
            ("dpi", bool(current.dpi and state.max_dpi)),
            ("stage", bool(current.dpi and state.max_dpi)),
            ("sensitivity", current.sensitivity is not None and bool(state.max_dpi)),
            ("polling", changes.get("polling") in (*state.rates, current.polling)),
            ("threshold", state.threshold is not None),
            ("idle", state.idle is not None),
            ("indicators", state.indicators is not None),
        ):
            if key in changes and not available:
                raise ValueError(f"Einstellung {key} ist gerade nicht verfügbar.")
        for name, edits in changes.get("lights", {}).items():
            light = state.lights.get(name)
            if light is None or ("brightness" in edits and light.brightness is None) or (
                "effect" in edits and edits["effect"] not in light.effects
            ):
                raise ValueError(f"Beleuchtungszone {LIGHT_ZONES[name][0]} ist gerade nicht verfügbar.")
        cycle_edit = changes.get("scroll_cycle")
        if state.basilisk and (any(scroll.values()) or "smart_reel_level" in changes):
            cycle = cycle_edit[1] if cycle_edit is not None else self.read_scroll_cycle()[1]
            if not cycle_has_free_spin(cycle):
                raise ScrollModeError(
                    f"Wähle unter „{SCROLL_CYCLE_LABEL}“ eine Kombination mit Freilauf."
                )

        dpi = changes.get("dpi", current.dpi)
        stage = changes.get("stage", min(max(current.stage, 1), len(dpi)))
        if ("dpi" in changes or "stage" in changes) and (stage, dpi) != (current.stage, current.dpi):
            if not 1 <= stage <= len(dpi) <= len(DEFAULT_STAGES):
                raise ValueError("Ungültige aktive DPI-Stufe.")
            mouse.dpi_stages = stage, list(dpi)
            actual_stage, actual_dpi = mouse.dpi_stages
            if (actual_stage, tuple(actual_dpi)) != (stage, dpi):
                raise ValueError("Die Maus hat die DPI-Stufen anders zurückgemeldet.")
            if mouse.has("dpi"):
                mouse.dpi = dpi[stage - 1]
        if "sensitivity" in changes:
            mouse.dpi = changes["sensitivity"]
        if "polling" in changes:
            mouse.poll_rate = changes["polling"]
        if "threshold" in changes and changes["threshold"] != mouse.get_low_battery_threshold():
            mouse.set_low_battery_threshold(changes["threshold"])
        if "idle" in changes and changes["idle"] != mouse.get_idle_time():
            mouse.set_idle_time(changes["idle"])
        if cycle_edit is not None:
            profile, cycle = cycle_edit
            self.set_scroll_cycle(profile, cycle)
            if not cycle_has_free_spin(cycle):
                for key in SCROLL_ASSISTS:
                    if mouse.has(key) and getattr(mouse, key):
                        scroll[key] = False
        for key, enabled in scroll.items():
            if not enabled:
                setattr(mouse, key, False)
        if "scroll_mode" in scroll_edits and not state.basilisk:
            mouse.scroll_mode = scroll_edits["scroll_mode"]
        if cycle_edit is not None:
            if not cycle & (1 << mouse.scroll_mode):
                mode = next(value for value in SCROLL_MODES if cycle & (1 << value))
                self.set_scroll_mode(mode, cycle)
        if "smart_reel_level" in changes:
            self.set_smart_reel_level(*changes["smart_reel_level"])
        for key, enabled in scroll.items():
            if enabled:
                setattr(mouse, key, True)
        for name, edits in changes.get("lights", {}).items():
            light = state.lights[name]
            zone, _, brightness_owner = self.light_zone(name)
            effect = edits.get("effect", light.effect)
            if "brightness" in edits:
                brightness_owner.brightness = edits["brightness"]
            if effect == "static" and ("effect" in edits or "color" in edits):
                zone.static(*edits.get("color", light.color))
            elif effect == "wave" and ("effect" in edits or "direction" in edits):
                zone.wave(edits.get("direction", light.direction))
            elif effect == "spectrum" and "effect" in edits:
                zone.spectrum()
            elif effect == "none" and "effect" in edits:
                zone.none()
        if "indicators" in changes:
            self.set_indicators(state, changes["indicators"])

    def read_settings(self, refresh_battery=False):
        reading = self.read(refresh_battery=refresh_battery)
        if reading is None:
            raise OSError(DISCONNECTED)
        mouse = self.mouse
        basilisk = self.selection.basilisk
        scroll = {}
        for key in SCROLL_SETTINGS:
            if mouse.has(key):
                value = optional(lambda: getattr(mouse, key))
                if value is not None:
                    scroll[key] = value
        profile, cycle, cached = None, None, False
        smart_reel_level = None
        if basilisk and "scroll_mode" in scroll:
            profile, cycle, cached = optional(self.read_scroll_cycle, (None, None, False))
        if profile is not None and "scroll_smart_reel" in scroll:
            def read_level():
                with open_control_device(mouse.serial, self.product_id) as device:
                    return read_smart_reel_level(device, 0)
            smart_reel_level = optional(read_level)
        indicators, direct, receiver_error = self.read_indicators()
        return Settings(
            reading=reading,
            max_dpi=optional(lambda: mouse.max_dpi, 0) if mouse.has("dpi") else 0,
            rates=optional(lambda: tuple(mouse.supported_poll_rates), ()),
            threshold=optional(mouse.get_low_battery_threshold) if mouse.has("low_battery_threshold") else None,
            idle=optional(mouse.get_idle_time) if mouse.has("idle_time") else None,
            lights=self.read_lights(),
            scroll=scroll,
            scroll_profile=profile,
            scroll_cycle=cycle,
            scroll_cycle_cached=cached,
            wired=basilisk and self.product_id == BASILISK_WIRED,
            smart_reel_level=smart_reel_level,
            basilisk=basilisk,
            dpi_presets=optional(lambda: tuple(mouse.available_dpi), ()),
            indicators=indicators,
            direct_indicators=direct,
            receiver_error=receiver_error,
        )

    @Slot(object)
    def settings(self, request):
        selection, changes = request
        error = ""
        try:
            changed = self.detect()
            if changes and (selection != self.selection or changed):
                error = "Das ausgewählte Gerät hat sich geändert. Die Einstellungen wurden neu geladen."
                changes = None
            state = self.read_settings(refresh_battery=True)
            if changes:
                try:
                    self.apply(state, changes)
                except ScrollModeError as exc:
                    logging.warning("Scrollradmodus übernehmen: %s", exc)
                    error = str(exc)
                except DEVICE_ERRORS as exc:
                    logging.warning("Einstellungen übernehmen: %s", exc)
                    error = "Das Gerät konnte die Einstellungen nur teilweise oder gar nicht übernehmen."
                state = self.read_settings()
            self.updated.emit(state.reading)
        except DEVICE_ERRORS as exc:
            logging.warning("Einstellungen lesen: %s", exc)
            self.settings_ready.emit(None, DISCONNECTED if self.mouse is None else
                                     "Die Einstellungen sind gerade nicht erreichbar.")
            return

        reading = state.reading
        profile, cycle = state.scroll_profile, state.scroll_cycle
        lights, scroll = state.lights, state.scroll
        actual = {"dpi": reading.dpi, "stage": reading.stage, "polling": reading.polling,
                  "threshold": state.threshold, "idle": state.idle,
                  "sensitivity": reading.sensitivity, "indicators": state.indicators,
                  "smart_reel_level": (state.wired, profile, state.smart_reel_level)}
        if changes and not error:
            changed_values = ((actual[key], value) for key, value in changes.items()
                              if key not in ("lights", "scroll", "scroll_cycle"))
            changed_lights = ((getattr(lights.get(name), key, None), value)
                              for name, edits in changes.get("lights", {}).items() for key, value in edits.items())
            changed_scroll = ((scroll.get(key), value) for key, value in changes.get("scroll", {}).items())
            if "scroll_cycle" in changes:
                requested_profile, requested_cycle = changes["scroll_cycle"]
                changed_scroll = (*changed_scroll, ((profile, cycle), (requested_profile, requested_cycle)))
                if not cycle_has_free_spin(requested_cycle):
                    changed_scroll = (*changed_scroll, *((scroll[key], False) for key in SCROLL_ASSISTS if key in scroll))
            if any(current != requested for current, requested in
                   (*changed_values, *changed_lights, *changed_scroll)):
                error = "Einige Werte wurden von der Maus anders zurückgemeldet. Die aktuellen Werte sind unten eingetragen."
        self.settings_ready.emit(state, error)


def tray_icon(reading):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#132229"))
    painter.drawRoundedRect(QRectF(5, 4, 54, 56), 13, 13)
    painter.setBrush(QColor("#455b62"))
    painter.drawRoundedRect(QRectF(14, 46, 36, 6), 3, 3)
    stage = "–"
    if reading is not None:
        if 1 <= reading.stage <= len(reading.dpi):
            stage = str(reading.stage)
        if reading.battery:
            color = "#ff8d7d" if reading.battery <= 20 else "#76e2b4"
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(14, 46, max(3, 36 * reading.battery / 100), 6), 3, 3)
        if stage == "–":
            stage = "•"
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(29)
    painter.setFont(font)
    painter.setPen(QColor("#f2fbfa"))
    painter.drawText(QRectF(5, 5, 54, 39), Qt.AlignmentFlag.AlignCenter, stage)
    painter.end()
    return QIcon(pixmap)


class LightControls(QGroupBox):
    def __init__(self, title):
        super().__init__(title)
        self.original = None
        self.color = (0, 255, 0)
        self.color_confirmed = False
        self.effect = QComboBox()
        self.brightness = QSpinBox()
        self.brightness.setRange(0, 100)
        self.brightness.setSuffix(" %")
        self.color_button = QPushButton()
        self.color_button.setAccessibleName(f"Farbe · {title}")
        self.color_button.clicked.connect(self.pick_color)
        self.direction = QComboBox()
        self.direction.setAccessibleName(f"Wellenrichtung · {title}")
        self.direction.addItem("Nach rechts", 1)
        self.direction.addItem("Nach links", 2)
        options = QHBoxLayout()
        options.addWidget(self.effect, 1)
        options.addWidget(self.color_button)
        options.addWidget(self.direction)
        form = QFormLayout(self)
        form.addRow("Effekt", options)
        form.addRow("Helligkeit", self.brightness)
        self.effect.currentIndexChanged.connect(self.update_effect_controls)
        self.update_effect_controls()

    def update_effect_controls(self):
        effect = self.effect.currentData()
        self.color_button.setVisible(effect == "static")
        self.direction.setVisible(effect == "wave")

    def show_color(self):
        color = QColor(*self.color)
        swatch = QPixmap(14, 14)
        swatch.fill(color)
        self.color_button.setIcon(QIcon(swatch))
        self.color_button.setText(color.name().upper())

    def pick_color(self):
        selected = QColorDialog.getColor(QColor(*self.color), self, f"Farbe · {self.title()}")
        if selected.isValid():
            self.color = selected.red(), selected.green(), selected.blue()
            self.color_confirmed = True
            self.show_color()

    def load(self, light):
        self.original = light
        self.color_confirmed = False
        self.setVisible(light is not None)
        if light is None:
            self.effect.clear()
            return
        self.effect.clear()
        for effect in light.effects:
            self.effect.addItem(LIGHT_EFFECTS[effect], effect)
        if light.effect is not None and light.effect not in light.effects:
            self.effect.addItem(f"Aktuell ({light.effect})", light.effect)
        self.effect.setCurrentIndex(self.effect.findData(light.effect))
        self.layout().setRowVisible(0, light.effect is not None)
        self.layout().setRowVisible(self.brightness, light.brightness is not None)
        if light.brightness is not None:
            self.brightness.setValue(light.brightness)
        self.color = light.color
        self.show_color()
        self.direction.setCurrentIndex(1 if light.direction == 2 else 0)
        self.update_effect_controls()

    def changes(self):
        original = self.original
        if original is None:
            return {}
        effect = self.effect.currentData()
        changes = {}
        if original.effect is not None and effect != original.effect:
            changes["effect"] = effect
        if original.brightness is not None and self.brightness.value() != original.brightness:
            changes["brightness"] = self.brightness.value()
        if effect == "static" and (self.color_confirmed or self.color != original.color):
            changes["color"] = self.color
        if effect == "wave" and self.direction.currentData() != original.direction:
            changes["direction"] = self.direction.currentData()
        return changes


class ScrollModeComboBox(QComboBox):
    def wheelEvent(self, event):
        # Turning the wheel to test a mode must leave the selected setting intact.
        event.ignore()


class SettingsDialog(QDialog):
    requested = Signal(object)
    selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NAME} · Einstellungen")
        self.setMinimumWidth(390)
        self.current = None
        self.active_edited = False
        self.busy = False
        self.selection = None
        layout = QVBoxLayout(self)
        device_form = QFormLayout()
        self.devices = QComboBox()
        self.devices.activated.connect(lambda index: self.selected.emit(self.devices.itemData(index)))
        device_form.addRow("Gerät", self.devices)
        layout.addLayout(device_form)
        self.status = QLabel(DISCONNECTED)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        general_page = QWidget()
        general = QVBoxLayout(general_page)
        self.tabs.addTab(general_page, "Sensor und Akku")

        self.sensor = QGroupBox("Sensor")
        form = QFormLayout(self.sensor)
        self.count = QSpinBox()
        self.count.setRange(1, len(DEFAULT_STAGES))
        self.active = QComboBox()
        self.active.activated.connect(self.active_changed)
        self.polling = QComboBox()
        form.addRow("Anzahl DPI-Stufen", self.count)
        form.addRow("Aktive Stufe", self.active)
        form.addRow("Pollingrate", self.polling)
        self.dpi_presets = QComboBox()
        form.addRow("DPI", self.dpi_presets)
        direct = QHBoxLayout()
        self.direct_dpi = QSpinBox(), QSpinBox()
        for axis, spin in zip(("X", "Y"), self.direct_dpi):
            spin.setAccessibleName(f"DPI {axis}")
            spin.setPrefix(f"{axis} ")
            spin.setKeyboardTracking(False)
            direct.addWidget(spin)
        self.direct_row = QWidget()
        direct.setContentsMargins(0, 0, 0, 0)
        self.direct_row.setLayout(direct)
        form.addRow("Empfindlichkeit", self.direct_row)
        self.dpi_grid = grid = QGridLayout()
        grid.addWidget(QLabel("Stufe"), 0, 0)
        grid.addWidget(QLabel("DPI X"), 0, 1)
        grid.addWidget(QLabel("DPI Y"), 0, 2)
        self.dpi = []
        for index, default in enumerate(DEFAULT_STAGES, 1):
            row = QLabel(str(index)), QSpinBox(), QSpinBox()
            for column, widget in enumerate(row):
                grid.addWidget(widget, index, column)
            for spin in row[1:]:
                spin.setRange(100, 50_000)
                spin.setValue(default)
                spin.setSingleStep(100)
                spin.setKeyboardTracking(False)
            self.dpi.append(row)
        form.addRow(grid)
        self.count.valueChanged.connect(self.update_rows)
        general.addWidget(self.sensor)

        self.power = QGroupBox("Akku")
        form = QFormLayout(self.power)
        self.threshold = QComboBox()
        self.idle = QSpinBox()
        self.idle.setRange(60, 900)
        self.idle.setSuffix(" s")
        self.idle.setSingleStep(30)
        form.addRow("Warnschwelle", self.threshold)
        form.addRow("Ruhezustand nach", self.idle)
        general.addWidget(self.power)
        general.addStretch()

        self.lighting_page = QWidget()
        lighting = QVBoxLayout(self.lighting_page)
        self.lights = {name: LightControls(label) for name, (label, _) in LIGHT_ZONES.items()}
        for controls in self.lights.values():
            lighting.addWidget(controls)
        lighting.addStretch()
        self.tabs.addTab(self.lighting_page, "Beleuchtung")

        self.scroll_page = QWidget()
        scroll = QFormLayout(self.scroll_page)
        self.scroll_mode = ScrollModeComboBox()
        scroll.addRow("Scrollradmodus", self.scroll_mode)
        self.scroll_cycle = ScrollModeComboBox()
        self.scroll_cycle.setToolTip("Legt fest, welche Modi die bereits belegte Taste durchläuft.")
        self.scroll_cycle_note = QLabel()
        self.scroll_cycle_note.setWordWrap(True)
        self.scroll_acceleration = QCheckBox("Scrollbeschleunigung aktivieren")
        self.scroll_acceleration.setToolTip("Wirkt, wenn sich das Rad im Freilauf befindet.")
        self.scroll_smart_reel = QCheckBox("Smart Reel aktivieren")
        self.scroll_smart_reel.setToolTip("Wechselt bei schnellem Scrollen automatisch in den Freilauf.")
        self.scroll_smart_reel_level = ScrollModeComboBox()
        self.scroll_smart_reel_level.setToolTip("Legt fest, wie empfindlich Smart Reel auf schnelles Drehen reagiert.")
        self.scroll_assists_note = QLabel(
            "Smart Reel und Scrollbeschleunigung sind bei Kombinationen mit Freilauf verfügbar."
        )
        self.scroll_assists_note.setWordWrap(True)
        self.scroll_unavailable = QLabel("OpenRazer meldet keine Scrollrad-Einstellungen für diese Maus.")
        self.scroll_unavailable.setWordWrap(True)
        scroll.addRow(SCROLL_CYCLE_LABEL, self.scroll_cycle)
        scroll.addRow(self.scroll_cycle_note)
        scroll.addRow(self.scroll_acceleration)
        scroll.addRow(self.scroll_smart_reel)
        scroll.addRow("Smart-Reel-Empfindlichkeit", self.scroll_smart_reel_level)
        scroll.addRow(self.scroll_assists_note)
        scroll.addRow(self.scroll_unavailable)
        self.scroll_unavailable.hide()
        self.scroll_cycle.currentIndexChanged.connect(self.update_scroll_assists)
        self.tabs.addTab(self.scroll_page, "Scrollrad")

        self.receiver_page = QWidget()
        receiver = QFormLayout(self.receiver_page)
        self.indicators = [QComboBox() for _ in range(3)]
        for index, combo in enumerate(self.indicators, 1):
            receiver.addRow(f"LED {index}", combo)
        self.receiver_note = QLabel()
        self.receiver_note.setWordWrap(True)
        receiver.addRow(self.receiver_note)
        self.tabs.addTab(self.receiver_page, "Dongle")
        for page in (self.lighting_page, self.scroll_page, self.receiver_page):
            self.show_tab(page, False)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Übernehmen")
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        self.apply_button.clicked.connect(self.submit)
        self.buttons.rejected.connect(self.close)
        layout.addWidget(self.buttons)
        self.set_controls(False)

    def set_controls(self, enabled):
        self.sensor.setEnabled(enabled)
        self.power.setEnabled(enabled)
        self.lighting_page.setEnabled(enabled)
        self.scroll_page.setEnabled(enabled)
        self.receiver_page.setEnabled(enabled)
        self.devices.setEnabled(not self.busy and self.devices.count() > 1)
        self.apply_button.setEnabled(enabled)

    def show_tab(self, page, visible):
        self.tabs.setTabVisible(self.tabs.indexOf(page), visible)

    def set_devices(self, choices, selection):
        changed = selection != self.selection
        self.selection = selection
        self.devices.clear()
        index = -1
        for choice in choices:
            label = choice.name
            if sum(item.name == label for item in choices) > 1:
                label = f"{label} · {choice.serial[-4:]}"
            self.devices.addItem(label, choice)
            if choice == selection:
                index = self.devices.count() - 1
        self.devices.setCurrentIndex(index)
        if changed:
            self.current = None
            self.set_controls(False)
        else:
            self.devices.setEnabled(not self.busy and len(choices) > 1)
        return changed

    def active_changed(self):
        self.active_edited = True

    def update_rows(self):
        count = self.count.value()
        active = min(self.active.currentData() or 1, count)
        self.active.clear()
        for index, row in enumerate(self.dpi, 1):
            for widget in row:
                widget.setEnabled(index <= count)
            if index <= count:
                self.active.addItem(str(index), index)
        self.active.setCurrentIndex(active - 1)

    @Slot(object, str)
    def load(self, state, error):
        self.busy = False
        self.current = state
        self.message.setText(error)
        self.message.setVisible(bool(error))
        self.set_controls(state is not None)
        if state is None:
            return
        reading = state.reading
        stages = bool(reading.dpi and len(reading.dpi) <= len(self.dpi) and state.max_dpi)
        direct = reading.sensitivity is not None and bool(state.max_dpi)
        polling = reading.polling is not None and bool(state.rates)
        form = self.sensor.layout()
        for widget in (self.count, self.active, self.dpi_grid):
            form.setRowVisible(widget, stages)
        form.setRowVisible(self.dpi_presets, direct and bool(state.dpi_presets))
        form.setRowVisible(self.direct_row, direct and not state.dpi_presets)
        form.setRowVisible(self.polling, polling)
        self.sensor.setVisible(stages or direct or polling)
        if direct:
            self.dpi_presets.clear()
            for value in sorted(set(state.dpi_presets) | {reading.sensitivity[0]}):
                self.dpi_presets.addItem(f"{value} DPI", value)
            self.dpi_presets.setCurrentIndex(self.dpi_presets.findData(reading.sensitivity[0]))
            for spin, value in zip(self.direct_dpi, reading.sensitivity):
                spin.setRange(0, state.max_dpi)
                spin.setValue(value)
        if stages:
            for index, (_, x, y) in enumerate(self.dpi):
                values = reading.dpi[index] if index < len(reading.dpi) else (DEFAULT_STAGES[index],) * 2
                for spin, value in zip((x, y), values):
                    if index >= len(reading.dpi):
                        value = min(value, state.max_dpi)
                    spin.setRange(min(100, value), max(state.max_dpi, value))
                    spin.setValue(value)
            self.count.setValue(len(reading.dpi))
            self.update_rows()
            self.active.setCurrentIndex(max(0, min(reading.stage, self.active.count()) - 1))
        self.active_edited = False

        self.polling.clear()
        if polling:
            for rate in sorted(set(state.rates) | {reading.polling}):
                self.polling.addItem(f"{rate} Hz", rate)
            self.polling.setCurrentIndex(self.polling.findData(reading.polling))
        self.threshold.clear()
        # OpenRazer clamps new values to 5–25%. Preserve any existing firmware value.
        if state.threshold is not None:
            for threshold in sorted(set(range(5, 26)) | {state.threshold}):
                suffix = " (aktuell)" if not 5 <= threshold <= 25 else ""
                self.threshold.addItem(f"{threshold} %{suffix}", threshold)
            self.threshold.setCurrentIndex(self.threshold.findData(state.threshold))
        if state.idle is not None:
            self.idle.setRange(min(60, state.idle), max(900, state.idle))
            self.idle.setValue(state.idle)
        self.power.layout().setRowVisible(self.threshold, state.threshold is not None)
        self.power.layout().setRowVisible(self.idle, state.idle is not None)
        self.power.setVisible(state.threshold is not None or state.idle is not None)
        for name, controls in self.lights.items():
            controls.load(state.lights.get(name))
        self.show_tab(self.lighting_page, bool(state.lights))
        self.show_tab(self.scroll_page, bool(state.scroll))
        self.show_tab(self.receiver_page, bool(state.indicators or state.receiver_error))
        modes = state.indicators or ()
        for index, combo in enumerate(self.indicators):
            self.receiver_page.layout().setRowVisible(combo, index < len(modes))
            combo.clear()
            if index < len(modes):
                for value, label in enumerate(LED_MODES[len(modes)]):
                    combo.addItem(label, value)
                if combo.findData(modes[index]) < 0:
                    combo.addItem(f"Aktuell ({modes[index]})", modes[index])
                combo.setCurrentIndex(combo.findData(modes[index]))
        self.receiver_note.setText(state.receiver_error)
        self.receiver_note.setVisible(bool(state.receiver_error))
        self.show_tab(self.tabs.widget(0), stages or direct or polling or
                      state.threshold is not None or state.idle is not None or
                      not (state.lights or state.scroll or state.indicators or state.receiver_error))
        self.load_scroll(state)

    def load_scroll(self, state):
        form = self.scroll_page.layout()
        form.setRowVisible(self.scroll_cycle, state.basilisk)
        self.scroll_mode.clear()
        if not state.basilisk and "scroll_mode" in state.scroll:
            choices = {0: "Rastend", 1: "Freilauf"}
            if state.scroll["scroll_mode"] not in choices:
                choices[state.scroll["scroll_mode"]] = "Aktueller Modus"
            for value, label in choices.items():
                self.scroll_mode.addItem(label, value)
            self.scroll_mode.setCurrentIndex(self.scroll_mode.findData(state.scroll["scroll_mode"]))
        form.setRowVisible(self.scroll_mode, self.scroll_mode.count() > 0)
        self.scroll_acceleration.setChecked(state.scroll.get("scroll_acceleration", False))
        self.scroll_smart_reel.setChecked(state.scroll.get("scroll_smart_reel", False))
        level = self.scroll_smart_reel_level
        level.setEnabled(state.smart_reel_level is not None)
        level.clear()
        if state.smart_reel_level is None:
            level.addItem("Nicht verfügbar", None)
        else:
            for value in SMART_REEL_LEVELS:
                level.addItem(f"Stufe {value + 1}", value)
            level.setCurrentIndex(level.findData(state.smart_reel_level))
        self.load_scroll_cycle(state)
        self.update_scroll_assists()
        self.scroll_unavailable.setVisible(not state.scroll)

    def load_scroll_cycle(self, state):
        self.scroll_cycle.clear()
        self.scroll_cycle.addItem("Modi auswählen …", None)
        for cycle, label in SCROLL_CYCLES.items():
            self.scroll_cycle.addItem(label, cycle)
        self.scroll_cycle.setCurrentIndex(max(0, self.scroll_cycle.findData(state.scroll_cycle)))
        self.scroll_cycle.setEnabled(state.scroll_profile is not None)
        if state.scroll_profile is None:
            note = "Die Modiauswahl benötigt Zugriff auf die USB-Steuerschnittstelle."
        elif state.scroll_cycle_cached:
            note = "Zuletzt im Tray für das aktive Mausprofil gespeichert."
        elif state.scroll_cycle is None:
            note = "Die Maus meldet die aktuelle Auswahl nicht zurück."
        else:
            note = ""
        self.scroll_cycle_note.setText(note)
        self.scroll_cycle_note.setVisible(state.basilisk and bool(note))

    def update_scroll_assists(self):
        if self.current is None:
            return
        scroll = self.current.scroll
        has_free_spin = not self.current.basilisk or cycle_has_free_spin(self.scroll_cycle.currentData())
        show_smart_reel = has_free_spin and "scroll_smart_reel" in scroll
        self.scroll_smart_reel.setVisible(show_smart_reel)
        self.scroll_acceleration.setVisible(has_free_spin and "scroll_acceleration" in scroll)
        self.scroll_page.layout().setRowVisible(self.scroll_smart_reel_level, self.current.basilisk and show_smart_reel)
        self.scroll_assists_note.setVisible(not has_free_spin and any(key in scroll for key in SCROLL_ASSISTS))

    def request(self, changes=None):
        self.busy = True
        self.set_controls(False)
        self.message.setText("Übernehme Einstellungen …" if changes else "Lese Einstellungen …")
        self.message.show()
        self.requested.emit((self.selection, changes))

    def submit(self):
        if self.busy or self.current is None:
            return
        state = self.current
        dpi = tuple((x.value(), y.value()) for _, x, y in self.dpi[:self.count.value()])
        changes = {}
        if state.reading.dpi and len(state.reading.dpi) <= len(self.dpi) and state.max_dpi and dpi != state.reading.dpi:
            changes["dpi"] = dpi
        if self.active_edited:
            changes["stage"] = self.active.currentData()
        for key, value, original in (
            ("polling", self.polling.currentData(), state.reading.polling),
            ("threshold", self.threshold.currentData(), state.threshold),
            ("idle", self.idle.value(), state.idle),
        ):
            if value is not None and original is not None and value != original:
                changes[key] = value
        if state.reading.sensitivity is not None and state.max_dpi:
            value = ((self.dpi_presets.currentData(), 0) if state.dpi_presets else
                     tuple(spin.value() for spin in self.direct_dpi))
            if value != state.reading.sensitivity:
                changes["sensitivity"] = value
        light_edits = {name: edits for name, controls in self.lights.items() if (edits := controls.changes())}
        if light_edits:
            changes["lights"] = light_edits
        cycle = self.scroll_cycle.currentData()
        if state.scroll_profile is not None and cycle is not None and cycle != state.scroll_cycle:
            changes["scroll_cycle"] = state.scroll_profile, cycle
        if not state.basilisk or cycle_has_free_spin(cycle):
            scroll_edits = {
                key: value for key, value in (
                    ("scroll_acceleration", self.scroll_acceleration.isChecked()),
                    ("scroll_smart_reel", self.scroll_smart_reel.isChecked()),
                ) if key in state.scroll and value != state.scroll[key]
            }
            if scroll_edits:
                changes["scroll"] = scroll_edits
            level = self.scroll_smart_reel_level.currentData()
            if state.scroll_profile is not None and level is not None and level != state.smart_reel_level:
                changes["smart_reel_level"] = state.wired, state.scroll_profile, level
        if self.scroll_mode.currentData() is not None and self.scroll_mode.currentData() != state.scroll.get("scroll_mode"):
            changes.setdefault("scroll", {})["scroll_mode"] = self.scroll_mode.currentData()
        if state.indicators:
            modes = tuple(combo.currentData() for combo in self.indicators[:len(state.indicators)])
            if modes != state.indicators:
                changes["indicators"] = modes
        if not changes and self.tabs.currentIndex() == 0 and self.polling.currentData() is not None:
            changes["polling"] = self.polling.currentData()
        if changes:
            self.request(changes)


class Tray(QObject):
    selected = Signal(object)

    def __init__(self, application):
        super().__init__()
        self.dialog = SettingsDialog()
        self.menu = QMenu()
        self.device_row = self.menu.addAction(NAME)
        self.device_row.setEnabled(False)
        self.rows = [self.menu.addAction("") for _ in range(3)]
        for action in self.rows:
            action.setEnabled(False)
        self.menu.addSeparator()
        self.device_menu = self.menu.addMenu("Gerät auswählen")
        self.device_menu.menuAction().setVisible(False)
        self.menu.addAction("Einstellungen …", self.open_settings)
        self.menu.addAction("Beenden", application.quit)
        self.tray = QSystemTrayIcon(tray_icon(None), self)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activate)
        self.last_reading = None
        self.show_reading(None)
        self.tray.show()

        self.thread = QThread(self)
        self.worker = MouseWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.thread.finished.connect(self.worker.deleteLater)
        self.worker.updated.connect(self.show_reading)
        self.worker.devices_changed.connect(self.show_devices)
        self.worker.settings_ready.connect(self.dialog.load)
        self.dialog.requested.connect(self.worker.settings)
        self.dialog.selected.connect(self.worker.select)
        self.selected.connect(self.worker.select)
        application.aboutToQuit.connect(self.stop)
        self.thread.start()

    @Slot(object, object)
    def show_devices(self, choices, selection):
        changed = self.dialog.set_devices(choices, selection)
        self.device_row.setText(selection.name if selection else NAME)
        self.device_menu.clear()
        for choice in choices:
            label = choice.name
            if sum(item.name == label for item in choices) > 1:
                label = f"{label} · {choice.serial[-4:]}"
            action = self.device_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(choice == selection)
            action.triggered.connect(lambda checked, target=choice: self.selected.emit(target))
        self.device_menu.menuAction().setVisible(len(choices) > 1)
        if changed and selection and self.dialog.isVisible() and not self.dialog.busy:
            self.dialog.request()

    @Slot(object)
    def show_reading(self, reading):
        previous = self.last_reading
        self.last_reading = reading
        labels = reading.labels() if reading else (DISCONNECTED,)
        self.tray.setToolTip(self.device_row.text() + "\n" + "\n".join(labels))
        if reading != previous or reading is None:
            if reading != previous:
                self.tray.setIcon(tray_icon(reading))
            for index, action in enumerate(self.rows):
                action.setVisible(index < len(labels))
                if index < len(labels):
                    action.setText(labels[index])
            self.dialog.status.setText("   |   ".join(labels))
        if reading is None:
            self.dialog.current = None
            self.dialog.set_controls(False)
        elif self.dialog.current is None and self.dialog.isVisible() and not self.dialog.busy and previous is None:
            self.dialog.request()

    def open_settings(self):
        if not self.dialog.isVisible() and not self.dialog.busy:
            self.dialog.request()
        self.dialog.showNormal()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    def stop(self):
        self.tray.hide()
        self.thread.quit()
        self.thread.wait()


class TrayLauncher(QDBusAbstractAdaptor):
    @Slot()
    def OpenSettings(self):
        self.parent().open_settings()


if ClassInfo is not None:
    TrayLauncher = ClassInfo(**{"D-Bus Interface": DESKTOP_ID})(TrayLauncher)
else:
    TrayLauncher = pyqtClassInfo("D-Bus Interface", DESKTOP_ID)(TrayLauncher)


def main():
    open_settings = "--settings" in sys.argv
    application = QApplication([sys.argv[0]])
    application.setApplicationName(NAME)
    application.setDesktopFileName(DESKTOP_ID)
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(QIcon.fromTheme("input-mouse"))

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        logging.error("Die KDE-D-Bus-Sitzung ist nicht erreichbar.")
        return 1
    if not bus.registerService(DESKTOP_ID):
        if open_settings:
            request = QDBusMessage.createMethodCall(DESKTOP_ID, BUS_PATH, DESKTOP_ID, "OpenSettings")
            reply = bus.call(request, QDBus.CallMode.Block, 2000)
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                logging.error("Einstellungsfenster öffnen: %s", reply.errorMessage())
                return 1
        return 0
    tray = Tray(application)
    launcher = TrayLauncher(tray)
    if not bus.registerObject(BUS_PATH, tray):
        tray.stop()
        return 1
    if open_settings:
        launcher.OpenSettings()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
