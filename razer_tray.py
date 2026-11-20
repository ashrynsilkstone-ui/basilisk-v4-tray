from dataclasses import dataclass
from fcntl import ioctl
import logging
from pathlib import Path
import struct
import sys
from time import monotonic, sleep

from dbus import DBusException
from openrazer.client import DaemonNotFound, DeviceManager

try:
    from PySide6.QtCore import ClassInfo, QObject, QRectF, Qt, QThread, QTimer, Signal, Slot
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
    from PyQt6.QtCore import QObject, QRectF, Qt, QThread, QTimer
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


NAME = "Basilisk V4 Pro"
DESKTOP_ID = "local.razer.BasiliskTray"
BUS_PATH = "/BasiliskTray"
DEVICE_ERRORS = (DBusException, DaemonNotFound, OSError, ValueError)
DISCONNECTED = "Warte auf den HyperSpeed-Dongle …"
DEFAULT_STAGES = (1200, 1600, 2400, 3200, 6400)
LIGHT_ZONES = {"logo": "Logo", "scroll_wheel": "Scrollrad", "backlight": "Unterboden"}
LIGHT_EFFECTS = {"none": "Aus", "static": "Statisch", "spectrum": "Farbwechsel", "wave": "Welle"}
SCROLL_MODES = {0: "Rastend (24 Rastpunkte)", 2: "Rastend (48 Rastpunkte)", 1: "Freilauf"}
SCROLL_SETTINGS = ("scroll_mode", "scroll_acceleration", "scroll_smart_reel")


class ScrollModeError(OSError):
    pass


def scroll_feature_report(device, command_class, command, arguments, expected_prefix=b""):
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
        sleep(0.05)
        reply = bytearray(91)
        length = ioctl(device, 0xC05B4807, reply)  # HIDIOCGFEATURE(91)
        # The driver can also be querying the receiver. Ignore unrelated replies.
        if length != len(reply) or reply[2] != report[2] or reply[7:9] != report[7:9]:
            continue
        if reply[1] != 0x02 or reply[6] != len(arguments):
            continue
        payload = bytes(reply[9:9 + reply[6]])
        if payload.startswith(expected_prefix):
            return payload
    raise OSError(f"Keine passende Antwort auf den HID-Befehl {command_class:02x}:{command:02x}.")


def enable_scroll_modes(serial):
    # USB interface 3 is the control endpoint on this HyperSpeed receiver.
    nodes = []
    for hid in Path("/sys/bus/usb/devices").glob("*:1.3/0003:1532:00E3.*"):
        if f"HID_UNIQ={serial}" in (hid / "uevent").read_text().splitlines():
            nodes.extend(hid.glob("hidraw/hidraw*"))
    if len(nodes) != 1:
        raise OSError("Der HID-Steueranschluss des Dongles konnte nicht eindeutig zugeordnet werden.")

    with open(Path("/dev") / nodes[0].name, "r+b", buffering=0) as device:
        info = bytearray(8)
        ioctl(device, 0x80084803, info)  # HIDIOCGRAWINFO
        if struct.unpack("=IHH", info) != (0x0003, 0x1532, 0x00E3):
            raise OSError("Der HID-Steueranschluss gehört nicht zur Basilisk V4 Pro.")
        profile, = scroll_feature_report(device, 0x05, 0x84, b"\x00")
        if not 1 <= profile <= 5:
            raise OSError(f"Die Maus meldet ein ungültiges aktives Profil ({profile}).")

        # Read both masks before changing either. Preserve bits outside the three wheel modes.
        masks = {}
        for bank in (0, profile):
            prefix = bytes((bank,))
            _, mask = scroll_feature_report(device, 0x15, 0x8B, prefix + b"\x00", prefix)
            masks[bank] = mask
        for bank, mask in masks.items():
            arguments = bytes((bank, mask | 0b111))
            scroll_feature_report(device, 0x15, 0x0B, arguments, arguments)


@dataclass(frozen=True)
class Reading:
    battery: int
    charging: bool
    stage: int
    dpi: tuple[tuple[int, int], ...]
    polling: int

    def labels(self):
        battery = f"Akku {self.battery} %" + (" · lädt" if self.charging else "")
        dpi = "DPI-Stufe unbekannt"
        if 1 <= self.stage <= len(self.dpi):
            x, y = self.dpi[self.stage - 1]
            value = str(x) if x == y else f"{x} × {y}"
            dpi = f"DPI-Stufe {self.stage}/{len(self.dpi)} · {value} DPI"
        return battery, dpi, f"Polling {self.polling} Hz"


