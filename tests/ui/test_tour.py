"""Tests for the guided tour."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QLabel, QWidget

from docly.ui.main_window import MainWindow
from docly.ui.settings_store import SettingsStore
from docly.ui.tour import TourOverlay, TourStep


def test_first_launch_starts_once(main_window: MainWindow, qtbot, app_data) -> None:
    assert main_window.maybe_start_tour()
    tour = main_window.tour
    with qtbot.waitSignal(tour.finished) as blocker:
        tour.skip()
    assert blocker.args == [False]
    assert SettingsStore(app_data / "settings.ini").tour_seen()
    assert not main_window.maybe_start_tour()  # never again on its own
    assert main_window.start_tour() is not None  # but always on request
    main_window.tour.skip()


def test_walks_through_every_step(main_window: MainWindow, qtbot) -> None:
    tour = main_window.start_tour()
    steps = len(tour.steps)
    assert steps == 7
    pages = []
    for index in range(steps):
        assert tour.bubble.counter.text() == f"Step {index + 1} of {steps}"
        qtbot.wait(5)
        assert not tour.spot.isNull(), tour.steps[index].title  # every step points at something
        bubble = QRect(tour.bubble.pos(), tour.bubble.size())
        assert tour.rect().contains(bubble)  # bubble fully inside the window
        assert not bubble.intersects(tour.spot) or tour.spot.width() > tour.width() // 2
        pages.append(main_window.current_page_id())
        if index < steps - 1:
            tour.next()
    assert "photo" in pages and "pdf" in pages
    assert tour.bubble.next_button.text() == "Done"
    with qtbot.waitSignal(tour.finished) as blocker:
        tour.next()
    assert blocker.args == [True]
    assert main_window.tour is None
    assert main_window.current_page_id() == "home"


def test_back_and_keys(main_window: MainWindow, qtbot) -> None:
    tour = main_window.start_tour()
    assert not tour.bubble.back_button.isEnabled()
    qtbot.keyClick(tour, Qt.Key.Key_Right)
    assert tour.index == 1
    qtbot.keyClick(tour, Qt.Key.Key_Left)
    assert tour.index == 0
    with qtbot.waitSignal(tour.finished):
        qtbot.keyClick(tour, Qt.Key.Key_Escape)


def test_follows_window_resizes(main_window: MainWindow, qtbot) -> None:
    tour = main_window.start_tour()
    main_window.resize(1000, 650)
    qtbot.wait(20)
    assert tour.geometry() == main_window.centralWidget().rect()
    bubble = QRect(tour.bubble.pos(), tour.bubble.size())
    assert tour.rect().contains(bubble)
    tour.skip()


def test_clicks_do_not_reach_the_app(main_window: MainWindow, qtbot) -> None:
    tour = main_window.start_tour()
    qtbot.mouseClick(tour, Qt.MouseButton.LeftButton, pos=tour.rect().center())
    assert tour.isVisible() and tour.index == 0
    tour.skip()


def test_about_dialog_starts_tour(main_window: MainWindow, qtbot) -> None:
    dialog = main_window.show_about()
    qtbot.mouseClick(dialog.tour_button, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    assert main_window.tour is not None
    main_window.tour.skip()


def test_starting_again_replaces_running_tour(main_window: MainWindow) -> None:
    first = main_window.start_tour()
    second = main_window.start_tour()
    assert first is not second and not first.isVisible()
    second.skip()


def test_hidden_target_centres_bubble(qtbot, theme_manager) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    host.show()
    hidden = QLabel("x", host)
    hidden.hide()
    tour = TourOverlay(host, [TourStep("Title", "Text", lambda: [hidden])], theme_manager)
    tour.start()
    assert tour.spot.isNull()
    assert abs(tour.bubble.geometry().center().x() - host.rect().center().x()) <= 2
    assert tour.bubble.next_button.text() == "Done"
    tour.skip()


def test_settings_flag_round_trip(settings_store: SettingsStore) -> None:
    assert not settings_store.tour_seen()
    settings_store.set_tour_seen(True)
    assert settings_store.tour_seen()
    settings_store.set_tour_seen(False)
    assert not settings_store.tour_seen()
