"""Tests for motion (on/off), page crossfade, the sliding sidebar bar, and toasts."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from docly.ui import desktop, motion
from docly.ui.main_window import MainWindow
from docly.ui.widgets.toast import SHOW_MS


@pytest.fixture
def motion_on(monkeypatch) -> None:
    monkeypatch.setenv(motion.ENV_REDUCE, "0")
    monkeypatch.setattr(motion, "windows_animations_enabled", lambda: True)
    motion.set_reduce_motion(False)


def test_motion_is_off_in_tests_and_with_the_setting(monkeypatch) -> None:
    assert not motion.enabled()  # conftest sets DOCLY_REDUCE_MOTION=1
    monkeypatch.setenv(motion.ENV_REDUCE, "0")
    monkeypatch.setattr(motion, "windows_animations_enabled", lambda: True)
    assert motion.enabled()
    motion.set_reduce_motion(True)
    try:
        assert not motion.enabled()
    finally:
        motion.set_reduce_motion(False)


def test_helpers_jump_to_the_end_when_motion_is_off(qtbot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    child = QLabel("hi", parent)
    child.hide()
    assert motion.fade_in(child) is None
    assert child.isVisible() and child.graphicsEffect() is None


def test_fade_in_animates_and_cleans_up(qtbot, motion_on) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    child = QLabel("hi", parent)
    child.hide()
    animation = motion.fade_in(child, 40)
    assert animation is not None and child.isVisible()
    qtbot.waitUntil(lambda: child.graphicsEffect() is None, timeout=2000)


def test_page_switch_crossfades(qtbot, main_window: MainWindow, motion_on) -> None:
    main_window.show_page("photo")
    covers = main_window.stack.findChildren(QWidget, "PageCover")
    assert len(covers) == 1, "a background-coloured cover should fade off the new page"
    assert covers[0].geometry() == main_window.stack.rect()
    assert main_window.current_page_id() == "photo"  # the real page is live at once
    qtbot.waitUntil(lambda: not main_window.stack.findChildren(QWidget, "PageCover"), timeout=2000)


def test_quick_clicks_leave_one_cover(qtbot, main_window: MainWindow, motion_on) -> None:
    main_window.show_page("photo")
    main_window.show_page("pdf")
    main_window.show_page("batch")
    qtbot.wait(10)  # let deleteLater run
    assert len(main_window.stack.findChildren(QWidget, "PageCover")) <= 1
    assert main_window.current_page_id() == "batch"


def test_no_crossfade_when_motion_is_off(main_window: MainWindow) -> None:
    main_window.show_page("pdf")
    assert not main_window.stack.findChildren(QWidget, "PageCover")


def test_sidebar_bar_sits_beside_the_current_item(qtbot, main_window: MainWindow) -> None:
    sidebar = main_window.sidebar
    main_window.show_page("batch")
    target = sidebar.indicator_target()
    button = sidebar.nav_buttons[main_window.page_ids().index("batch")]
    assert target is not None and sidebar.indicator.geometry() == target
    assert button.geometry().top() < target.center().y() < button.geometry().bottom()
    assert sidebar.indicator.isVisible()


def test_sidebar_bar_slides(qtbot, main_window: MainWindow, motion_on) -> None:
    sidebar = main_window.sidebar
    main_window.show_page("pdf")
    target = sidebar.indicator_target()
    qtbot.waitUntil(lambda: sidebar.indicator.geometry() == target, timeout=2000)


def test_saving_shows_a_toast(qtbot, main_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(desktop, "reveal_in_folder", lambda path: opened.append(path) or True)
    card = main_window.page("photo").result_card
    saved = tmp_path / "photo_ready.jpg"
    card.saved.emit(saved)
    toast = main_window.toasts.toast
    assert toast.isVisible() and toast.text() == "Saved photo_ready.jpg"
    assert toast.action_button.text() == "Open folder" and toast.timer.interval() == SHOW_MS
    qtbot.mouseClick(toast.action_button, Qt.MouseButton.LeftButton)
    assert opened == [saved] and not toast.isVisible()


def test_saving_several_files_toast(main_window: MainWindow, tmp_path: Path) -> None:
    card = main_window.page("pdf").result_card
    card.saved.emit([tmp_path / "a.pdf", tmp_path / "b.pdf"])
    toast = main_window.toasts.toast
    assert toast.text() == "Saved 2 files"
    toast.dismiss()
    assert not toast.isVisible()


def test_toast_stays_inside_the_window(main_window: MainWindow, tmp_path: Path) -> None:
    main_window.page("photo").result_card.saved.emit(tmp_path / ("x" * 200 + ".jpg"))
    toast, root = main_window.toasts.toast, main_window.centralWidget()
    assert root.rect().contains(toast.geometry())
    main_window.resize(main_window.minimumSize())
    assert root.rect().contains(toast.geometry())


def test_title_squiggle_ripples_when_a_page_opens(qtbot, main_window: MainWindow, motion_on) -> None:
    squiggle = main_window.page("signature").header.squiggle
    main_window.show_page("signature")
    assert squiggle.is_playing
    reveal, _phase, amplitude = squiggle.wave_state()
    assert reveal < 1.0 and amplitude > squiggle.AMPLITUDE  # drawing in, livelier than at rest
    squiggle.animation.setCurrentTime(squiggle.animation.duration())
    reveal, phase, amplitude = squiggle.wave_state()
    assert reveal == 1.0 and amplitude == squiggle.AMPLITUDE
    assert abs(math.sin(phase)) < 1e-9 and abs(math.cos(phase) - 1) < 1e-9  # rests in its usual shape


def test_title_squiggle_stays_still_without_motion(main_window: MainWindow) -> None:
    main_window.show_page("pdf")
    squiggle = main_window.page("pdf").header.squiggle
    assert not squiggle.is_playing and squiggle.wave_state()[0] == 1.0
