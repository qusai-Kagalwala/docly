"""Shared pytest fixtures.

Qt runs "offscreen" so tests never open real windows, and every test gets
its own temporary AppData folder so your real settings and logs are never
touched.
"""

from __future__ import annotations

import gc
import os

# Must be set before any Qt module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Animations finish instantly in tests (motion tests turn them back on).
os.environ.setdefault("DOCLY_REDUCE_MOTION", "1")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from docly import config  # noqa: E402
from docly.ui.main_window import MainWindow  # noqa: E402
from docly.ui.settings_store import SettingsStore  # noqa: E402
from docly.ui.theme import ThemeManager  # noqa: E402


@pytest.fixture(autouse=True)
def _delete_closed_widgets(request: pytest.FixtureRequest):
    """Really delete widgets closed by a test before the next one starts.

    pytest-qt closes test widgets with ``deleteLater()``, which only runs
    when the event loop does. Without this, old windows pile up and every
    theme change restyles all of them, making later tests much slower.
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent

    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()


@pytest.fixture(autouse=True)
def app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Docly's AppData folder at a fresh temp dir for every test."""
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv(config.DATA_DIR_ENV, str(data_dir))
    return data_dir


@pytest.fixture
def settings_store(app_data: Path) -> SettingsStore:
    return SettingsStore(app_data / "settings.ini")


@pytest.fixture
def theme_manager(qapp, settings_store: SettingsStore, monkeypatch: pytest.MonkeyPatch) -> ThemeManager:
    """A ThemeManager whose "Windows setting" is light unless a test changes it."""
    monkeypatch.setattr(ThemeManager, "_system_scheme", lambda self: Qt.ColorScheme.Light)
    return ThemeManager(qapp, settings_store)


@pytest.fixture
def main_window(qtbot, theme_manager: ThemeManager) -> MainWindow:
    window = MainWindow(theme_manager)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


# ----------------------------------------------------------------------
# Quick mode:  pytest -m "not slow"   (everyday runs, about a third of the time)
#              pytest                 (everything; run this before pushing)
# ----------------------------------------------------------------------
#: Test files that process real images/PDFs end to end or run the AI model.
SLOW_MODULES = frozenset(
    {
        "test_pipeline", "test_pdf_compress", "test_background", "test_signature", "test_compress",
        "test_photo_page", "test_signature_page", "test_pdf_page", "test_sign_page",
        "test_batch", "test_batch_page", "test_pdf_fill_render",
    }
)  # fmt: skip


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    slow = pytest.mark.slow
    for item in items:
        if item.module is not None and item.module.__name__.rsplit(".", 1)[-1] in SLOW_MODULES:
            item.add_marker(slow)
