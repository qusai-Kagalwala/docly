"""Phase 12b: Settings (output folder, presets, reduce motion, help),
app-wide keyboard shortcuts, and names for screen readers."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QSlider

from docly.core.batch import batch_folder
from docly.core.errors import CorruptImageError
from docly.core.image_io import load_image_bytes
from docly.presets.loader import default_presets
from docly.ui import desktop, motion
from docly.ui.main_window import MainWindow
from docly.ui.pages import settings_page
from docly.ui.pages.settings_page import NEXT_TO_ORIGINAL, ONE_FOLDER, SettingsPage
from docly.ui.shortcuts import SHORTCUTS, ShortcutsDialog
from docly.ui.theme import ThemeManager
from tests.core import images


@pytest.fixture
def window(qtbot, theme_manager: ThemeManager) -> MainWindow:
    w = MainWindow(theme_manager, default_presets())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    return w


def settings(window: MainWindow) -> SettingsPage:
    page = window.page("settings")
    assert isinstance(page, SettingsPage)
    return page


# ----- output folder ---------------------------------------------------------
def test_defaults_to_next_to_the_original(window: MainWindow, tmp_path: Path) -> None:
    page = settings(window)
    assert page.save_mode.value() == NEXT_TO_ORIGINAL and not page.folder_row.isVisibleTo(page)
    assert desktop.output_folder_for(tmp_path / "a.jpg") == tmp_path / "Docly_Output"


def test_choose_one_folder(window: MainWindow, tmp_path: Path, monkeypatch, theme_manager) -> None:
    chosen = tmp_path / "Uploads ready"
    monkeypatch.setattr(settings_page, "ask_folder", lambda parent, start: chosen)
    page = settings(window)
    page.save_mode.valueChanged.emit(ONE_FOLDER)
    assert page.save_mode.value() == ONE_FOLDER
    assert desktop.output_folder_for(tmp_path / "x" / "a.jpg") == chosen
    assert theme_manager.store.output_folder() == chosen
    assert str(chosen) in page.folder_label.text()
    # Batch runs go into a dated folder inside it.
    assert batch_folder(tmp_path / "a.jpg", "IBPS", base=desktop.output_folder_for(tmp_path / "a.jpg")).parent == chosen


def test_photo_saves_into_the_chosen_folder(window: MainWindow, tmp_path: Path, monkeypatch, qtbot) -> None:
    chosen = tmp_path / "Ready"
    monkeypatch.setattr(settings_page, "ask_folder", lambda parent, start: chosen)
    settings(window).choose_folder()
    photo = window.page("photo")
    photo.picker.select("in-ibps-photo")
    (tmp_path / "src").mkdir()
    photo.load_file(images.save(images.photo_like(600, 800), tmp_path / "src" / "me.jpg"))
    qtbot.waitUntil(lambda: photo.result_card.save_button.isEnabled(), timeout=15_000)
    saved = photo.result_card.save()
    assert saved is not None and saved.parent == chosen


def test_cancelling_the_folder_picker_changes_nothing(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(settings_page, "ask_folder", lambda parent, start: None)
    page = settings(window)
    page.save_mode.valueChanged.emit(ONE_FOLDER)
    assert page.save_mode.value() == NEXT_TO_ORIGINAL and desktop.custom_output_folder() is None


def test_unwritable_folder_is_refused(window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings_page, "can_write_to", lambda folder: False)
    page = settings(window)
    assert not page.set_output_folder(tmp_path / "locked")
    assert page.folder_message.isVisibleTo(page) and "can't save into" in page.folder_message.text()
    assert desktop.custom_output_folder() is None


def test_back_to_next_to_original(window: MainWindow, tmp_path: Path, theme_manager) -> None:
    page = settings(window)
    page.set_output_folder(tmp_path / "out")
    page.save_mode.valueChanged.emit(NEXT_TO_ORIGINAL)
    assert desktop.custom_output_folder() is None and theme_manager.store.output_folder() is None


def test_folder_choice_survives_a_restart(qtbot, window: MainWindow, theme_manager, tmp_path: Path) -> None:
    settings(window).set_output_folder(tmp_path / "out")
    desktop.set_custom_output_folder(None)  # as if the app had closed
    again = MainWindow(theme_manager, default_presets())
    qtbot.addWidget(again)
    assert desktop.custom_output_folder() == tmp_path / "out"
    assert settings(again).save_mode.value() == ONE_FOLDER


# ----- presets -------------------------------------------------------------------
def test_last_preset_is_remembered(qtbot, window: MainWindow, theme_manager) -> None:
    assert window.page("photo").picker.select("in-upsc-photo")
    again = MainWindow(theme_manager, default_presets())
    qtbot.addWidget(again)
    assert again.page("photo").picker.current_preset().id == "in-upsc-photo"


def test_presets_not_remembered_when_switched_off(qtbot, window: MainWindow, theme_manager) -> None:
    default_id = window.page("photo").picker.current_preset().id
    settings(window).remember_presets.setChecked(False)
    window.page("photo").picker.select("in-upsc-photo")
    again = MainWindow(theme_manager, default_presets())
    qtbot.addWidget(again)
    assert again.page("photo").picker.current_preset().id == default_id
    assert not settings(again).remember_presets.isChecked()


def test_every_picker_has_a_key(window: MainWindow) -> None:
    keys = set(window.preset_pickers())
    assert {"photo/0", "signature/0", "batch/0", "batch/1"} <= keys


# ----- appearance and help -------------------------------------------------------------
def test_reduce_motion_setting(window: MainWindow, monkeypatch, theme_manager) -> None:
    monkeypatch.setenv(motion.ENV_REDUCE, "0")
    monkeypatch.setattr(motion, "windows_animations_enabled", lambda: True)
    assert motion.enabled()
    settings(window).reduce_motion.setChecked(True)
    assert not motion.enabled() and theme_manager.store.reduce_motion()


def test_show_the_tour_again(qtbot, window: MainWindow) -> None:
    qtbot.mouseClick(settings(window).tour_button, Qt.MouseButton.LeftButton)
    assert window.tour is not None and window.tour.isVisible()
    window.tour.skip()


def test_shortcuts_dialog_lists_everything(qtbot, window: MainWindow) -> None:
    qtbot.mouseClick(settings(window).shortcuts_button, Qt.MouseButton.LeftButton)
    dialog = window.findChild(ShortcutsDialog)
    assert dialog is not None and dialog.isVisible()
    assert len(dialog.rows) == sum(len(entries) for _section, entries in SHORTCUTS)
    dialog.accept()


def test_about_opens_shortcuts(window: MainWindow) -> None:
    about = window.show_about()
    about.shortcuts_button.click()
    assert not about.isVisible() and window.show_shortcuts().isVisible()


# ----- keyboard -----------------------------------------------------------------
@pytest.mark.parametrize(("number", "page_id"), [(1, "home"), (2, "photo"), (5, "sign"), (7, "settings")])
def test_ctrl_number_switches_page(window: MainWindow, number: int, page_id: str) -> None:
    window.shortcuts[f"Ctrl+{number}"].activated.emit()
    assert window.current_page_id() == page_id


def test_ctrl_number_with_real_keys(qtbot, window: MainWindow) -> None:
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert window.current_page_id() == "signature"


def test_f1_shows_shortcuts(window: MainWindow) -> None:
    window.shortcuts["F1"].activated.emit()
    assert window.findChild(ShortcutsDialog).isVisible()


def test_ctrl_o_opens_the_picker(window: MainWindow, monkeypatch) -> None:
    calls: list[str] = []
    for page in window.pages:
        if hasattr(page, "browse"):
            monkeypatch.setattr(page, "browse", lambda pid=page.PAGE_ID: calls.append(pid))
    window.show_page("pdf")
    window.shortcuts["Ctrl+O"].activated.emit()
    window.show_page("home")
    window.shortcuts["Ctrl+O"].activated.emit()  # Home: goes to Photo first
    window.show_page("settings")
    window.shortcuts["Ctrl+O"].activated.emit()  # nothing to open here
    assert calls == ["pdf", "photo"]


def test_ctrl_s_only_when_there_is_something_to_save(window: MainWindow, monkeypatch) -> None:
    window.show_page("photo")
    assert not window.save_on_current_page()  # nothing processed yet
    card = window.page("photo").result_card
    saves: list[bool] = []
    card.save_button.clicked.disconnect()
    card.save_button.clicked.connect(lambda: saves.append(True))
    card.save_button.setEnabled(True)
    assert window.save_on_current_page() and saves == [True]
    window.show_page("settings")
    assert not window.save_on_current_page()


# ----- names for screen readers ---------------------------------------------------------
def test_every_control_has_a_name(window: MainWindow) -> None:
    window.show_about()
    window.show_shortcuts()
    missing: list[str] = []
    for top in QApplication.topLevelWidgets():
        if not top.isVisible():
            continue
        for button in top.findChildren(QAbstractButton):
            if button.objectName() == "qt_tableview_cornerbutton" or not button.isVisibleTo(top):
                continue
            if not button.text().strip() and not (button.accessibleName() and button.toolTip()):
                missing.append(f"button in {type(button.parent()).__name__}: tooltip={button.toolTip()!r}")
        for kind in (QLineEdit, QComboBox, QAbstractSpinBox, QSlider, QPlainTextEdit):
            for control in top.findChildren(kind):
                inside = isinstance(control.parent(), (QComboBox, QAbstractSpinBox))
                if not inside and not control.accessibleName():
                    missing.append(f"{kind.__name__} in {type(control.parent()).__name__}")
    assert missing == []


def test_empty_file_hint_mentions_onedrive() -> None:
    with pytest.raises(CorruptImageError, match="OneDrive"):
        load_image_bytes(b"", "scan.jpg")
