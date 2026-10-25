"""Preset dropdown grouped by region and category, with search.

The list starts with the user's own region (from the Windows region
setting) and the Universal presets; "Show all regions" reveals the rest.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCheckBox, QComboBox, QVBoxLayout, QWidget

from docly.presets.models import INTL_REGION, Category, Preset, PresetKind
from docly.ui.widgets.search_field import SearchField

#: Docly is India-first: Indian presets are always in the default list, even
#: on PCs set to another region (many Indian PCs are set to "United States").
HOME_REGION = "IN"

PRESET_ID_ROLE = Qt.ItemDataRole.UserRole + 1
CATEGORY_ORDER = (Category.EXAM, Category.GOVERNMENT, Category.PASSPORT, Category.VISA, Category.GENERAL)
CATEGORY_TITLES = {
    Category.EXAM: "Exams",
    Category.GOVERNMENT: "Government",
    Category.PASSPORT: "Passport",
    Category.VISA: "Visa",
    Category.GENERAL: "General",
}


def system_region() -> str:
    """Two-letter region from the Windows region setting, e.g. ``"IN"``."""
    name = QLocale.system().name()  # e.g. "en_IN"
    parts = name.replace("-", "_").split("_")
    return parts[1].upper() if len(parts) > 1 and len(parts[1]) == 2 else ""


def matches(preset: Preset, query: str) -> bool:
    """Search across name, portal, region, tags and id (all words must match)."""
    if not query.strip():
        return True
    haystack = " ".join(
        [preset.name, preset.portal, preset.region, preset.region_label, preset.id, *preset.tags]
    ).lower()
    return all(word in haystack for word in query.lower().split())


def default_regions(region: str) -> list[str]:
    """Regions shown before "Show all": the user's, India, then Universal."""
    return list(dict.fromkeys(r for r in (region, HOME_REGION, INTL_REGION) if r))


def region_order(region: str, available: Iterable[str]) -> list[str]:
    """Default regions first (see :func:`default_regions`), then the rest A–Z."""
    regions = set(available)
    ordered = [r for r in default_regions(region) if r in regions]
    ordered += sorted(regions - set(ordered))
    return ordered


class PresetPicker(QWidget):
    """Search box + grouped dropdown (+ "Show all regions").

    Signals:
        presetChanged(object): the selected :class:`Preset`, or ``None``.
    """

    presetChanged = Signal(object)

    def __init__(
        self,
        presets: Sequence[Preset],
        kinds: Sequence[PresetKind] = (PresetKind.PHOTO, PresetKind.IMAGE),
        region: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presets = [p for p in presets if p.kind in kinds]
        self._region = (region if region is not None else system_region()).upper()
        self._current_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.search = SearchField("Search presets, e.g. IBPS, visa, passport")
        self.search.setAccessibleName("Search presets")
        layout.addWidget(self.search)

        self.combo = QComboBox()
        self.combo.setAccessibleName("Preset")
        self.combo.setMaxVisibleItems(18)
        # Don't let the longest preset name force the column wider.
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self._model = QStandardItemModel(self.combo)
        self.combo.setModel(self._model)
        layout.addWidget(self.combo)

        self.show_all = QCheckBox("Show all regions")
        self.show_all.setVisible(self._has_other_regions())
        layout.addWidget(self.show_all)

        self.search.textChanged.connect(self._rebuild)
        self.show_all.toggled.connect(self._rebuild)
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        self._rebuild()

    # ----- public API -------------------------------------------------
    @property
    def region(self) -> str:
        return self._region

    def current_preset(self) -> Preset | None:
        return self._by_id(self._current_id)

    def visible_preset_ids(self) -> list[str]:
        """Ids currently listed (in order), for tests and keyboard logic."""
        return [
            self._model.item(row).data(PRESET_ID_ROLE)
            for row in range(self._model.rowCount())
            if self._model.item(row).data(PRESET_ID_ROLE)
        ]

    def headers(self) -> list[str]:
        return [
            self._model.item(row).text()
            for row in range(self._model.rowCount())
            if self._model.item(row).data(PRESET_ID_ROLE) is None
        ]

    def select(self, preset_id: str) -> bool:
        """Select a preset by id (revealing all regions if needed)."""
        preset = self._by_id(preset_id)
        if preset is None:
            return False
        if preset_id not in self.visible_preset_ids():
            self.search.clear()
            if preset_id not in self.visible_preset_ids():
                self.show_all.setChecked(True)
        row = self._row_of(preset_id)
        if row is None:
            return False
        self.combo.setCurrentIndex(row)
        return True

    # ----- internals --------------------------------------------------
    def _has_other_regions(self) -> bool:
        return any(p.region not in default_regions(self._region) for p in self._presets)

    def _shown_regions(self) -> list[str]:
        available = {p.region for p in self._presets}
        ordered = region_order(self._region, available)
        if self.show_all.isChecked() or self.search.text().strip():
            return ordered  # searching looks everywhere
        default = [r for r in ordered if r in default_regions(self._region)]
        return default or ordered

    def _rebuild(self) -> None:
        previous = self._current_id
        query = self.search.text()
        self.combo.blockSignals(True)
        self._model.clear()
        for region in self._shown_regions():
            for category in CATEGORY_ORDER:
                group = [
                    p for p in self._presets if p.region == region and p.category == category and matches(p, query)
                ]
                if not group:
                    continue
                self._model.appendRow(self._header_item(f"{group[0].region_label} · {CATEGORY_TITLES[category]}"))
                for preset in group:
                    item = QStandardItem(f"    {preset.name}")
                    item.setData(preset.id, PRESET_ID_ROLE)
                    item.setToolTip(" · ".join(x for x in (preset.pixel_text, preset.kb_range_text) if x))
                    self._model.appendRow(item)
        if not self.visible_preset_ids():
            empty = QStandardItem("No presets match your search")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._model.appendRow(empty)
        self.combo.blockSignals(False)

        row = self._row_of(previous) if previous else None
        if row is None:
            ids = self.visible_preset_ids()
            row = self._row_of(ids[0]) if ids else None
        if row is not None:
            self.combo.setCurrentIndex(row)
            self._on_index_changed(row)
        else:
            self.combo.setCurrentIndex(-1)
            self._set_current(None)

    @staticmethod
    def _header_item(text: str) -> QStandardItem:
        item = QStandardItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
        font = QFont()
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
        return item

    def _on_index_changed(self, row: int) -> None:
        item = self._model.item(row) if row >= 0 else None
        preset_id = item.data(PRESET_ID_ROLE) if item is not None else None
        if preset_id is None:
            return
        self._set_current(preset_id)

    def _set_current(self, preset_id: str | None) -> None:
        if preset_id == self._current_id:
            return
        self._current_id = preset_id
        self.presetChanged.emit(self._by_id(preset_id))

    def _row_of(self, preset_id: str | None) -> int | None:
        for row in range(self._model.rowCount()):
            if self._model.item(row).data(PRESET_ID_ROLE) == preset_id:
                return row
        return None

    def _by_id(self, preset_id: str | None) -> Preset | None:
        return next((p for p in self._presets if p.id == preset_id), None)
