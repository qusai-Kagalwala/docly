"""Card that shows a preset's rules in plain words."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

from docly.presets.models import Category, Preset
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.style import set_style_prop

UNVERIFIED_TEXT = "⚠ Unverified"
UNVERIFIED_TIP = (
    "Docly hasn't confirmed this preset against the latest official notice. "
    "Check the source before uploading."
)


class PresetInfoCard(Card):
    """Size, file size, format, DPI, notes and a verification chip."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.body.setSpacing(8)

        self.title = QLabel("No preset selected")
        self.title.setProperty("role", "section")
        self.title.setWordWrap(True)
        self.body.addWidget(self.title)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.region_chip = QLabel()
        self.region_chip.setProperty("chip", "neutral")
        self.status_chip = QLabel()
        self.status_chip.setProperty("chip", "neutral")
        chips.addWidget(self.region_chip)
        chips.addWidget(self.status_chip)
        chips.addStretch(1)
        self.body.addLayout(chips)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}
        for row, key in enumerate(("Size", "File size", "Format", "DPI")):
            label = QLabel(key)
            label.setProperty("role", "caption")
            value = QLabel("—")
            value.setProperty("role", "body")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        self.notes = QLabel()
        self.notes.setProperty("role", "caption")
        self.notes.setWordWrap(True)
        self.body.addWidget(self.notes)

        self.source = QLabel()
        self.source.setTextFormat(Qt.TextFormat.RichText)
        self.source.setOpenExternalLinks(True)
        self.source.setProperty("role", "caption")
        self.body.addWidget(self.source)

        self.show_preset(None)

    def show_preset(self, preset: Preset | None) -> None:
        if preset is None:
            self.title.setText("No preset selected")
            for value in self.values.values():
                value.setText("—")
            for widget in (self.region_chip, self.status_chip, self.notes, self.source):
                widget.hide()
            return

        self.title.setText(preset.name)
        self.values["Size"].setText(preset.pixel_text or "Any size (photo is kept as it is)")
        self.values["File size"].setText(preset.kb_range_text or "No limit")
        self.values["Format"].setText(" or ".join(f.value.upper() for f in preset.formats))
        self.values["DPI"].setText(str(preset.dpi) if preset.dpi else "Not specified")

        self.region_chip.setText(preset.region_label)
        self.region_chip.show()
        self.status_chip.setToolTip("")
        if preset.category == Category.GENERAL:
            self.status_chip.setText("Docly preset")
            set_style_prop(self.status_chip, "chip", "neutral")
        elif preset.verified:
            verified = f" on {preset.last_verified:%d %b %Y}" if preset.last_verified else ""
            self.status_chip.setText(f"Verified{verified}")
            set_style_prop(self.status_chip, "chip", "success")
        else:
            self.status_chip.setText(UNVERIFIED_TEXT)
            self.status_chip.setToolTip(UNVERIFIED_TIP)
            set_style_prop(self.status_chip, "chip", "warning")
        self.status_chip.show()

        self.notes.setText(preset.notes)
        self.notes.setVisible(bool(preset.notes))
        if preset.source:
            link = escape(preset.source, quote=True)
            prefix = "" if preset.verified else "Check the latest rules: "
            self.source.setText(f'{prefix}<a href="{link}">official source ↗</a>')
            self.source.show()
        else:
            self.source.hide()
