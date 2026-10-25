"""Icon capsules for status, and banners with an icon — no emoji anywhere.

* :class:`StatusBadge` — a small rounded pill: icon + word, tinted to its
  meaning (Ready, Check, Failed, Unverified, Working…). "Working" spins.
* :class:`Banner` — a full-width message with a leading icon.
* :class:`StatusIcon` — a large icon on a rounded tinted tile (result cards).
* :class:`IconText` — an icon and a line of text (result-card check rows).
* :class:`StatusDelegate` — paints a capsule inside a table cell (batch).

Colours come from the theme (the same tints as the stylesheet chips), so
they follow light and dark mode.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from docly.ui import motion
from docly.ui.icons import render_icon
from docly.ui.qss import derived_colors
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.style import set_style_prop

#: kind → icon. Kinds match the stylesheet's tints.
ICONS: dict[str, str] = {
    "success": "circle-check",
    "warning": "triangle-alert",
    "danger": "circle-x",
    "neutral": "info",
    "working": "loader-circle",
    "info": "info",
}


def kind_colour(tokens: Tokens, kind: str) -> str:
    colours = derived_colors(tokens)
    return {
        "success": colours["success_text"],
        "warning": colours["warning_text"],
        "danger": colours["danger_text"],
    }.get(kind, colours["accent_text"])


class StatusBadge(QFrame):
    """A capsule with an icon and a short word."""

    ICON_PX = 14

    def __init__(self, theme: ThemeManager, kind: str = "neutral", text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBadge")
        self._tokens = theme.tokens
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 10, 2)
        layout.setSpacing(5)
        self.icon = QLabel()
        self.icon.setFixedSize(QSize(self.ICON_PX, self.ICON_PX))
        self.label = QLabel(text)
        self.label.setObjectName("StatusBadgeText")
        layout.addWidget(self.icon)
        layout.addWidget(self.label)
        self._kind = ""
        self._base: QPixmap | None = None
        self._spin = QVariantAnimation(self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(900)
        self._spin.setLoopCount(-1)
        self._spin.valueChanged.connect(self._rotate)
        theme.themeChanged.connect(self._apply_tokens)
        self.set_status(kind, text)

    @property
    def kind(self) -> str:
        return self._kind

    def text(self) -> str:
        return self.label.text()

    def set_status(self, kind: str, text: str) -> None:
        self._kind = kind
        self.label.setText(text)
        self.setAccessibleName(text)
        set_style_prop(self, "kind", "warning" if kind == "working" else kind)
        self._paint_icon()

    def _paint_icon(self) -> None:
        colour = kind_colour(self._tokens, self._kind)
        self._base = render_icon(ICONS.get(self._kind, "info"), colour, self.ICON_PX, self.devicePixelRatioF())
        self.icon.setPixmap(self._base)
        if self._kind == "working" and motion.enabled():
            if self._spin.state() != QAbstractAnimation.State.Running:
                self._spin.start()
        else:
            self._spin.stop()

    def _rotate(self, angle: float) -> None:
        if self._base is not None:
            self.icon.setPixmap(_turned(self._base, angle))

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self._paint_icon()


class StatusIcon(QLabel):
    """A big status icon on a soft tinted tile. ``kind`` "" hides it."""

    TILE = 40
    ICON_PX = 22

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusIcon")
        self.setFixedSize(self.TILE, self.TILE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tokens = theme.tokens
        self._kind = ""
        self._base: QPixmap | None = None
        self._spin = QVariantAnimation(self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(900)
        self._spin.setLoopCount(-1)
        self._spin.valueChanged.connect(self._rotate)
        theme.themeChanged.connect(self._apply_tokens)
        self.hide()

    @property
    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        set_style_prop(self, "kind", "warning" if kind == "working" else (kind or None))
        self._paint()
        self.setVisible(bool(kind))

    def _paint(self) -> None:
        self._spin.stop()
        if not self._kind:
            self.clear()
            self._base = None
            return
        colour = kind_colour(self._tokens, self._kind)
        self._base = render_icon(ICONS.get(self._kind, "info"), colour, self.ICON_PX, self.devicePixelRatioF())
        self.setPixmap(self._base)
        if self._kind == "working" and motion.enabled():
            self._spin.start()

    def _rotate(self, angle: float) -> None:
        if self._base is not None:
            self.setPixmap(_turned(self._base, angle))

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self._paint()


def _turned(base: QPixmap, angle: float) -> QPixmap:
    """``base`` rotated about its centre, cropped back to its own size so
    the layout doesn't wobble while it spins."""
    turned = base.transformed(QTransform().rotate(angle), Qt.TransformationMode.SmoothTransformation)
    w, h = base.width(), base.height()
    cropped = turned.copy((turned.width() - w) // 2, (turned.height() - h) // 2, w, h)
    cropped.setDevicePixelRatio(base.devicePixelRatio())
    return cropped


class Banner(QFrame):
    """An inline message with a leading icon (danger, warning, info, success)."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self._tokens = theme.tokens
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.label = QLabel()
        self.label.setObjectName("BannerText")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.label, 1)
        self._kind = "info"
        theme.themeChanged.connect(self._apply_tokens)
        self.hide()

    @property
    def kind(self) -> str:
        return self._kind

    def text(self) -> str:
        return self.label.text()

    def show_message(self, text: str, kind: str = "danger") -> None:
        was_hidden = self.isHidden()
        self._kind = kind
        self.label.setText(text)
        set_style_prop(self, "kind", kind)
        self._paint_icon()
        if was_hidden:
            motion.fade_in(self)
        else:
            self.show()

    def _paint_icon(self) -> None:
        colour = kind_colour(self._tokens, self._kind)
        self.icon.setPixmap(render_icon(ICONS.get(self._kind, "info"), colour, 16, self.devicePixelRatioF()))

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self._paint_icon()


class IconText(QWidget):
    """An icon and a line of text, e.g. a check row "Size: 200 × 230 px"."""

    def __init__(self, theme: ThemeManager, kind: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens, self._kind = theme.tokens, kind
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setProperty("role", "body")
        if kind in ("danger", "warning"):
            self.label.setProperty("tone", kind)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.label, 1)
        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    @property
    def kind(self) -> str:
        return self._kind

    def text(self) -> str:
        return self.label.text()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        colour = kind_colour(tokens, self._kind)
        self.icon.setPixmap(render_icon(ICONS.get(self._kind, "info"), colour, 16, self.devicePixelRatioF()))


#: kind → the base token its tint is made from.
TINT_TOKEN = {"success": "success", "warning": "warning", "danger": "danger"}


class StatusDelegate(QStyledItemDelegate):
    """Draws a cell's text as a capsule (icon + word).

    The cell keeps its plain text, so copying, sorting, screen readers and
    tests still see "Ready"; only the painting changes. ``kinds`` maps the
    text to a kind; unknown text is drawn as a quiet neutral word.
    """

    PAD_X, GAP, ICON_PX, HEIGHT = 8, 5, 14, 22

    def __init__(self, theme: ThemeManager, kinds: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = theme.tokens
        self._kinds = kinds
        theme.themeChanged.connect(self._apply_tokens)

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens

    def _font(self, option: QStyleOptionViewItem):  # noqa: ANN202
        font = option.font
        font.setWeight(font.Weight.DemiBold)
        font.setPixelSize(12)
        return font

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:  # noqa: N802
        text = str(index.data() or "")
        width = QFontMetrics(self._font(option)).horizontalAdvance(text)
        return QSize(self.PAD_X * 2 + self.ICON_PX + self.GAP + width + 16, self.HEIGHT + 8)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        text = str(index.data() or "")
        kind = self._kinds.get(text)
        # Row background / selection, without the text.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font(option)
        painter.setFont(font)
        text_w = QFontMetrics(font).horizontalAdvance(text)
        icon_w = self.ICON_PX + self.GAP if kind else 0
        width = self.PAD_X * 2 + icon_w + text_w
        rect = QRectF(option.rect.x() + 6, option.rect.center().y() - self.HEIGHT / 2 + 0.5, width, self.HEIGHT)
        if kind:
            token = TINT_TOKEN.get(kind, "accent")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._tokens.qcolor(token, 46 if self._tokens.is_dark else 34))
            painter.drawRoundedRect(rect, self.HEIGHT / 2, self.HEIGHT / 2)
            colour = kind_colour(self._tokens, kind)
            dpr = painter.device().devicePixelRatioF() if painter.device() is not None else 1.0
            pixmap = render_icon(ICONS.get(kind, "info"), colour, self.ICON_PX, dpr)
            icon_y = rect.center().y() - self.ICON_PX / 2
            painter.drawPixmap(int(rect.x() + self.PAD_X), int(round(icon_y)), pixmap)
            painter.setPen(QColor(colour))
        else:
            painter.setPen(self._tokens.qcolor("text_muted"))
        text_rect = rect.adjusted(self.PAD_X + icon_w, 0, -self.PAD_X + 2, 0)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        painter.restore()
