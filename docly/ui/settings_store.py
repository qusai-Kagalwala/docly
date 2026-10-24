"""Tiny wrapper around QSettings for the few things Docly remembers.

Settings live in an INI file in AppData (not the Windows registry) so they
are easy to inspect, back up or delete. Phase 10.2 adds more keys.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from docly import config
from docly.logger import get_logger
from docly.ui.theme import ThemeMode

log = get_logger(__name__)

KEY_THEME = "appearance/theme"


class SettingsStore:
    """Reads and writes user settings, always falling back to safe defaults."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config.settings_path()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # QSettings still works in memory; changes just won't persist.
            log.warning("Settings folder unavailable (%s): %s", self.path.parent, exc)
        self._settings = QSettings(str(self.path), QSettings.Format.IniFormat)

    def theme_mode(self) -> str:
        """Saved theme choice; anything unexpected becomes ``"system"``."""
        value = self._settings.value(KEY_THEME, ThemeMode.SYSTEM.value)
        allowed = {mode.value for mode in ThemeMode}
        if not isinstance(value, str) or value not in allowed:
            log.warning("Ignoring invalid theme setting: %r", value)
            return ThemeMode.SYSTEM.value
        return value

    def set_theme_mode(self, mode: str) -> None:
        """Save the theme choice (``system``, ``light`` or ``dark``)."""
        self._settings.setValue(KEY_THEME, ThemeMode(mode).value)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            log.warning("Could not save settings to %s", self.path)
