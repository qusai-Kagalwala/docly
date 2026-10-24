"""App-wide constants and paths.

This module must stay free of Qt imports so that ``core/`` code and tests
can use it without a GUI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from docly import __version__

APP_NAME = "Docly"
APP_ID = "QusaiKagalwala.Docly"  # Windows AppUserModelID (taskbar grouping)
ORG_NAME = "Qusai Kagalwala"
APP_TAGLINE = "Get your documents upload-ready."
APP_VERSION = __version__
APP_LICENSE = "MIT"
REPO_URL = "https://github.com/qusai-Kagalwala/docly"

WINDOW_MIN_SIZE: tuple[int, int] = (1000, 650)
WINDOW_DEFAULT_SIZE: tuple[int, int] = (1180, 760)
SIDEBAR_WIDTH = 210

# Set this environment variable to keep all app data somewhere else
# (used by the tests; also handy for a portable build later).
DATA_DIR_ENV = "DOCLY_DATA_DIR"


def _base_dir() -> Path:
    """Return the folder that contains ``assets/``.

    When frozen by PyInstaller, bundled files are unpacked to
    ``sys._MEIPASS``; otherwise it is the repository root.
    """
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
ASSETS_DIR = BASE_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
BUNDLED_PRESETS_PATH = BASE_DIR / "docly" / "presets" / "presets.json"


def app_data_dir() -> Path:
    """Folder for logs and settings: ``%LOCALAPPDATA%\\Docly`` on Windows."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    # Fallback for running from source on non-Windows machines.
    return Path.home() / ".docly"


def log_dir() -> Path:
    """Folder that holds the rotating log files."""
    return app_data_dir() / "logs"


def settings_path() -> Path:
    """Path of the INI file that stores user settings."""
    return app_data_dir() / "settings.ini"


def user_presets_path() -> Path:
    """Optional user presets file that adds to / replaces built-in presets.

    It lives in AppData because the install folder is read-only, so users can
    fix a spec the day a notification changes, without a new release.
    """
    return app_data_dir() / "presets.json"
