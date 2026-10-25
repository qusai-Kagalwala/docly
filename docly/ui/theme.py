"""Colour tokens and the theme manager.

Every colour in the app comes from a :class:`Tokens` instance. Widgets never
hard-code colours: QSS is built from tokens (see ``qss.py``) and
custom-painted widgets listen to :attr:`ThemeManager.themeChanged`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from docly.logger import get_logger

if TYPE_CHECKING:
    from docly.ui.settings_store import SettingsStore

log = get_logger(__name__)


class ThemeMode(str, Enum):
    """What the user picked. ``SYSTEM`` follows Windows' setting."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class Tokens:
    """One complete colour palette (values are ``#RRGGBB``)."""

    name: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    on_accent: str  # text/icons drawn on an accent fill
    success: str
    warning: str
    danger: str
    shadow: str  # card shadow colour (used with low opacity)

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def qcolor(self, token: str, alpha: int = 255) -> QColor:
        """Return a token as a ``QColor`` with an optional alpha (0-255)."""
        color = QColor(getattr(self, token))
        color.setAlpha(alpha)
        return color


#: Names of the colour fields (everything except ``name``).
COLOR_TOKENS: tuple[str, ...] = tuple(f.name for f in fields(Tokens) if f.name != "name")

LIGHT = Tokens(
    name="light",
    bg="#F6F7F9",
    surface="#FFFFFF",
    surface_alt="#EEF0F4",
    border="#E2E5EB",
    text="#1B1F27",
    text_muted="#5F6775",
    accent="#2F6FEB",
    accent_hover="#2560D6",
    on_accent="#FFFFFF",
    success="#1F9D55",
    warning="#C98A0E",
    danger="#D64545",
    shadow="#101828",
)

DARK = Tokens(
    name="dark",
    bg="#15171C",
    surface="#1E2128",
    surface_alt="#1A1D23",
    border="#2C3038",
    text="#E8EAEE",
    text_muted="#9AA1AD",
    accent="#5B8DEF",
    accent_hover="#7AA3F2",
    # White on #5B8DEF is only 3.2:1, below the WCAG 4.5:1 minimum,
    # so dark-theme accent buttons use near-black text (5.9:1).
    on_accent="#0E1116",
    success="#3CC37A",
    warning="#E3A93A",
    danger="#EF6B6B",
    shadow="#000000",
)

SIDEBAR_ALPHA = 235  # ~92 % opaque: the "slightly translucent" sidebar


def tokens_for(dark: bool) -> Tokens:
    """Return the dark or light palette."""
    return DARK if dark else LIGHT


def build_palette(t: Tokens) -> QPalette:
    """A QPalette matching the tokens, for anything QSS doesn't reach."""
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(t.bg))
    p.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    p.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface_alt))
    p.setColor(QPalette.ColorRole.Text, QColor(t.text))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_muted))
    p.setColor(QPalette.ColorRole.Button, QColor(t.surface))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    p.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_accent))
    p.setColor(QPalette.ColorRole.Link, QColor(t.accent))
    p.setColor(QPalette.ColorRole.Mid, QColor(t.border))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.text_muted))
    return p


class ThemeManager(QObject):
    """Owns the current theme, applies it app-wide and remembers the choice.

    Signals:
        themeChanged(Tokens): the effective palette changed.
        modeChanged(str): the user's choice changed (a ``ThemeMode`` value).
    """

    themeChanged = Signal(object)
    modeChanged = Signal(str)

    def __init__(self, app: QApplication, store: SettingsStore) -> None:
        super().__init__()
        self._app = app
        self._store = store
        self._mode = ThemeMode(store.theme_mode())
        self._tokens: Tokens = LIGHT
        self._applying = False
        app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        self.apply(force=True)

    # ----- public API -------------------------------------------------
    @property
    def store(self) -> SettingsStore:
        """The settings file this manager saves to (shared with other UI)."""
        return self._store

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def tokens(self) -> Tokens:
        return self._tokens

    @property
    def is_dark(self) -> bool:
        return self._tokens.is_dark

    def set_mode(self, mode: ThemeMode | str) -> None:
        """Switch to System / Light / Dark, save it, and restyle the app."""
        mode = ThemeMode(mode)
        if mode == self._mode:
            return
        self._mode = mode
        self._store.set_theme_mode(mode.value)
        log.info("Theme mode set to %s", mode.value)
        self.modeChanged.emit(mode.value)
        self.apply()

    def toggle(self) -> None:
        """Flip between light and dark (leaves "System" mode)."""
        self.set_mode(ThemeMode.LIGHT if self.is_dark else ThemeMode.DARK)

    def apply(self, force: bool = False) -> None:
        """Resolve the mode to a palette and apply it to the whole app."""
        if self._applying:
            return
        self._applying = True
        try:
            self._sync_qt_color_scheme()
            new_tokens = tokens_for(self._resolve_dark())
            if not force and new_tokens == self._tokens:
                return
            self._tokens = new_tokens
            # Imported here to avoid a circular import (qss uses Tokens).
            from docly.ui.icons import export_icon_svg
            from docly.ui.qss import build_stylesheet

            down = export_icon_svg("chevron-down", new_tokens.text_muted)
            up = export_icon_svg("chevron-up", new_tokens.text_muted)
            # QSS wants forward slashes
            self._app.setPalette(build_palette(new_tokens))
            self._app.setStyleSheet(
                build_stylesheet(new_tokens, down.as_posix() if down else None, up.as_posix() if up else None)
            )
            log.debug("Applied %s theme", new_tokens.name)
            self.themeChanged.emit(new_tokens)
        finally:
            self._applying = False

    # ----- internals --------------------------------------------------
    def _system_scheme(self) -> Qt.ColorScheme:
        """Windows' current light/dark setting (``Unknown`` if not reported)."""
        return self._app.styleHints().colorScheme()

    def _resolve_dark(self) -> bool:
        if self._mode == ThemeMode.DARK:
            return True
        if self._mode == ThemeMode.LIGHT:
            return False
        return self._system_scheme() == Qt.ColorScheme.Dark

    def _sync_qt_color_scheme(self) -> None:
        """Tell Qt about a manual choice so native parts (e.g. the Windows
        title bar) match. ``Unknown`` hands control back to the system."""
        hints = self._app.styleHints()
        if not hasattr(hints, "setColorScheme"):  # Qt < 6.8
            return
        wanted = {
            ThemeMode.DARK: Qt.ColorScheme.Dark,
            ThemeMode.LIGHT: Qt.ColorScheme.Light,
            ThemeMode.SYSTEM: Qt.ColorScheme.Unknown,
        }[self._mode]
        try:
            hints.setColorScheme(wanted)
        except Exception:  # pragma: no cover - platform specific
            log.exception("Could not set Qt colour scheme")

    def _on_system_scheme_changed(self, *_args: object) -> None:
        if self._mode == ThemeMode.SYSTEM:
            log.info("Windows colour scheme changed; following it")
            self.apply()
