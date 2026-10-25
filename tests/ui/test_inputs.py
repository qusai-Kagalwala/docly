"""Tests for the polished inputs: search field and stylesheet icons."""

from __future__ import annotations

from PySide6.QtCore import Qt

from docly.ui.qss import build_stylesheet
from docly.ui.widgets.search_field import SearchField


def test_search_field_clear_button_only_with_text(qtbot) -> None:
    field = SearchField("Search presets")
    qtbot.addWidget(field)
    field.show()
    assert not field.clear_action.isVisible()
    qtbot.keyClicks(field, "ibps")
    assert field.clear_action.isVisible()
    field.clear_action.trigger()
    assert field.text() == "" and not field.clear_action.isVisible()
    assert field.placeholderText() == "Search presets" and field.objectName() == "SearchField"


def test_preset_picker_uses_search_field(qtbot, theme_manager, bundled_presets) -> None:
    from docly.ui.widgets.preset_picker import PresetPicker

    picker = PresetPicker(bundled_presets.presets, region="IN")
    qtbot.addWidget(picker)
    assert isinstance(picker.search, SearchField)


def test_stylesheet_uses_exported_icons(theme_manager) -> None:
    qss = build_stylesheet(theme_manager.tokens, "down.svg", None, {"plus": "plus.svg", "minus": "minus.svg", "check": "tick.svg"})
    assert 'url("tick.svg")' in qss and 'url("plus.svg")' in qss and 'url("minus.svg")' in qss
    plain = build_stylesheet(theme_manager.tokens)
    assert "url(" not in plain  # without files Qt draws its own


def test_theme_exports_the_icons(theme_manager, app_data) -> None:
    folder = app_data / "cache" / "icons"
    theme_manager.apply(force=True)
    names = {path.name.split("-")[0] for path in folder.glob("*.svg")}
    assert {"plus", "minus", "check", "chevron"} <= names


def test_number_boxes_centre_their_value(qtbot, theme_manager) -> None:
    from PySide6.QtWidgets import QSpinBox

    box = QSpinBox()
    qtbot.addWidget(box)
    box.ensurePolished()
    assert box.alignment() & Qt.AlignmentFlag.AlignHCenter