@dataclass(frozen=True)
class Settings:
    reading: Reading
    max_dpi: int
    rates: tuple[int, ...]
    threshold: int
    idle: int
    lights: dict[str, "Light"]
    scroll: dict[str, int | bool]


@dataclass(frozen=True)
class Light:
    effect: str
    brightness: int
    color: tuple[int, int, int]
    direction: int

    @classmethod
    def read(cls, zone):
        red, green, blue = zone.colors[:3]
        return cls(zone.effect, round(zone.brightness), (red, green, blue), zone.wave_dir)


class MouseWorker(QObject):
    updated = Signal(object)
    settings_ready = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.mouse = None
        self.battery = (0, False)
        self.next_battery_check = None

    def read(self, refresh_battery=False):
        if self.mouse is None:
            self.mouse = next(
                (device for device in DeviceManager().devices
                 if (device._vid, device._pid) == (0x1532, 0x00E3)),
                None,
            )
        if self.mouse is None:
            raise DaemonNotFound(DISCONNECTED)
        stage, dpi = self.mouse.dpi_stages
        polling = self.mouse.poll_rate
        now = monotonic()
        if refresh_battery or self.next_battery_check is None or now >= self.next_battery_check:
            self.battery = self.mouse.battery_level, self.mouse.is_charging
            self.next_battery_check = now + 10
        return Reading(*self.battery, stage, tuple(dpi), polling)

    def mark_disconnected(self):
        self.mouse = None
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
            self.updated.emit(self.read())
        except DEVICE_ERRORS:
            self.mark_disconnected()

    def set_scroll_mode(self, mode):
        self.mouse.scroll_mode = mode
        sleep(0.5)
        if self.mouse.scroll_mode == mode:
            return
        repair_error = None
        try:
            enable_scroll_modes(self.mouse.serial)
        except OSError as exc:
            repair_error = exc
        self.mouse.scroll_mode = mode
        sleep(0.5)
        if self.mouse.scroll_mode == mode:
            return
        if isinstance(repair_error, PermissionError):
            raise ScrollModeError(
                "Der Tray hat keinen HID-Zugriff auf den Dongle. "
                "Stecke den Dongle neu ein oder melde dich erneut an."
            ) from repair_error
        if repair_error is not None:
            raise ScrollModeError(
                f"Scrollradmodi konnten nicht freigegeben werden. {repair_error}"
            ) from repair_error
        raise ScrollModeError("Die Maus hat den gewählten Scrollradmodus erneut zurückgewiesen.")

    def apply(self, current, changes):
        mouse = self.mouse
        dpi = changes.get("dpi", current.dpi)
        stage = changes.get("stage", min(max(current.stage, 1), len(dpi)))
        if ("dpi" in changes or "stage" in changes) and (stage, dpi) != (current.stage, current.dpi):
            mouse.dpi_stages = stage, list(dpi)
            actual_stage, actual_dpi = mouse.dpi_stages
            if (actual_stage, tuple(actual_dpi)) != (stage, dpi):
                raise ValueError("Die Maus hat die DPI-Stufen anders zurückgemeldet.")
            mouse.dpi = dpi[stage - 1]
        if "polling" in changes:
            mouse.poll_rate = changes["polling"]
        if "threshold" in changes and changes["threshold"] != mouse.get_low_battery_threshold():
            mouse.set_low_battery_threshold(changes["threshold"])
        if "idle" in changes and changes["idle"] != mouse.get_idle_time():
            mouse.set_idle_time(changes["idle"])
        scroll = changes.get("scroll", {})
        for key in SCROLL_SETTINGS:
            if key in scroll and not mouse.has(key):
                raise ValueError(f"Scrollradeinstellung {key} ist nicht verfügbar.")
        if scroll.get("scroll_smart_reel") is False:
            mouse.scroll_smart_reel = False
        if "scroll_mode" in scroll:
            self.set_scroll_mode(scroll["scroll_mode"])
        if "scroll_acceleration" in scroll:
            mouse.scroll_acceleration = scroll["scroll_acceleration"]
        if scroll.get("scroll_smart_reel") is True:
            mouse.scroll_smart_reel = True
        for name, edits in changes.get("lights", {}).items():
            zone = getattr(mouse.fx.misc, name)
            if zone is None:
                raise ValueError(f"Beleuchtungszone {LIGHT_ZONES[name]} ist nicht verfügbar.")
            light = Light.read(zone)
            effect = edits.get("effect", light.effect)
            if "brightness" in edits:
                zone.brightness = edits["brightness"]
            if effect == "static" and ("effect" in edits or "color" in edits):
                zone.static(*edits.get("color", light.color))
            elif effect == "wave" and ("effect" in edits or "direction" in edits):
                zone.wave(edits.get("direction", light.direction))
            elif effect == "spectrum" and "effect" in edits:
                zone.spectrum()
            elif effect == "none" and "effect" in edits:
                zone.none()

    @Slot(object)
    def settings(self, changes):
        error = ""
        if changes:
            try:
                self.apply(self.read(), changes)
            except ScrollModeError as exc:
                logging.warning("Scrollradmodus übernehmen: %s", exc)
                error = str(exc)
            except DEVICE_ERRORS as exc:
                logging.warning("Einstellungen übernehmen: %s", exc)
                error = "Die Maus konnte die Einstellungen nur teilweise oder gar nicht übernehmen."

        try:
            reading = self.read(refresh_battery=True)
            lights = {}
            for name in LIGHT_ZONES:
                zone = getattr(self.mouse.fx.misc, name)
                if zone is not None:
                    lights[name] = Light.read(zone)
            scroll = {key: getattr(self.mouse, key) for key in SCROLL_SETTINGS if self.mouse.has(key)}
            state = Settings(reading, self.mouse.max_dpi, tuple(self.mouse.supported_poll_rates),
                             self.mouse.get_low_battery_threshold(), self.mouse.get_idle_time(), lights, scroll)
            self.updated.emit(reading)
        except DEVICE_ERRORS as exc:
            logging.warning("Einstellungen lesen: %s", exc)
            self.mark_disconnected()
            self.settings_ready.emit(None, "Die Mauseinstellungen sind gerade nicht erreichbar.")
            return

        actual = {"dpi": reading.dpi, "stage": reading.stage, "polling": reading.polling,
                  "threshold": state.threshold, "idle": state.idle}
        if changes and not error:
            changed_values = ((actual[key], value) for key, value in changes.items()
                              if key not in ("lights", "scroll"))
            changed_lights = ((getattr(lights.get(name), key, None), value)
                              for name, edits in changes.get("lights", {}).items() for key, value in edits.items())
            changed_scroll = ((scroll.get(key), value) for key, value in changes.get("scroll", {}).items())
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
        self.setEnabled(light is not None)
        if light is None:
            self.effect.clear()
            return
        self.effect.clear()
        for effect, label in LIGHT_EFFECTS.items():
            self.effect.addItem(label, effect)
        if light.effect not in LIGHT_EFFECTS:
            self.effect.addItem(f"Aktuell ({light.effect})", light.effect)
        self.effect.setCurrentIndex(self.effect.findData(light.effect))
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
        if effect != original.effect:
            changes["effect"] = effect
        if self.brightness.value() != original.brightness:
            changes["brightness"] = self.brightness.value()
        if effect == "static" and (self.color_confirmed or self.color != original.color):
            changes["color"] = self.color
        if effect == "wave" and self.direction.currentData() != original.direction:
            changes["direction"] = self.direction.currentData()
        return changes


