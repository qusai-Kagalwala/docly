"""Builds the app-wide Qt Style Sheet (QSS) from colour tokens.

QSS is Qt's version of CSS. Widgets opt into styles with an
``objectName`` (``#Card``) or a dynamic property (``[variant="primary"]``),
so no widget needs to know any colour.
"""

from __future__ import annotations

from collections.abc import Mapping
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
QFrame#NavIndicator {
    background: $accent;
    border-radius: 1px;
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
QDialog#ColourPopover { background: transparent; }
QFrame#PopoverFrame {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
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
QPushButton[variant="primary"]:disabled {
    background: $surface_alt;
    color: $text_muted;
    border-color: $border;
    font-weight: 600;
}
QPushButton[variant="primary"]:focus {
    border-color: $accent_pressed;
}
QPushButton[variant="ghost"] {
    background: transparent;
    border-color: transparent;
    color: $text_muted;
}
QPushButton[variant="ghost"]:hover {
    background: $hover_tint;
    color: $text;
}

/* ---------- tables (Batch) ---------- */
QTableView {
    background: $surface;
    alternate-background-color: $surface_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    gridline-color: $border;
    selection-background-color: $accent_tint;
    selection-color: $text;
}
QHeaderView::section {
    background: $surface_alt;
    color: $text_muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 8px;
    font-weight: 600;
}

/* ---------- home page & tour ---------- */
QFrame#Toast {
    background: $surface;
    border: 1px solid $border_hover;
    border-radius: 12px;
}
QFrame#Toast QLabel#ToastText { font-size: 13px; background: transparent; }
QFrame#Toast QPushButton { padding: 4px 10px; min-height: 0; }
QFrame#TourBubble {
    background: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#Card[feature="true"]:hover {
    border-color: $accent;
}
QLabel#StepNumber {
    background: $accent_tint;
    color: $accent_text;
    border-radius: 14px;
    font-weight: 700;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}
QLabel#HeroTitle {
    font-size: 22px;
    font-weight: 600;
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
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 22px;
    selection-background-color: $accent;
    selection-color: $on_accent;
}
QPlainTextEdit {
    padding: 4px 6px;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {
    border-color: $border_hover;
}
/* Focus: a 2px ring in the accent; padding shrinks by 1px so text doesn't jump. */
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 2px solid $focus_ring;
    padding: 5px 9px;
}
QPlainTextEdit:focus { padding: 3px 5px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled {
    background: $surface_alt;
    color: $text_muted;
}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {
    border: 2px solid $danger;
    padding: 5px 9px;
}
QLineEdit#SearchField { border-radius: 18px; padding-left: 4px; }
QLineEdit#SearchField:focus { padding-left: 3px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
}
QComboBox::down-arrow {
    $combo_arrow
    width: 14px;
    height: 14px;
}
QComboBox::down-arrow:on { top: 1px; }
/* Number boxes: [-]  value  [+] */
QSpinBox, QDoubleSpinBox {
    padding: 6px 30px;
    qproperty-alignment: AlignCenter;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid $focus_ring;
    padding: 5px 29px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 26px;
    height: 26px;
    border: none;
    border-radius: 6px;
    background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: center right; right: 4px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: center left; left: 4px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: $hover_tint;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background: $pressed_tint;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    $spin_up_arrow
    width: 14px;
    height: 14px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    $spin_down_arrow
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView {
    background: $surface;
    border: 1px solid $border;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $accent_tint;
    selection-color: $text;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 0 8px;
    border-radius: 6px;
}
QComboBox QAbstractItemView::item:hover {
    background: $hover_tint;
}
QComboBox QAbstractItemView::item:selected {
    background: $accent_tint;
    color: $text;
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

/* ---------- drop zone ---------- */
QFrame#DropZone {
    background: $surface;
    border: 2px dashed $border_hover;
    border-radius: 10px;
}
QFrame#DropZone:hover {
    border-color: $accent;
}
QFrame#DropZone[active="true"] {
    background: $accent_tint;
    border-color: $accent;
}

/* ---------- banners (inline messages) ---------- */
QLabel[banner] {
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}
QLabel[banner="danger"]  { background: $danger_tint;  color: $danger_text; }
QLabel[banner="warning"] { background: $warning_tint; color: $warning_text; }
QLabel[banner="info"]    { background: $accent_tint;  color: $accent_text; }
QFrame#Banner {
    border-radius: 8px;
    border: 1px solid transparent;
}
QFrame#Banner QLabel#BannerText { font-size: 13px; background: transparent; }
QFrame#Banner[kind="danger"]  { background: $danger_tint;  border-color: $danger_tint; }
QFrame#Banner[kind="danger"] QLabel#BannerText  { color: $danger_text; }
QFrame#Banner[kind="warning"] { background: $warning_tint; border-color: $warning_tint; }
QFrame#Banner[kind="warning"] QLabel#BannerText { color: $warning_text; }
QFrame#Banner[kind="info"]    { background: $accent_tint;  border-color: $accent_tint; }
QFrame#Banner[kind="info"] QLabel#BannerText    { color: $accent_text; }
QFrame#Banner[kind="success"] { background: $success_tint; border-color: $success_tint; }
QFrame#Banner[kind="success"] QLabel#BannerText { color: $success_text; }

