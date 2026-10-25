"""Tests for the Photo page's Background card."""

from __future__ import annotations

import pytest

from docly.core.background import COLOURS
from docly.ui.widgets import background_card
from docly.ui.widgets.background_card import BLOCKED, CUSTOM, KEEP, MISSING, BackgroundCard
from tests.core import images


@pytest.fixture
def card(qtbot, theme_manager) -> BackgroundCard:
    widget = BackgroundCard(theme_manager)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_keeps_original_by_default(card: BackgroundCard) -> None:
    assert card.current() == KEEP
    assert card.options() is None
    assert not card.softness_row.isVisible()


def test_named_colours(qtbot, card: BackgroundCard) -> None:
    with qtbot.waitSignal(card.changed):
        card.select("light_blue")
    options = card.options()
    assert options.colour == COLOURS["light_blue"]
    assert card.softness_row.isVisible()
    card.softness.setValue(20)
    assert card.options().softness == 20


def test_custom_colour(qtbot, card: BackgroundCard, monkeypatch) -> None:
    monkeypatch.setattr(background_card, "ask_colour", lambda parent, start: (10, 20, 30))
    index = card.choice.findData(CUSTOM)
    card.choice.setCurrentIndex(index)
    with qtbot.waitSignal(card.changed):
        card.choice.activated.emit(index)
    assert card.options().colour == (10, 20, 30)
    assert "#0A141E" in card.choice.itemText(index)


def test_cancelled_custom_colour_keeps_previous(card: BackgroundCard, monkeypatch) -> None:
    monkeypatch.setattr(background_card, "ask_colour", lambda parent, start: None)
    index = card.choice.findData(CUSTOM)
    card.choice.setCurrentIndex(index)
    card.choice.activated.emit(index)
    assert card.options().colour == card.custom_colour


def test_blocked_presets_lock_the_card_and_remember_choice(card: BackgroundCard) -> None:
    card.select("white")
    card.set_preset(images.preset(no_edits=True))
    assert not card.choice.isEnabled()
    assert card.options() is None
    assert card.message.text() == BLOCKED
    card.set_preset(images.preset())
    assert card.choice.isEnabled()
    assert card.options().colour == COLOURS["white"]  # choice came back


def test_missing_model(qtbot, theme_manager) -> None:
    card = BackgroundCard(theme_manager, available=False)
    qtbot.addWidget(card)
    card.select("white")
    assert card.options() is None
    assert card.message.text() == MISSING