class SettingsDialog(QDialog):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{NAME} · Einstellungen")
        self.setMinimumWidth(390)
        self.current = None
        self.active_edited = False
        self.busy = False
        layout = QVBoxLayout(self)
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
        grid = QGridLayout()
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
        self.lights = {name: LightControls(label) for name, label in LIGHT_ZONES.items()}
        for controls in self.lights.values():
            lighting.addWidget(controls)
        lighting.addStretch()
        self.tabs.addTab(self.lighting_page, "Beleuchtung")

        self.scroll_page = QWidget()
        scroll = QFormLayout(self.scroll_page)
        self.scroll_mode = QComboBox()
        self.scroll_acceleration = QCheckBox("Scrollbeschleunigung aktivieren")
        self.scroll_smart_reel = QCheckBox("Smart Reel aktivieren")
        self.scroll_smart_reel.setToolTip("Wechselt bei schnellem Scrollen automatisch in den Freilauf.")
        self.scroll_unavailable = QLabel("OpenRazer meldet keine Scrollrad-Einstellungen für diese Maus.")
        self.scroll_unavailable.setWordWrap(True)
        scroll.addRow("Modus", self.scroll_mode)
        scroll.addRow(self.scroll_acceleration)
        scroll.addRow(self.scroll_smart_reel)
        scroll.addRow(self.scroll_unavailable)
        self.scroll_unavailable.hide()
        self.tabs.addTab(self.scroll_page, "Scrollrad")

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
        self.apply_button.setEnabled(enabled)

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
        for index, (_, x, y) in enumerate(self.dpi):
            values = reading.dpi[index] if index < len(reading.dpi) else (DEFAULT_STAGES[index],) * 2
            for spin, value in zip((x, y), values):
                spin.setMaximum(state.max_dpi)
                spin.setValue(value)
        self.count.setValue(len(reading.dpi))
        self.update_rows()
        self.active.setCurrentIndex(max(0, min(reading.stage, self.active.count()) - 1))
        self.active_edited = False

        self.polling.clear()
        for rate in sorted(set(state.rates) | {reading.polling}):
            self.polling.addItem(f"{rate} Hz", rate)
        self.polling.setCurrentIndex(self.polling.findData(reading.polling))
        self.threshold.clear()
        # OpenRazer clamps new values to 5–25%. Preserve any existing firmware value.
        for threshold in sorted(set(range(5, 26)) | {state.threshold}):
            suffix = " (aktuell)" if not 5 <= threshold <= 25 else ""
            self.threshold.addItem(f"{threshold} %{suffix}", threshold)
        self.threshold.setCurrentIndex(self.threshold.findData(state.threshold))
        self.idle.setValue(state.idle)
        for name, controls in self.lights.items():
            controls.load(state.lights.get(name))
        self.load_scroll(state.scroll)

    def load_scroll(self, scroll):
        form = self.scroll_page.layout()
        mode_available = "scroll_mode" in scroll
        form.labelForField(self.scroll_mode).setVisible(mode_available)
        self.scroll_mode.setVisible(mode_available)
        self.scroll_mode.clear()
        if mode_available:
            mode = scroll["scroll_mode"]
            for value, label in SCROLL_MODES.items():
                self.scroll_mode.addItem(label, value)
            if mode not in SCROLL_MODES:
                self.scroll_mode.addItem(f"Aktuell ({mode})", mode)
            self.scroll_mode.setCurrentIndex(self.scroll_mode.findData(mode))
        self.scroll_acceleration.setVisible("scroll_acceleration" in scroll)
        self.scroll_acceleration.setChecked(scroll.get("scroll_acceleration", False))
        self.scroll_smart_reel.setVisible("scroll_smart_reel" in scroll)
        self.scroll_smart_reel.setChecked(scroll.get("scroll_smart_reel", False))
        self.scroll_unavailable.setVisible(not scroll)

    def request(self, changes=None):
        self.busy = True
        self.set_controls(False)
        self.message.setText("Übernehme Einstellungen …" if changes else "Lese Einstellungen …")
        self.message.show()
        self.requested.emit(changes)

    def submit(self):
        if self.busy or self.current is None:
            return
        state = self.current
        dpi = tuple((x.value(), y.value()) for _, x, y in self.dpi[:self.count.value()])
        changes = {}
        if dpi != state.reading.dpi:
            changes["dpi"] = dpi
        if self.active_edited:
            changes["stage"] = self.active.currentData()
        for key, value, original in (
            ("polling", self.polling.currentData(), state.reading.polling),
            ("threshold", self.threshold.currentData(), state.threshold),
            ("idle", self.idle.value(), state.idle),
        ):
            if value != original:
                changes[key] = value
        light_edits = {name: edits for name, controls in self.lights.items() if (edits := controls.changes())}
        if light_edits:
            changes["lights"] = light_edits
        scroll_edits = {
            key: value for key, value in (
                ("scroll_mode", self.scroll_mode.currentData()),
                ("scroll_acceleration", self.scroll_acceleration.isChecked()),
                ("scroll_smart_reel", self.scroll_smart_reel.isChecked()),
            ) if key in state.scroll and value != state.scroll[key]
        }
        if scroll_edits:
            changes["scroll"] = scroll_edits
        if not changes and self.tabs.currentIndex() == 0:
            changes["polling"] = self.polling.currentData()
        if changes:
            self.request(changes)


class Tray(QObject):
    def __init__(self, application):
        super().__init__()
        self.dialog = SettingsDialog()
        self.menu = QMenu()
        self.rows = [self.menu.addAction("") for _ in range(3)]
        for action in self.rows:
            action.setEnabled(False)
        self.menu.addSeparator()
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
        self.worker.settings_ready.connect(self.dialog.load)
        self.dialog.requested.connect(self.worker.settings)
        application.aboutToQuit.connect(self.stop)
        self.thread.start()

    @Slot(object)
    def show_reading(self, reading):
        previous = self.last_reading
        self.last_reading = reading
        labels = reading.labels() if reading else (DISCONNECTED,)
        if reading != previous or reading is None:
            self.tray.setToolTip(NAME + "\n" + "\n".join(labels))
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
        elif previous is None and self.dialog.isVisible() and not self.dialog.busy:
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
