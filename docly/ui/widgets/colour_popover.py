"""Docly's own colour picker: swatches, a hex box and recent colours.

Windows' built-in colour dialog is a 1990s grid with RGB/HSL spin boxes —
far more than a photo background needs. This small popover opens next to
the control that asked for it, shows background-friendly swatches first,
and accepts a typed hex code (with or without the ``#``).

Desktop note: the popover is a ``QDialog`` with the ``Popup`` window flag.
Popups close by themselves when you click elsewhere or press Esc, which
counts as "Cancel".
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPoint, QRectF, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from docly.ui.theme import ThemeManager, Tokens

RGB = tuple[int, int, int]

#: Light, plain backgrounds that photo rules usually allow, then a few others.
SWATCHES: tuple[tuple[str, RGB], ...] = (
    ("White", (255, 255, 255)),
    ("Off-white", (245, 245, 240)),
    ("Light grey", (229, 231, 235)),
    ("Cream", (250, 244, 228)),
    ("Light blue", (205, 225, 245)),
    ("Pale blue", (225, 236, 248)),
    ("Sky blue", (176, 210, 240)),
    ("Mid blue", (120, 165, 215)),
    ("Pale green", (222, 240, 226)),
    ("Grey", (190, 194, 200)),
    ("Red", (200, 40, 40)),
    ("Dark blue", (30, 60, 120)),
)
MAX_RECENT = 6
DARK_HINT = "Most portals want a light, plain background."
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

_recent: list[RGB] = []  # this session's picks, newest first


def parse_hex(text: str) -> RGB | None:
    """Six hex digits (``#`` optional) or the 3-digit short form → RGB; else None."""
    match = HEX_RE.match(text.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


#: Shown as the hex box placeholder and in the "how to type it" hint.
EXAMPLE_HEX = to_hex((220, 230, 240))


def is_dark(rgb: RGB) -> bool:
    """Perceived brightness below the middle (photo backgrounds should be light)."""
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) < 150


def recent_colours() -> list[RGB]:
    return list(_recent)


def remember(rgb: RGB) -> None:
    if rgb in _recent:
        _recent.remove(rgb)
    _recent.insert(0, rgb)
    del _recent[MAX_RECENT:]


class SwatchButton(QAbstractButton):
    """A round colour button; a ring shows the selected one."""

    SIZE = 28

    def __init__(self, rgb: RGB, name: str, tokens: Tokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rgb = rgb
        self._tokens = tokens
        self.setCheckable(True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{name}  {to_hex(rgb)}")
        self.setAccessibleName(name)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isChecked() or self.hasFocus():
            painter.setPen(self._tokens.qcolor("accent"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(outer)
        inner = outer.adjusted(4, 4, -4, -4)
        painter.setPen(self._tokens.qcolor("text", 60))
        painter.setBrush(QColor(*self.rgb))
        painter.drawEllipse(inner)
        if self.underMouse() and not self.isChecked():
            painter.setPen(self._tokens.qcolor("text", 90))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(outer.adjusted(2, 2, -2, -2))


class ColourChip(QLabel):
    """A rounded rectangle preview of the current colour."""

    def __init__(self, tokens: Tokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self.rgb: RGB = (255, 255, 255)
        self.setFixedSize(36, 36)

    def set_rgb(self, rgb: RGB) -> None:
        self.rgb = rgb
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self._tokens.qcolor("border"))
        painter.setBrush(QColor(*self.rgb))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


class ColourPopover(QDialog):
    """Pick a colour. :meth:`colour` holds the choice after ``exec()``.

    Signals:
        picked(tuple): live preview while choosing (not used by the card yet).
    """

    picked = Signal(tuple)

    def __init__(self, theme: ThemeManager, start: RGB, title: str = "Background colour", parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("ColourPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)  # rounded corners
        tokens = theme.tokens
        self._colour: RGB = start
        self.swatches: list[SwatchButton] = []

        frame = QFrame(self)
        frame.setObjectName("PopoverFrame")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        heading = QLabel(title)
        heading.setProperty("role", "section")
        layout.addWidget(heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, (name, rgb) in enumerate(SWATCHES):
            button = SwatchButton(rgb, name, tokens)
            button.clicked.connect(lambda _c=False, value=rgb: self._choose(value))
            grid.addWidget(button, index // 6, index % 6)
            self.swatches.append(button)
        layout.addLayout(grid)

        self.recent_label = QLabel("Recent")
        self.recent_label.setProperty("role", "caption")
        self.recent_row = QHBoxLayout()
        self.recent_row.setSpacing(6)
        self.recent_buttons: list[SwatchButton] = []
        for rgb in recent_colours():
            button = SwatchButton(rgb, "Recent colour", tokens)
            button.clicked.connect(lambda _c=False, value=rgb: self._choose(value))
            self.recent_row.addWidget(button)
            self.recent_buttons.append(button)
        self.recent_row.addStretch(1)
        has_recent = bool(self.recent_buttons)
        self.recent_label.setVisible(has_recent)
        layout.addWidget(self.recent_label)
        layout.addLayout(self.recent_row)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(10)
        self.chip = ColourChip(tokens)
        self.hex_edit = QLineEdit()
        self.hex_edit.setAccessibleName("Hex colour code")
        self.hex_edit.setPlaceholderText(EXAMPLE_HEX)
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"#?[0-9A-Fa-f]{0,6}"), self))
        hex_row.addWidget(self.chip)
        hex_row.addWidget(self.hex_edit, 1)
        layout.addLayout(hex_row)

        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.use_button = QPushButton("Use colour")
        self.use_button.setProperty("variant", "primary")
        self.use_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)

        self.cancel_button.clicked.connect(self.reject)
        self.use_button.clicked.connect(self._accept_if_valid)
        self.hex_edit.textEdited.connect(self._on_hex)
        self.hex_edit.returnPressed.connect(self._accept_if_valid)
        self.setFixedWidth(6 * SwatchButton.SIZE + 5 * 6 + 28 + 2)
        self._choose(start)

    def colour(self) -> RGB:
        return self._colour

    # ----- internals ------------------------------------------------------
    def _choose(self, rgb: RGB) -> None:
        self._colour = rgb
        self.chip.set_rgb(rgb)
        if parse_hex(self.hex_edit.text()) != rgb:
            self.hex_edit.setText(to_hex(rgb))
        for button in (*self.swatches, *self.recent_buttons):
            button.setChecked(button.rgb == rgb)
        self._show_hint("")
        self.use_button.setEnabled(True)
        self.picked.emit(rgb)

    def _on_hex(self, text: str) -> None:
        rgb = parse_hex(text)
        if rgb is None:
            self.use_button.setEnabled(False)
            self._show_hint(f"Type 6 hex digits, like {EXAMPLE_HEX}." if len(text.strip("#")) >= 3 else "")
            return
        self._choose(rgb)

    def _show_hint(self, text: str) -> None:
        if not text and is_dark(self._colour):
            text = DARK_HINT
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def _accept_if_valid(self) -> None:
        if parse_hex(self.hex_edit.text()) is None:
            self.use_button.setEnabled(False)
            return
        remember(self._colour)
        self.accept()

    def place_below(self, anchor: QWidget) -> None:
        """Open just under ``anchor``, kept on its screen."""
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = anchor.screen().availableGeometry() if anchor.screen() is not None else None
        if screen is not None:
            x = min(max(point.x(), screen.left() + 8), screen.right() - self.width() - 8)
            y = point.y()
            if y + self.height() > screen.bottom() - 8:
                y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
            point = QPoint(x, max(screen.top() + 8, y))
        self.move(point)


def ask_colour(theme: ThemeManager, anchor: QWidget, start: RGB) -> RGB | None:
    """Open the popover under ``anchor``; the colour, or None if cancelled."""
    popover = ColourPopover(theme, start, parent=anchor)
    popover.place_below(anchor)
    accepted = popover.exec() == QDialog.DialogCode.Accepted
    colour = popover.colour()
    popover.deleteLater()
    return colour if accepted else None
