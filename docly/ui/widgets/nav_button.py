"""Sidebar navigation button with an animated hover tint.

QSS can't animate, so this button paints itself. A ``QVariantAnimation``
fades the hover tint in and out over ~140 ms.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QEnterEvent, QFocusEvent, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from docly.ui.icons import render_icon
from docly.ui.theme import ThemeManager, Tokens

HOVER_MS = 140
HEIGHT = 38
ICON_SIZE = 18
RADIUS = 8.0
BAR_WIDTH = 3.0
BAR_INSET = 10  # gap above and below the selected bar


class NavButton(QAbstractButton):
    """Icon + label button for the sidebar.

    Checkable buttons show the selected state (accent tint and a 3px accent
    bar on the left). Non-checkable ones act as plain actions.
    """

    def __init__(
        self,
        text: str,
        icon_name: str,
        theme: ThemeManager,
        checkable: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setAccessibleName(text)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(HEIGHT)

        self._icon_name = icon_name
        self._tokens = theme.tokens
        self._hover = 0.0  # 0 = not hovered, 1 = fully hovered
        self._focus_visible = False
        #: False when the sidebar draws a sliding bar instead of each button.
        self.paint_bar = True

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(HOVER_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_hover_value)

        theme.themeChanged.connect(self._apply_tokens)
        self.toggled.connect(lambda _checked: self.update())

    # ----- public API -------------------------------------------------
    @property
    def icon_name(self) -> str:
        return self._icon_name

    def set_content(self, text: str, icon_name: str) -> None:
        """Change label and icon (used by the theme toggle)."""
        self.setText(text)
        self.setAccessibleName(text)
        self._icon_name = icon_name
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt name)
        return QSize(180, HEIGHT)

    # ----- events -----------------------------------------------------
    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._animate_to(0.0)
        super().leaveEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        # Only show a focus ring for keyboard focus, like modern Windows apps.
        self._focus_visible = event.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
        )
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._focus_visible = False
        #: False when the sidebar draws a sliding bar instead of each button.
        self.paint_bar = True
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        selected = self.isCheckable() and self.isChecked()

        # Background: accent tint when selected, fading neutral tint on hover.
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.qcolor("accent", 46 if t.is_dark else 30))
            painter.drawRoundedRect(rect, RADIUS, RADIUS)
        if self._hover > 0.0 or self.isDown():
            base = 16 if t.is_dark else 10
            alpha = round(base * (1.0 if self.isDown() else self._hover)) + (8 if self.isDown() else 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.qcolor("text", alpha))
            painter.drawRoundedRect(rect, RADIUS, RADIUS)

        # 3px accent bar on the left of the selected item.
        if selected and self.paint_bar:
            bar = QRectF(rect.left() + 1, rect.top() + BAR_INSET, BAR_WIDTH, rect.height() - 2 * BAR_INSET)
            painter.setBrush(t.qcolor("accent"))
            painter.drawRoundedRect(bar, BAR_WIDTH / 2, BAR_WIDTH / 2)

        # Keyboard focus ring.
        if self._focus_visible and self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(t.qcolor("accent", 170), 1.5))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS - 1, RADIUS - 1)

        # Icon.
        icon_color = t.accent if selected else t.text_muted
        if self._hover > 0.5 and not selected:
            icon_color = t.text
        pixmap = render_icon(self._icon_name, icon_color, ICON_SIZE, self.devicePixelRatioF())
        icon_x = 14
        icon_y = (self.height() - ICON_SIZE) / 2
        painter.drawPixmap(int(icon_x), int(icon_y), pixmap)

        # Label.
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(t.text))
        text_rect = QRectF(icon_x + ICON_SIZE + 12, 0, self.width() - (icon_x + ICON_SIZE + 20), self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()

    # ----- internals --------------------------------------------------
    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_hover_value(self, value: object) -> None:
        self._hover = float(value)  # type: ignore[arg-type]
        self.update()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self.update()
