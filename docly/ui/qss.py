"""Builds the app-wide Qt Style Sheet (QSS) from colour tokens.

QSS is Qt's version of CSS. Widgets opt into styles with an
``objectName`` (``#Card``) or a dynamic property (``[variant="primary"]``),
so no widget needs to know any colour.
"""

from __future__ import annotations

from string import Template

from docly.ui.theme import SIDEBAR_ALPHA, Tokens


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgba(hex_color: str, alpha: int) -> str:
    """``#RRGGBB`` + alpha (0-255) -> ``rgba(r, g, b, a)`` for QSS."""
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {max(0, min(255, alpha))})"


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Blend ``amount`` (0-1) of ``color_b`` into ``color_a``; returns hex."""
    ra, ga, ba = _rgb(color_a)
    rb, gb, bb = _rgb(color_b)
    t = max(0.0, min(1.0, amount))
    r = round(ra + (rb - ra) * t)
    g = round(ga + (gb - ga) * t)
    b = round(ba + (bb - ba) * t)
    return f"#{r:02X}{g:02X}{b:02X}"


def derived_colors(t: Tokens) -> dict[str, str]:
    """Extra shades computed from the base tokens (tints, hovers, chips)."""
    dark = t.is_dark
    # Status colours are tuned for icons; as small text on a light tint
    # they need darkening to stay readable.
    def chip_text(color: str) -> str:
        return color if dark else mix(color, t.text, 0.35)

    return {
        "sidebar_bg": rgba(t.surface_alt, SIDEBAR_ALPHA),
        "hover_tint": rgba(t.text, 16 if dark else 10),
        "pressed_tint": rgba(t.text, 26 if dark else 18),
        "border_hover": mix(t.border, t.text, 0.22 if dark else 0.18),
        "accent_tint": rgba(t.accent, 46 if dark else 30),
        "accent_pressed": mix(t.accent, t.text, 0.18),
        "focus_ring": rgba(t.accent, 160),
        "scroll_handle": rgba(t.text, 60 if dark else 45),
        "scroll_handle_hover": rgba(t.text, 100 if dark else 80),
        "success_tint": rgba(t.success, 40 if dark else 28),
        "warning_tint": rgba(t.warning, 40 if dark else 30),
        "danger_tint": rgba(t.danger, 40 if dark else 26),
        "success_text": chip_text(t.success),
        "warning_text": chip_text(t.warning),
        "danger_text": chip_text(t.danger),
        "accent_text": t.accent if dark else mix(t.accent, t.text, 0.15),
    }


_TEMPLATE = Template(
    """
/* ---------- base ---------- */
QWidget {
    color: $text;
}
QMainWindow, #AppRoot, QStackedWidget#PageStack {
    background: $bg;
}
QScrollArea, QScrollArea > QWidget > QWidget#PageBody {
    background: transparent;
    border: none;
}
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 4px 8px;
}

/* ---------- sidebar ---------- */
#Sidebar {
    background: $sidebar_bg;
    border: none;
    border-right: 1px solid $border;
}
QLabel#SidebarBrand {
    font-size: 16px;
    font-weight: 600;
}
QFrame#SidebarDivider {
    background: $border;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

/* ---------- text roles ---------- */
QLabel[role="title"] {
    font-size: 20px;
    font-weight: 600;
}
QLabel[role="section"] {
    font-size: 14px;
    font-weight: 600;
}
QLabel[role="body"] {
    font-size: 13px;
}
QLabel[role="muted"] {
    color: $text_muted;
    font-size: 13px;
}
QLabel[role="caption"] {
    color: $text_muted;
    font-size: 12px;
}
/* ---------- cards & dialogs ---------- */
QFrame#Card {
    background: $surface;
    border: 1px solid $border;
    border-radius: 10px;
}
QDialog {
    background: $bg;
}

/* ---------- chips ---------- */
QLabel[chip] {
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 600;
}
QLabel[chip="neutral"] { background: $accent_tint; color: $accent_text; }
QLabel[chip="success"] { background: $success_tint; color: $success_text; }
QLabel[chip="warning"] { background: $warning_tint; color: $warning_text; }
QLabel[chip="danger"]  { background: $danger_tint;  color: $danger_text; }

/* ---------- buttons ---------- */
QPushButton {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 7px 16px;
    min-height: 20px;
    font-size: 13px;
}
QPushButton:hover {
    background: $hover_tint;
    border-color: $border_hover;
}
QPushButton:pressed {
    background: $pressed_tint;
}
QPushButton:focus {
    border-color: $focus_ring;
}
QPushButton:disabled {
    color: $text_muted;
    background: $surface_alt;
    border-color: $border;
}
QPushButton[variant="primary"] {
    background: $accent;
    color: $on_accent;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: $accent_hover;
    border-color: $accent_hover;
}
QPushButton[variant="primary"]:pressed {
    background: $accent_pressed;
    border-color: $accent_pressed;
}
QPushButton[variant="primary"]:focus {
    border-color: $accent_pressed;
}

/* segmented control (e.g. System / Light / Dark) */
QFrame#Segmented {
    background: $surface_alt;
    border: 1px solid $border;
    border-radius: 8px;
}
QPushButton[segment="true"] {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 14px;
    color: $text_muted;
}
QPushButton[segment="true"]:hover {
    color: $text;
    background: $hover_tint;
}
QPushButton[segment="true"]:checked {
    background: $surface;
    color: $text;
    border-color: $border;
    font-weight: 600;
}
QPushButton[segment="true"]:focus {
    border-color: $focus_ring;
}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: $border_hover;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $accent;
}
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    selection-background-color: $accent_tint;
    selection-color: $text;
    outline: none;
}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $scroll_handle;
    border-radius: 3px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: $scroll_handle_hover;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
    width: 0;
    height: 0;
}

/* ---------- message boxes ---------- */
QMessageBox {
    background: $surface;
}
QMessageBox QLabel {
    font-size: 13px;
}
"""
)


def build_stylesheet(t: Tokens) -> str:
    """Return the full QSS for one palette."""
    values: dict[str, str] = {name: getattr(t, name) for name in t.__dataclass_fields__ if name != "name"}
    values.update(derived_colors(t))
    return _TEMPLATE.substitute(values)
