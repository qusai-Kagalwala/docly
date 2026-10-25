"""Tiny wrapper around QSettings for the few things Docly remembers.

Settings live in an INI file in AppData (not the Windows registry) so they
are easy to inspect, back up or delete.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from docly import config
from docly.logger import get_logger
from docly.ui.theme import ThemeMode

log = get_logger(__name__)

KEY_THEME = "appearance/theme"
KEY_TOUR_SEEN = "onboarding/tour_seen"
KEY_OUTPUT_FOLDER = "output/folder"  # empty = next to the original
KEY_REMEMBER_PRESETS = "presets/remember"
KEY_LAST_PRESET = "presets/last/"  # + picker key, e.g. "photo/0"
KEY_REDUCE_MOTION = "appearance/reduce_motion"


def _as_bool(value: object, default: bool) -> bool:
    """QSettings hands back INI values as strings ("true"/"false")."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return default


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

    def tour_seen(self) -> bool:
        """True once the first-run tour was finished or skipped."""
        return _as_bool(self._settings.value(KEY_TOUR_SEEN, False), False)

    def set_tour_seen(self, seen: bool = True) -> None:
        self._set(KEY_TOUR_SEEN, "true" if seen else "false")

    # ----- output folder ------------------------------------------------
    def output_folder(self) -> Path | None:
        """The folder chosen in Settings, or None for "next to the original"."""
        value = self._settings.value(KEY_OUTPUT_FOLDER, "")
        if not isinstance(value, str) or not value.strip():
            return None
        return Path(value)

    def set_output_folder(self, folder: Path | None) -> None:
        self._set(KEY_OUTPUT_FOLDER, str(folder) if folder is not None else "")

    # ----- presets ---------------------------------------------------------
    def remember_presets(self) -> bool:
        return _as_bool(self._settings.value(KEY_REMEMBER_PRESETS, True), True)

    def set_remember_presets(self, remember: bool) -> None:
        self._set(KEY_REMEMBER_PRESETS, "true" if remember else "false")

    def last_preset(self, picker: str) -> str | None:
        value = self._settings.value(KEY_LAST_PRESET + picker, "")
        return value if isinstance(value, str) and value else None

    def set_last_preset(self, picker: str, preset_id: str) -> None:
        self._set(KEY_LAST_PRESET + picker, preset_id)

    # ----- motion ---------------------------------------------------------
    def reduce_motion(self) -> bool:
        return _as_bool(self._settings.value(KEY_REDUCE_MOTION, False), False)

    def set_reduce_motion(self, reduce: bool) -> None:
        self._set(KEY_REDUCE_MOTION, "true" if reduce else "false")

    def _set(self, key: str, value: str) -> None:
        self._settings.setValue(key, value)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            log.warning("Could not save settings to %s", self.path)
