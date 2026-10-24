"""Smoke tests: the app launches, pages load, navigation and theming work."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from docly import config
from docly.ui.about_dialog import AboutDialog
from docly.ui.main_window import MainWindow
from docly.ui.settings_store import SettingsStore
from docly.ui.theme import DARK, LIGHT, ThemeManager, ThemeMode

EXPECTED_PAGES = ["photo", "signature", "pdf", "batch", "settings"]


def test_window_launches(main_window: MainWindow) -> None:
    assert main_window.isVisible()
    assert main_window.windowTitle() == "Docly"
    assert main_window.minimumWidth() >= 1000 and main_window.minimumHeight() >= 650
    assert main_window.current_page_id() == "photo"


def test_all_pages_load(main_window: MainWindow) -> None:
    assert main_window.page_ids() == EXPECTED_PAGES
    assert main_window.stack.count() == len(EXPECTED_PAGES)
    for page in main_window.pages:
        assert page.header.title_label.text()


@pytest.mark.parametrize("index,page_id", list(enumerate(EXPECTED_PAGES)))
def test_sidebar_navigation(main_window: MainWindow, qtbot, index: int, page_id: str) -> None:
    button = main_window.sidebar.nav_buttons[index]
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert main_window.current_page_id() == page_id
    checked = [b for b in main_window.sidebar.nav_buttons if b.isChecked()]
    assert checked == [button]


def test_show_page_by_id(main_window: MainWindow) -> None:
    main_window.show_page("settings")
    assert main_window.current_page_id() == "settings"
    assert main_window.sidebar.nav_buttons[4].isChecked()
    with pytest.raises(KeyError):
        main_window.show_page("nope")


def test_theme_toggle_button(main_window: MainWindow, theme_manager: ThemeManager, qtbot, qapp) -> None:
    toggle = main_window.sidebar.theme_button
    assert toggle.text() == "Dark mode"
    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert theme_manager.is_dark
    assert DARK.bg in qapp.styleSheet()
    assert toggle.text() == "Light mode"
    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert not theme_manager.is_dark
    assert LIGHT.bg in qapp.styleSheet()


def test_settings_theme_selector(main_window: MainWindow, theme_manager: ThemeManager, qtbot) -> None:
    selector = main_window.pages[-1].theme_selector
    assert selector.value() == "system"
    qtbot.mouseClick(selector.buttons["dark"], Qt.MouseButton.LeftButton)
    assert theme_manager.mode == ThemeMode.DARK
    # Changing the theme elsewhere (sidebar toggle) keeps the selector in sync.
    theme_manager.toggle()
    assert selector.value() == "light"


def test_theme_survives_restart(qtbot, qapp, theme_manager: ThemeManager, app_data: Path) -> None:
    theme_manager.set_mode(ThemeMode.DARK)
    new_manager = ThemeManager(qapp, SettingsStore(app_data / "settings.ini"))
    window = MainWindow(new_manager)
    qtbot.addWidget(window)
    assert new_manager.is_dark
    assert window.sidebar.theme_button.text() == "Light mode"
    assert window.pages[-1].theme_selector.value() == "dark"


def test_about_dialog_opens_and_closes(main_window: MainWindow, qtbot) -> None:
    qtbot.mouseClick(main_window.sidebar.about_button, Qt.MouseButton.LeftButton)
    dialog = main_window.findChild(AboutDialog)
    assert dialog is not None
    qtbot.waitExposed(dialog)
    assert config.APP_VERSION in dialog.version_chip.text()
    assert config.REPO_URL in dialog.link_label.text()
    qtbot.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()


def test_layout_survives_resizing(main_window: MainWindow, qtbot) -> None:
    for width, height in [(1000, 650), (1600, 1000), (1000, 650)]:
        main_window.resize(width, height)
        qtbot.wait(10)
        assert main_window.sidebar.width() == config.SIDEBAR_WIDTH
        assert main_window.stack.width() > 0


def test_logs_folder_button(main_window: MainWindow, monkeypatch, qtbot) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        "docly.ui.pages.settings_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    main_window.show_page("settings")
    qtbot.mouseClick(main_window.pages[-1].open_logs_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 1
