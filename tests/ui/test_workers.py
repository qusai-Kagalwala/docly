"""Tests for background workers."""

from __future__ import annotations

import logging
import threading
import time

from docly.core.errors import CancelledError, CorruptImageError
from docly.ui.workers import GENERIC_ERROR, CancelToken, TaskRunner


def test_cancel_token() -> None:
    token = CancelToken()
    assert not token() and not token.cancelled
    token.cancel()
    assert token() and token.cancelled


def test_job_runs_off_the_ui_thread(qtbot) -> None:
    runner = TaskRunner()
    main_thread = threading.get_ident()
    with qtbot.waitSignal(runner.finished, timeout=5000) as blocker:
        runner.submit(lambda token: threading.get_ident())
    assert blocker.args[0] != main_thread
    assert not runner.busy


def test_friendly_errors_pass_through(qtbot) -> None:
    runner = TaskRunner()

    def job(token):
        raise CorruptImageError("photo.jpg is incomplete.")

    with qtbot.waitSignal(runner.failed, timeout=5000) as blocker:
        runner.submit(job)
    assert blocker.args == ["photo.jpg is incomplete."]


def test_unexpected_errors_are_logged_and_softened(qtbot, caplog) -> None:
    runner = TaskRunner()
    logging.getLogger("docly").propagate = True
    try:

        def job(token):
            raise KeyError("internal detail")

        with caplog.at_level(logging.ERROR, logger="docly"), qtbot.waitSignal(runner.failed, timeout=5000) as blocker:
            runner.submit(job)
        assert blocker.args == [GENERIC_ERROR]
        assert "internal detail" in caplog.text
    finally:
        logging.getLogger("docly").propagate = False


def test_cancel_stops_job_and_suppresses_result(qtbot) -> None:
    runner = TaskRunner()
    results: list[object] = []
    runner.finished.connect(results.append)
    started = threading.Event()

    def job(token):
        started.set()
        deadline = time.time() + 5
        while not token() and time.time() < deadline:
            time.sleep(0.01)
        raise CancelledError()

    with qtbot.waitSignal(runner.busyChanged, timeout=5000) as blocker:
        runner.submit(job)
        started.wait(5)
        runner.cancel()
    assert blocker.args == [False] or not runner.busy
    runner.wait()
    qtbot.wait(50)
    assert results == []
    assert not runner.busy


def test_newer_job_wins(qtbot) -> None:
    runner = TaskRunner()
    results: list[object] = []
    runner.finished.connect(results.append)

    def slow(token):
        time.sleep(0.3)
        return "old"

    runner.submit(slow)
    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.submit(lambda token: "new")
    runner.wait()
    qtbot.wait(100)
    assert results == ["new"]


def test_busy_changes_once_per_burst(qtbot) -> None:
    runner = TaskRunner()
    states: list[bool] = []
    runner.busyChanged.connect(states.append)
    with qtbot.waitSignal(runner.finished, timeout=5000):
        runner.submit(lambda token: time.sleep(0.1))
        runner.submit(lambda token: "done")
    runner.wait()
    qtbot.wait(50)
    assert states == [True, False]
