"""Shared pytest fixtures.

Qt runs "offscreen" so tests never open real windows, and every test gets
its own temporary AppData folder so your real settings and logs are never
touched.
"""

from __future__ import annotations

import os

# Must be set before any Qt module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from docly import config  # noqa: E402
from docly.ui.main_window import MainWindow  # noqa: E402
from docly.ui.settings_store import SettingsStore  # noqa: E402
from docly.ui.theme import ThemeManager  # noqa: E402


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
