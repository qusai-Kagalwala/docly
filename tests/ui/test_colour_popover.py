"""Tests for Docly's colour popover."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from docly.ui.widgets import colour_popover
from docly.ui.widgets.colour_popover import SWATCHES, ColourPopover, is_dark, parse_hex, to_hex


@pytest.fixture(autouse=True)
def _no_recent(monkeypatch) -> None:
    monkeypatch.setattr(colour_popover, "_recent", [])


@pytest.mark.parametrize(
    ("text", "rgb"),
    [("#DCE6F0", (220, 230, 240)), ("dce6f0", (220, 230, 240)), (" #abc ", (170, 187, 204)), ("#12345", None), ("blue", None), ("", None)],
)
def test_parse_hex(text: str, rgb) -> None:  # noqa: ANN001
    assert parse_hex(text) == rgb


def test_to_hex_and_darkness() -> None:
    assert to_hex((220, 230, 240)) == "#DCE6F0"
    assert is_dark((30, 60, 120)) and not is_dark((255, 255, 255))


@pytest.fixture
def popover(qtbot, theme_manager) -> ColourPopover:
    widget = ColourPopover(theme_manager, (255, 255, 255))
    qtbot.addWidget(widget)
    return widget


def test_starts_on_the_given_colour(popover: ColourPopover) -> None:
    assert popover.colour() == (255, 255, 255)
    assert popover.hex_edit.text() == "#FFFFFF"
    assert popover.swatches[0].isChecked() and len(popover.swatches) == len(SWATCHES)
    assert not popover.recent_label.isVisibleTo(popover)


def test_clicking_a_swatch_picks_it(qtbot, popover: ColourPopover) -> None:
    qtbot.mouseClick(popover.swatches[4], Qt.MouseButton.LeftButton)
    assert popover.colour() == SWATCHES[4][1]
    assert popover.hex_edit.text() == to_hex(SWATCHES[4][1])
    assert popover.swatches[4].isChecked() and not popover.swatches[0].isChecked()


def test_typing_a_hex_code(qtbot, popover: ColourPopover) -> None:
    popover.hex_edit.clear()
    qtbot.keyClicks(popover.hex_edit, "#1E3C78")
    assert popover.colour() == (30, 60, 120)
    assert popover.hint.text() == colour_popover.DARK_HINT  # dark backgrounds get a gentle note


def test_incomplete_hex_disables_use(qtbot, popover: ColourPopover) -> None:
    popover.hex_edit.clear()
    qtbot.keyClicks(popover.hex_edit, "#12AB")
    assert not popover.use_button.isEnabled()
    assert "6 hex digits" in popover.hint.text()


def test_use_remembers_recent(qtbot, theme_manager, popover: ColourPopover) -> None:
    qtbot.mouseClick(popover.swatches[5], Qt.MouseButton.LeftButton)
    popover._accept_if_valid()
    assert popover.result() == popover.DialogCode.Accepted
    again = ColourPopover(theme_manager, (255, 255, 255))
    qtbot.addWidget(again)
    assert [b.rgb for b in again.recent_buttons] == [SWATCHES[5][1]]
    assert again.recent_label.isVisibleTo(again)


def test_recent_list_is_short(monkeypatch) -> None:
    for value in range(10):
        colour_popover.remember((value, value, value))
    colour_popover.remember((3, 3, 3))
    recent = colour_popover.recent_colours()
    assert len(recent) == colour_popover.MAX_RECENT and recent[0] == (3, 3, 3)
