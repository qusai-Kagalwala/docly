"""Tests for the Home page."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from docly import config
from docly.ui.main_window import MainWindow
from docly.ui.pages.home_page import FEATURES, HomePage


def test_app_opens_on_home(main_window: MainWindow) -> None:
    assert main_window.current_page_id() == "home"
    assert isinstance(main_window.page("home"), HomePage)


@pytest.mark.parametrize("page_id", [f.page_id for f in FEATURES])
def test_feature_cards_open_their_page(main_window: MainWindow, qtbot, page_id: str) -> None:
    card = main_window.page("home").feature_cards[page_id]
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    assert main_window.current_page_id() == page_id
    main_window.show_page("home")
    qtbot.mouseClick(card.open_button, Qt.MouseButton.LeftButton)
    assert main_window.current_page_id() == page_id


def test_feature_card_keyboard(main_window: MainWindow, qtbot) -> None:
    card = main_window.page("home").feature_cards["pdf"]
    card.setFocus()
    qtbot.keyClick(card, Qt.Key.Key_Return)
    assert main_window.current_page_id() == "pdf"


def test_every_tool_is_ready(main_window: MainWindow) -> None:
    cards = main_window.page("home").feature_cards
    assert all(card.feature.ready for card in cards.values())
    assert not any(label.text() == "Coming soon" for card in cards.values() for label in card.findChildren(type(card.icon)))


def test_start_with_a_photo(main_window: MainWindow, qtbot) -> None:
    qtbot.mouseClick(main_window.page("home").start_button, Qt.MouseButton.LeftButton)
    assert main_window.current_page_id() == "photo"


def test_credits_and_links(main_window: MainWindow) -> None:
    home = main_window.page("home")
    text = home.links.text()
    assert config.CREATOR_GITHUB_URL in text and config.CREATOR_LINKEDIN_URL in text and config.REPO_URL in text
    assert home.links.openExternalLinks()
    assert config.REPO_URL in home.star_link.text()
    assert any(config.CREATOR_NAME in label.text() for label in home.findChildren(type(home.links)))


def test_take_the_tour_button(main_window: MainWindow, qtbot) -> None:
    qtbot.mouseClick(main_window.page("home").tour_button, Qt.MouseButton.LeftButton)
    assert main_window.tour is not None and main_window.tour.isVisible()
    main_window.tour.skip()


def test_fits_the_smallest_window(main_window: MainWindow, qtbot) -> None:
    main_window.resize(*config.WINDOW_MIN_SIZE)
    qtbot.wait(20)
    home = main_window.page("home")
    for card in home.feature_cards.values():
        assert card.width() >= card.minimumSizeHint().width()
