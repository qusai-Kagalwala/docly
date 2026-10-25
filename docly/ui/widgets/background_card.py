""""Background" card on the Photo page: keep it, or pick a new colour."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QComboBox, QHBoxLayout, QLabel, QSlider, QWidget

from docly.core.background import COLOURS, RGB, BackgroundOptions
from docly.presets.models import Preset
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.style import set_style_prop

KEEP = "keep"
CUSTOM = "custom"
LABELS = {"white": "White", "off_white": "Off-white", "light_blue": "Light blue"}
HINT = "Docly finds you in the photo and fills everything behind you. Works best with a plain wall."
BLOCKED = (
    "This authority doesn't accept edited photos, so the background can't be changed. "
    "Retake the photo against a plain white or off-white wall."
)
MISSING = "The background tool isn't available: its model file is missing. Reinstalling Docly will fix this."
SOFTNESS_TIP = "Low gives crisp edges and tidies flyaway hair. High keeps fine hair strands."


def ask_colour(parent: QWidget, start: RGB) -> RGB | None:
    """Windows colour picker; None if cancelled."""
    colour = QColorDialog.getColor(QColor(*start), parent, "Background colour")
    return (colour.red(), colour.green(), colour.blue()) if colour.isValid() else None


def swatch(rgb: RGB, size: int = 16) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(0, 0, 0, 70))
    painter.setBrush(QColor(*rgb))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class BackgroundCard(Card):
    """Signals:
    changed(): the choice or softness changed (re-process the photo).
    """

    changed = Signal()

    def __init__(self, theme: ThemeManager, available: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.available = available
        self.blocked = False
        self.custom_colour: RGB = (220, 230, 240)

        section = QLabel("Background")
        section.setProperty("role", "section")
        self.body.addWidget(section)

        self.choice = QComboBox()
        self.choice.setAccessibleName("Background")
        self.choice.addItem("Keep original", KEEP)
        for key, label in LABELS.items():
            self.choice.addItem(swatch(COLOURS[key]), label, key)
        self.choice.addItem(swatch(self.custom_colour), "Custom colour…", CUSTOM)
        self.body.addWidget(self.choice)

        self.softness_row = QWidget()
        row = QHBoxLayout(self.softness_row)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Edge softness")
        label.setProperty("role", "body")
        label.setToolTip(SOFTNESS_TIP)
        self.softness = QSlider(Qt.Orientation.Horizontal)
        self.softness.setRange(0, 100)
        self.softness.setValue(BackgroundOptions().softness)
        self.softness.setPageStep(10)
        self.softness.setToolTip(SOFTNESS_TIP)
        self.softness.setAccessibleName("Edge softness")
        row.addWidget(label)
        row.addWidget(self.softness, 1)
        self.body.addWidget(self.softness_row)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.body.addWidget(self.message)

        self.choice.activated.connect(self._on_activated)
        self.softness.valueChanged.connect(lambda _v: self.changed.emit())
        self._update()

    # ----- public -------------------------------------------------------
    def current(self) -> str:
        return self.choice.currentData() or KEEP

    def select(self, value: str) -> None:
        index = self.choice.findData(value)
        if index >= 0 and index != self.choice.currentIndex():
            self.choice.setCurrentIndex(index)
            self._update()
            self.changed.emit()

    def set_custom_colour(self, rgb: RGB) -> None:
        self.custom_colour = rgb
        index = self.choice.findData(CUSTOM)
        self.choice.setItemIcon(index, swatch(rgb))
        self.choice.setItemText(index, f"Custom #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")

    def options(self) -> BackgroundOptions | None:
        """What to do, or None to keep the photo's own background."""
        value = self.current()
        if value == KEEP or self.blocked or not self.available:
            return None
        colour = self.custom_colour if value == CUSTOM else COLOURS[value]
        return BackgroundOptions(colour, self.softness.value())

    def set_preset(self, preset: Preset | None) -> None:
        """Lock the card for presets that forbid edits (the choice is remembered)."""
        blocked = bool(preset is not None and preset.no_edits)
        if blocked != self.blocked:
            self.blocked = blocked
            self._update()

    # ----- internals ------------------------------------------------------
    def _on_activated(self, index: int) -> None:
        if self.choice.itemData(index) == CUSTOM:
            picked = ask_colour(self, self.custom_colour)
            if picked is not None:
                self.set_custom_colour(picked)
        self._update()
        self.changed.emit()

    def _update(self) -> None:
        usable = self.available and not self.blocked
        self.choice.setEnabled(usable)
        self.softness_row.setVisible(usable and self.current() != KEEP)
        if not self.available:
            text, banner = MISSING, "danger"
        elif self.blocked:
            text, banner = BLOCKED, "warning"
        else:
            text, banner = HINT, None
        self.message.setText(text)
        set_style_prop(self.message, "banner", banner)
        set_style_prop(self.message, "role", None if banner else "caption")