QLabel[tone="danger"]  { color: $danger_text; }
QLabel[tone="warning"] { color: $warning_text; }
QLabel#StatusIcon { border-radius: 12px; background: $surface_alt; }
QLabel#StatusIcon[kind="success"] { background: $success_tint; }
QLabel#StatusIcon[kind="warning"] { background: $warning_tint; }
QLabel#StatusIcon[kind="danger"]  { background: $danger_tint; }
QLabel#StatusIcon[kind="info"], QLabel#StatusIcon[kind="neutral"] { background: $accent_tint; }

/* ---------- status capsules (icon + word) ---------- */
QFrame#StatusBadge {
    border-radius: 10px;
    min-height: 20px;
}
QFrame#StatusBadge QLabel { background: transparent; }
QLabel#StatusBadgeText { font-size: 12px; font-weight: 600; }
QFrame#StatusBadge[kind="success"] { background: $success_tint; }
QFrame#StatusBadge[kind="success"] QLabel#StatusBadgeText { color: $success_text; }
QFrame#StatusBadge[kind="warning"] { background: $warning_tint; }
QFrame#StatusBadge[kind="warning"] QLabel#StatusBadgeText { color: $warning_text; }
QFrame#StatusBadge[kind="danger"]  { background: $danger_tint; }
QFrame#StatusBadge[kind="danger"] QLabel#StatusBadgeText  { color: $danger_text; }
QFrame#StatusBadge[kind="neutral"], QFrame#StatusBadge[kind="info"] { background: $accent_tint; }
QFrame#StatusBadge[kind="neutral"] QLabel#StatusBadgeText,
QFrame#StatusBadge[kind="info"] QLabel#StatusBadgeText { color: $accent_text; }

/* ---------- result status ---------- */
QLabel#StatusTitle {
    font-size: 16px;
    font-weight: 600;
}
QLabel#StatusTitle[state="pass"] { color: $success_text; }
QLabel#StatusTitle[state="fail"] { color: $danger_text; }
QLabel#StatusTitle[state="warn"] { color: $warning_text; }
QFrame#OutputPreview {
    background: $surface_alt;
    border: 1px solid $border;
    border-radius: 8px;
}

/* ---------- sliders ---------- */
QSlider::groove:horizontal {
    background: $surface_alt;
    border: 1px solid $border;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: $surface;
    border: 2px solid $accent;
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: $accent_tint;
}
QSlider:focus {
    outline: none;
}

/* ---------- check boxes ---------- */
QCheckBox {
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid $border_hover;
    border-radius: 5px;
    background: $surface;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked {
    background: $accent;
    border-color: $accent;
    $check_mark
}
QCheckBox::indicator:disabled { background: $surface_alt; border-color: $border; }
QCheckBox:focus { outline: none; }

/* ---------- progress ---------- */
QProgressBar {
    background: $surface_alt;
    border: none;
    border-radius: 2px;
    max-height: 4px;
    min-height: 4px;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 2px;
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


def build_stylesheet(
    t: Tokens,
    combo_arrow: str | None = None,
    up_arrow: str | None = None,
    icons: Mapping[str, str | None] | None = None,
) -> str:
    """Return the full QSS for one palette.

    QSS can only load images from files, so icons the stylesheet draws come
    in as paths of recoloured SVGs: ``combo_arrow`` (dropdown chevron) and
    ``up_arrow`` (kept for older callers), plus ``icons`` with any of
    ``plus``, ``minus`` (number-box buttons) and ``check`` (tick on the
    accent). Missing ones fall back to what Qt draws itself.
    """
    paths = dict(icons or {})

    def image(path: str | None) -> str:
        return f'image: url("{path}");' if path else ""

    values: dict[str, str] = {name: getattr(t, name) for name in t.__dataclass_fields__ if name != "name"}
    values.update(derived_colors(t))
    values["combo_arrow"] = image(combo_arrow)
    values["spin_up_arrow"] = image(paths.get("plus") or up_arrow)
    values["spin_down_arrow"] = image(paths.get("minus") or combo_arrow)
    values["check_mark"] = image(paths.get("check"))
    return _TEMPLATE.substitute(values)
