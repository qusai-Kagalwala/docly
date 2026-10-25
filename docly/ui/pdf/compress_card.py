""""Shrink to size" card: pick a size limit (a preset or your own) and greyscale."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QSizePolicy, QSpinBox, QWidget

from docly.core.compress import byte_window
from docly.presets.models import Preset, PresetKind
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.preset_picker import region_order, system_region

OFF = "off"
CUSTOM = "custom"
DEFAULT_CUSTOM_KB = 500


@dataclass(frozen=True)
class ShrinkSettings:
    """What the user asked for (read on the UI thread, used by workers)."""

    target_bytes: int | None = None  # None: no size limit
    min_bytes: int | None = None
    grayscale: bool = False
    label: str = ""  # e.g. "500 KB", for messages

    @property
    def active(self) -> bool:
        return self.target_bytes is not None or self.grayscale


def format_limit(kb: float) -> str:
    return f"{kb / 1000:g} MB" if kb >= 1000 else f"{kb:g} KB"


class CompressCard(Card):
    """Signals:
    changed(): any setting changed.
    """

    changed = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        presets: list[Preset],
        region: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent)
        section = QLabel("Shrink to size")
        section.setProperty("role", "section")
        self.body.addWidget(section)

        documents = [p for p in presets if p.kind == PresetKind.DOCUMENT and p.kb_max is not None]
        order = region_order((region or system_region()).upper(), {p.region for p in documents})
        documents.sort(key=lambda p: (order.index(p.region), p.kb_max or 0, p.name))
        self.presets = {p.id: p for p in documents}

        self.choice = QComboBox()
        self.choice.setAccessibleName("Size limit")
        # Long preset names must not widen the narrow side column.
        self.choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.choice.setMinimumContentsLength(1)
        self.choice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.choice.addItem("Don't shrink", OFF)
        self.choice.addItem("My own limit…", CUSTOM)
        self.choice.insertSeparator(self.choice.count())
        for preset in documents:
            self.choice.addItem(f"{preset.name} · {preset.kb_range_text}", preset.id)
            self.choice.setItemData(self.choice.count() - 1, preset.notes or preset.name, Qt.ItemDataRole.ToolTipRole)
        # The open list may be wider than the box, so full names stay readable.
        view = self.choice.view()
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setMinimumWidth(view.sizeHintForColumn(0) + 24)
        self.body.addWidget(self.choice)

        self.custom_kb = QSpinBox()
        self.custom_kb.setRange(10, 100_000)
        self.custom_kb.setSingleStep(50)
        self.custom_kb.setValue(DEFAULT_CUSTOM_KB)
        self.custom_kb.setPrefix("Up to ")
        self.custom_kb.setSuffix(" KB")
        self.custom_kb.setAccessibleName("Largest size in KB")
        self.body.addWidget(self.custom_kb)

        self.grayscale = QCheckBox("Black && white pictures")
        self.grayscale.setToolTip(
            "Turns scans and photos grey, which often halves the size. Coloured text stays coloured.\n"
            "Leave it off if the portal needs colour documents."
        )
        self.body.addWidget(self.grayscale)

        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)

        self.choice.currentIndexChanged.connect(self._on_changed)
        self.custom_kb.valueChanged.connect(self._on_changed)
        self.grayscale.toggled.connect(self._on_changed)
        self._update()

    # ----- public -------------------------------------------------------
    def select(self, value: str) -> None:
        """Choose ``OFF``, ``CUSTOM`` or a preset id."""
        index = self.choice.findData(value)
        if index >= 0:
            self.choice.setCurrentIndex(index)

    def current(self) -> str:
        return self.choice.currentData() or OFF

    def settings(self) -> ShrinkSettings:
        grey = self.grayscale.isChecked()
        value = self.current()
        if value == CUSTOM:
            kb = self.custom_kb.value()
            return ShrinkSettings(math.floor(kb * 1000), None, grey, format_limit(kb))
        preset = self.presets.get(value)
        if preset is None:
            return ShrinkSettings(None, None, grey, "")
        window = byte_window(preset)
        return ShrinkSettings(window.high, window.low, grey, format_limit(preset.kb_max or 0))

    # ----- internals ------------------------------------------------------
    def _on_changed(self, *_args: object) -> None:
        self._update()
        self.changed.emit()

    def _update(self) -> None:
        value = self.current()
        self.custom_kb.setVisible(value == CUSTOM)
        settings = self.settings()
        if settings.target_bytes is None:
            self.hint.setText("Pictures are turned grey; nothing else changes." if settings.grayscale else "")
        else:
            text = f"Pictures inside the PDF are re-saved until it's under {settings.label}. Text stays sharp."
            preset = self.presets.get(value)
            if preset is not None and not preset.verified:
                text += " This portal's limit isn't verified yet, so check its notice."
            self.hint.setText(text)
        self.hint.setVisible(bool(self.hint.text()))
