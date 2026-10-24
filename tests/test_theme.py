"""Tests for colour tokens, the stylesheet builder and ThemeManager."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from docly.ui.qss import build_stylesheet, mix, rgba
from docly.ui.settings_store import SettingsStore
from docly.ui.theme import COLOR_TOKENS, DARK, LIGHT, ThemeManager, ThemeMode, Tokens

HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# ----- tokens ---------------------------------------------------------
@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_every_token_is_a_hex_colour(tokens: Tokens) -> None:
    for name in COLOR_TOKENS:
        assert HEX.fullmatch(getattr(tokens, name)), name


def test_design_guide_values() -> None:
    assert (LIGHT.bg, LIGHT.accent, LIGHT.danger) == ("#F6F7F9", "#2F6FEB", "#D64545")
    assert (DARK.bg, DARK.accent, DARK.success) == ("#15171C", "#5B8DEF", "#3CC37A")


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_text_is_readable(tokens: Tokens) -> None:
    """WCAG AA (4.5:1) for body text, muted text and accent buttons."""
    assert contrast(tokens.text, tokens.bg) >= 4.5
    assert contrast(tokens.text, tokens.surface) >= 4.5
    assert contrast(tokens.text_muted, tokens.surface) >= 4.5
    assert contrast(tokens.text_muted, tokens.surface_alt) >= 4.5
    assert contrast(tokens.on_accent, tokens.accent) >= 4.5


# ----- stylesheet -----------------------------------------------------
@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_stylesheet_is_fully_filled(tokens: Tokens) -> None:
    qss = build_stylesheet(tokens)
    assert "$" not in qss
    assert tokens.bg in qss and tokens.accent in qss
    assert qss.count("{") == qss.count("}")


def test_light_and_dark_stylesheets_differ() -> None:
    assert build_stylesheet(LIGHT) != build_stylesheet(DARK)


def test_colour_helpers() -> None:
    assert rgba("#FF0080", 128) == "rgba(255, 0, 128, 128)"
    assert rgba("#000000", 999) == "rgba(0, 0, 0, 255)"
    assert mix("#000000", "#FFFFFF", 0.5) == "#808080"
    assert mix("#123456", "#ABCDEF", 0.0) == "#123456"


def test_no_hardcoded_colours_in_widgets() -> None:
    """Colours belong in theme.py only (icons use 'currentColor')."""
    ui_dir = Path(__file__).resolve().parent.parent / "docly" / "ui"
    offenders = []
    for path in ui_dir.rglob("*.py"):
        if path.name == "theme.py":
            continue
        if HEX.search(path.read_text(encoding="utf-8").replace('"#{', "")):
            offenders.append(path.name)
    assert offenders == []


# ----- ThemeManager ---------------------------------------------------
def test_defaults_to_system_mode(theme_manager: ThemeManager) -> None:
    assert theme_manager.mode == ThemeMode.SYSTEM
    assert theme_manager.tokens == LIGHT  # fixture's "Windows" is light


def test_system_mode_follows_windows_dark(qapp, settings_store: SettingsStore, monkeypatch) -> None:
    monkeypatch.setattr(ThemeManager, "_system_scheme", lambda self: Qt.ColorScheme.Dark)
    manager = ThemeManager(qapp, settings_store)
    assert manager.is_dark


def test_live_windows_change_is_followed(theme_manager: ThemeManager, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(ThemeManager, "_system_scheme", lambda self: Qt.ColorScheme.Dark)
    with qtbot.waitSignal(theme_manager.themeChanged, timeout=1000) as blocker:
        theme_manager._on_system_scheme_changed()
    assert blocker.args == [DARK]


def test_manual_mode_ignores_windows_change(theme_manager: ThemeManager, monkeypatch) -> None:
    theme_manager.set_mode(ThemeMode.LIGHT)
    monkeypatch.setattr(ThemeManager, "_system_scheme", lambda self: Qt.ColorScheme.Dark)
    theme_manager._on_system_scheme_changed()
    assert not theme_manager.is_dark


def test_set_mode_applies_stylesheet(theme_manager: ThemeManager, qapp) -> None:
    theme_manager.set_mode(ThemeMode.DARK)
    assert theme_manager.is_dark
    assert DARK.bg in qapp.styleSheet()
    theme_manager.set_mode("light")
    assert LIGHT.bg in qapp.styleSheet()


def test_toggle_switches_and_emits(theme_manager: ThemeManager, qtbot) -> None:
    with qtbot.waitSignals([theme_manager.themeChanged, theme_manager.modeChanged], timeout=1000):
        theme_manager.toggle()
    assert theme_manager.mode == ThemeMode.DARK
    theme_manager.toggle()
    assert theme_manager.mode == ThemeMode.LIGHT


def test_choice_persists(qapp, theme_manager: ThemeManager, app_data: Path) -> None:
    theme_manager.set_mode(ThemeMode.DARK)
    reopened = ThemeManager(qapp, SettingsStore(app_data / "settings.ini"))
    assert reopened.mode == ThemeMode.DARK


def test_corrupt_setting_falls_back_to_system(qapp, app_data: Path) -> None:
    settings_file = app_data / "settings.ini"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("[appearance]\ntheme=purple\n", encoding="utf-8")
    store = SettingsStore(settings_file)
    assert store.theme_mode() == "system"
