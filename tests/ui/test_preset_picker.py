"""Tests for the grouped, searchable preset picker."""

from __future__ import annotations

import pytest

from docly.presets.models import PresetKind
from docly.ui.widgets import preset_picker
from docly.ui.widgets.preset_picker import PresetPicker, default_regions, matches, region_order, system_region


@pytest.fixture
def picker(qtbot, bundled_presets):
    widget = PresetPicker(bundled_presets.presets, region="IN")
    qtbot.addWidget(widget)
    return widget


def test_india_and_universal_by_default(picker, bundled_presets) -> None:
    ids = picker.visible_preset_ids()
    assert ids and all(i.startswith(("in-", "intl-")) for i in ids)
    assert "in-ibps-photo" in ids and "intl-photo-35x45" in ids
    assert "us-visa-photo" not in ids
    assert picker.headers()[0].startswith("India · ")
    assert "Universal · Passport" in picker.headers()


def test_only_photo_and_image_presets(picker, bundled_presets) -> None:
    allowed = {p.id for p in bundled_presets.presets if p.kind in (PresetKind.PHOTO, PresetKind.IMAGE)}
    picker.show_all.setChecked(True)
    ids = set(picker.visible_preset_ids())
    assert ids == allowed
    assert "in-ibps-signature" not in ids  # signatures get their own page
    assert "intl-doc-200kb" not in ids


def test_show_all_regions(picker) -> None:
    picker.show_all.setChecked(True)
    assert "us-visa-photo" in picker.visible_preset_ids()


def test_other_region_still_sees_india_first_after_own(qtbot, bundled_presets) -> None:
    widget = PresetPicker(bundled_presets.presets, region="US")
    qtbot.addWidget(widget)
    headers = widget.headers()
    assert headers[0].startswith("United States")
    assert any(h.startswith("India") for h in headers)
    assert not any(h.startswith("United Kingdom") for h in headers)


def test_unknown_region_falls_back_to_india_and_universal(qtbot, bundled_presets) -> None:
    widget = PresetPicker(bundled_presets.presets, region="DE")
    qtbot.addWidget(widget)
    assert widget.headers()[0].startswith("India")


def test_search_by_tag_across_regions(picker) -> None:
    picker.search.setText("banking")
    ids = picker.visible_preset_ids()
    assert ids and all("ibps" in i for i in ids)
    picker.search.setText("visa")
    assert "us-visa-photo" in picker.visible_preset_ids()  # search looks everywhere


def test_search_with_no_match(qtbot, picker) -> None:
    with qtbot.waitSignal(picker.presetChanged, timeout=1000) as blocker:
        picker.search.setText("zzzz nothing")
    assert blocker.args == [None]
    assert picker.current_preset() is None
    assert picker.visible_preset_ids() == []


def test_selection_survives_search_when_still_listed(picker) -> None:
    picker.select("in-ibps-thumb")
    picker.search.setText("ibps")
    assert picker.current_preset().id == "in-ibps-thumb"


def test_select_reveals_hidden_region(picker) -> None:
    assert picker.select("gb-passport-photo-online")
    assert picker.show_all.isChecked()
    assert picker.current_preset().id == "gb-passport-photo-online"
    assert not picker.select("does-not-exist")


def test_headers_cannot_be_selected(picker) -> None:
    model = picker.combo.model()
    for row in range(model.rowCount()):
        item = model.item(row)
        if item.data(preset_picker.PRESET_ID_ROLE) is None:
            assert not item.isSelectable() and not item.isEnabled()


def test_matches() -> None:
    from tests.core import images

    preset = images.preset(name="IBPS — Photograph", portal="IBPS", region="IN", tags=("banking", "clerk"))
    assert matches(preset, "")
    assert matches(preset, "ibps photo")
    assert matches(preset, "BANKING")
    assert matches(preset, "india")
    assert not matches(preset, "ibps visa")


def test_region_helpers(monkeypatch) -> None:
    assert default_regions("US") == ["US", "IN", "INTL"]
    assert default_regions("IN") == ["IN", "INTL"]
    assert region_order("US", {"GB", "IN", "INTL", "US"}) == ["US", "IN", "INTL", "GB"]

    class FakeLocale:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    monkeypatch.setattr(preset_picker.QLocale, "system", staticmethod(lambda: FakeLocale("en_IN")))
    assert system_region() == "IN"
    monkeypatch.setattr(preset_picker.QLocale, "system", staticmethod(lambda: FakeLocale("C")))
    assert system_region() == ""
