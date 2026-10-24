"""Tests for app bootstrap helpers: font and crash handling."""

from __future__ import annotations

import logging
import sys

import pytest

from docly.ui import app as docly_app


def _raise_and_capture() -> tuple:
    try:
        raise ValueError("boom")
    except ValueError:
        return sys.exc_info()


def test_font_prefers_segoe(qapp) -> None:
    font = docly_app.build_app_font()
    assert font.families()[:2] == ["Segoe UI Variable Text", "Segoe UI"]
    assert font.pixelSize() == 13


def test_exception_hook_logs_and_shows_dialog(qapp, monkeypatch, caplog) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        docly_app.QMessageBox,
        "critical",
        lambda parent, title, text: shown.append(text),
    )
    logging.getLogger("docly").propagate = True  # let caplog see it
    hook = docly_app.make_exception_hook()
    with caplog.at_level(logging.CRITICAL, logger="docly"):
        hook(*_raise_and_capture())
    assert "Unhandled exception" in caplog.text
    assert "boom" in caplog.text
    assert len(shown) == 1 and "Your files were not changed" in shown[0]


def test_exception_hook_survives_dialog_failure(qapp, monkeypatch) -> None:
    def broken(*_args):
        raise RuntimeError("dialog failed")

    monkeypatch.setattr(docly_app.QMessageBox, "critical", broken)
    hook = docly_app.make_exception_hook()
    hook(*_raise_and_capture())  # must not raise


def test_keyboard_interrupt_goes_to_default_hook(monkeypatch) -> None:
    calls: list[type] = []
    monkeypatch.setattr(sys, "__excepthook__", lambda t, e, tb: calls.append(t))
    hook = docly_app.make_exception_hook()
    hook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert calls == [KeyboardInterrupt]


@pytest.fixture(autouse=True)
def _restore_logger_propagation():
    yield
    logging.getLogger("docly").propagate = False
