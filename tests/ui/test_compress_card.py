"""Tests for the "Shrink to size" card."""

from __future__ import annotations

import pytest

from docly.ui.pdf.compress_card import CUSTOM, OFF, CompressCard, ShrinkSettings


@pytest.fixture
def card(qtbot, theme_manager, bundled_presets) -> CompressCard:
    widget = CompressCard(theme_manager, bundled_presets.presets, region="IN")
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_off_by_default(card: CompressCard) -> None:
    assert card.current() == OFF
    assert card.settings() == ShrinkSettings()
    assert not card.settings().active
    assert not card.custom_kb.isVisible()


def test_lists_only_pdf_presets_with_a_limit(card: CompressCard, bundled_presets) -> None:
    listed = set(card.presets)
    expected = {p.id for p in bundled_presets.presets if p.kind.value == "document" and p.kb_max is not None}
    assert listed == expected and "in-jee-main-certificate" in listed
    assert "in-ibps-photo" not in listed


def test_custom_limit_uses_strict_kb(qtbot, card: CompressCard) -> None:
    with qtbot.waitSignal(card.changed):
        card.select(CUSTOM)
    assert card.custom_kb.isVisible()
    card.custom_kb.setValue(250)
    settings = card.settings()
    assert settings.target_bytes == 250_000 and settings.min_bytes is None
    assert settings.label == "250 KB"
    assert "under 250 KB" in card.hint.text()


def test_preset_limit_has_safe_window(card: CompressCard) -> None:
    card.select("in-jee-main-certificate")  # 50–300 KB
    settings = card.settings()
    assert settings.target_bytes == 300_000
    assert settings.min_bytes == 50 * 1024
    assert settings.label == "300 KB"
    assert "isn't verified" in card.hint.text()


def test_grayscale_alone_is_active(card: CompressCard) -> None:
    card.grayscale.setChecked(True)
    settings = card.settings()
    assert settings.active and settings.grayscale and settings.target_bytes is None
    assert "grey" in card.hint.text()


def test_long_names_do_not_widen_the_column(card: CompressCard) -> None:
    # The box shrinks to the column (its long names are elided, not widening it).
    # The whole-column check is in test_pdf_page.py, measured with real fonts.
    assert card.choice.minimumSizeHint().width() <= 150
    view = card.choice.view()
    assert view.minimumWidth() >= view.sizeHintForColumn(0)  # open list shows full names
