"""Photo preview with a ratio-locked crop frame.

The widget shows a reduced *display* copy of the photo (fast to paint) and
keeps the crop box in display-image coordinates. :meth:`crop_box` converts
it to full-resolution pixels for the engine.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from docly.core.resize import CropBox
from docly.ui.theme import ThemeManager, Tokens

MARGIN = 12  # px around the photo
HANDLE = 10  # corner handle size (widget px)
HIT = 14  # how close (widget px) counts as grabbing a corner
MIN_BOX = 24  # smallest crop frame (display px)


class _Drag(Enum):
    NONE = 0
    MOVE = 1
    RESIZE = 2


class CropView(QWidget):
    """Shows the photo; lets the user move/resize a ratio-locked frame.

    Signals:
        cropChanged(): the user finished moving or resizing the frame.
    """

    cropChanged = Signal()

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(300, 260))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Photo crop area. Arrow keys move the frame.")

        self._tokens = theme.tokens
        theme.themeChanged.connect(self._apply_tokens)

        self._image: QImage | None = None
        self._full_size: tuple[int, int] = (0, 0)
        self._ratio: float | None = None
        self._box = QRectF()  # display-image coordinates
        self._drag = _Drag.NONE
        self._anchor = QPointF()  # fixed corner while resizing
        self._grab_offset = QPointF()  # mouse offset inside the box while moving

    # ----- public API -------------------------------------------------
    def set_image(self, image: QImage, full_size: tuple[int, int], ratio: float | None) -> None:
        """Show ``image`` (a display copy of a ``full_size`` photo)."""
        self._image = image
        self._full_size = full_size
        self.set_ratio(ratio)

    def clear(self) -> None:
        self._image = None
        self._box = QRectF()
        self.update()

    def set_ratio(self, ratio: float | None) -> None:
        """Lock the frame to ``ratio`` (w ÷ h) and centre it; None = no crop."""
        self._ratio = ratio
        self.reset()

    def reset(self) -> None:
        """Largest centred frame with the current ratio."""
        if self._image is None or self._ratio is None:
            self._box = QRectF()
        else:
            w, h = self._image.width(), self._image.height()
            if w / h > self._ratio:
                bw, bh = h * self._ratio, float(h)
            else:
                bw, bh = float(w), w / self._ratio
            self._box = QRectF((w - bw) / 2, (h - bh) / 2, bw, bh)
        self.update()

    @property
    def has_crop(self) -> bool:
        return not self._box.isEmpty()

    @property
    def display_box(self) -> QRectF:
        return QRectF(self._box)

    def crop_box(self) -> CropBox | None:
        """Frame in full-resolution pixels, or None when there is no frame."""
        if self._image is None or self._box.isEmpty():
            return None
        sx = self._full_size[0] / self._image.width()
        sy = self._full_size[1] / self._image.height()
        x = round(self._box.x() * sx)
        y = round(self._box.y() * sy)
        w = max(1, min(round(self._box.width() * sx), self._full_size[0] - x))
        h = max(1, min(round(self._box.height() * sy), self._full_size[1] - y))
        return CropBox(x, y, w, h)

    def image_rect(self) -> QRectF:
        """Where the photo is drawn inside the widget."""
        if self._image is None:
            return QRectF()
        avail_w = max(1.0, self.width() - 2 * MARGIN)
        avail_h = max(1.0, self.height() - 2 * MARGIN)
        scale = min(avail_w / self._image.width(), avail_h / self._image.height())
        w, h = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_widget(self, point: QPointF) -> QPointF:
        """Display-image coordinates → widget coordinates."""
        rect = self.image_rect()
        scale = rect.width() / self._image.width() if self._image else 1.0
        return QPointF(rect.x() + point.x() * scale, rect.y() + point.y() * scale)

    def to_image(self, point: QPointF) -> QPointF:
        """Widget coordinates → display-image coordinates (not clamped)."""
        rect = self.image_rect()
        scale = rect.width() / self._image.width() if self._image else 1.0
        return QPointF((point.x() - rect.x()) / scale, (point.y() - rect.y()) / scale)

    def move_box(self, dx: float, dy: float) -> None:
        """Move the frame by display pixels, kept inside the photo."""
        if self._box.isEmpty():
            return
        self._box.translate(dx, dy)
        self._clamp_inside()
        self.update()

    # ----- painting ---------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), t.qcolor("surface_alt"))
        if self._image is None:
            painter.end()
            return

        rect = self.image_rect()
        painter.drawImage(rect, self._image)

        if not self._box.isEmpty():
            top_left = self.to_widget(self._box.topLeft())
            bottom_right = self.to_widget(self._box.bottomRight())
            box = QRectF(top_left, bottom_right)

            outside = QPainterPath()
            outside.addRect(rect)
            inner = QPainterPath()
            inner.addRect(box)
            painter.fillPath(outside.subtracted(inner), t.qcolor("shadow", 140))

            painter.setPen(QPen(t.qcolor("surface", 110), 1))
            for i in (1, 2):
                x = box.left() + box.width() * i / 3
                y = box.top() + box.height() * i / 3
                painter.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
                painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))

            painter.setPen(QPen(t.qcolor("accent"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)

            painter.setPen(QPen(t.qcolor("accent"), 1.5))
            painter.setBrush(t.qcolor("surface"))
            for corner in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()):
                painter.drawRect(QRectF(corner.x() - HANDLE / 2, corner.y() - HANDLE / 2, HANDLE, HANDLE))

            if self.hasFocus():
                painter.setPen(QPen(t.qcolor("accent", 120), 1, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(box.adjusted(-4, -4, 4, 4))
        painter.end()

    # ----- mouse ------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._box.isEmpty():
            return super().mousePressEvent(event)
        pos = event.position()
        corner = self._corner_at(pos)
        if corner is not None:
            self._drag = _Drag.RESIZE
            self._anchor = self._opposite(corner)
        elif self._widget_box().contains(pos):
            self._drag = _Drag.MOVE
            self._grab_offset = self.to_image(pos) - self._box.topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag == _Drag.MOVE:
            top_left = self.to_image(pos) - self._grab_offset
            self._box.moveTopLeft(top_left)
            self._clamp_inside()
            self.update()
        elif self._drag == _Drag.RESIZE:
            self._resize_to(self.to_image(pos))
            self.update()
        else:
            self._update_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag != _Drag.NONE:
            self._drag = _Drag.NONE
            self._update_cursor(event.position())
            self.cropChanged.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        moves = {
            Qt.Key.Key_Left: (-step, 0.0),
            Qt.Key.Key_Right: (step, 0.0),
            Qt.Key.Key_Up: (0.0, -step),
            Qt.Key.Key_Down: (0.0, step),
        }
        if event.key() in moves and self.has_crop:
            self.move_box(*moves[event.key()])
            self.cropChanged.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        self.update()
        super().resizeEvent(event)

    # ----- geometry helpers -------------------------------------------
    def _widget_box(self) -> QRectF:
        return QRectF(self.to_widget(self._box.topLeft()), self.to_widget(self._box.bottomRight()))

    def _corner_at(self, pos: QPointF) -> QPointF | None:
        box = self._widget_box()
        for corner_w, corner_img in (
            (box.topLeft(), self._box.topLeft()),
            (box.topRight(), self._box.topRight()),
            (box.bottomLeft(), self._box.bottomLeft()),
            (box.bottomRight(), self._box.bottomRight()),
        ):
            if abs(pos.x() - corner_w.x()) <= HIT and abs(pos.y() - corner_w.y()) <= HIT:
                return corner_img
        return None

    def _opposite(self, corner: QPointF) -> QPointF:
        b = self._box
        x = b.left() if abs(corner.x() - b.right()) < 1e-6 else b.right()
        y = b.top() if abs(corner.y() - b.bottom()) < 1e-6 else b.bottom()
        return QPointF(x, y)

    def _resize_to(self, point: QPointF) -> None:
        """Resize from the anchor corner towards ``point`` keeping the ratio."""
        assert self._image is not None and self._ratio is not None
        ratio = self._ratio
        ax, ay = self._anchor.x(), self._anchor.y()
        going_right = point.x() >= ax
        going_down = point.y() >= ay
        max_w = (self._image.width() - ax) if going_right else ax
        max_h = (self._image.height() - ay) if going_down else ay

        w = max(abs(point.x() - ax), abs(point.y() - ay) * ratio, MIN_BOX)
        h = w / ratio
        if w > max_w:
            w, h = max_w, max_w / ratio
        if h > max_h:
            h, w = max_h, max_h * ratio
        x = ax if going_right else ax - w
        y = ay if going_down else ay - h
        self._box = QRectF(x, y, w, h)

    def _clamp_inside(self) -> None:
        if self._image is None:
            return
        b = self._box
        x = min(max(b.x(), 0.0), self._image.width() - b.width())
        y = min(max(b.y(), 0.0), self._image.height() - b.height())
        self._box.moveTopLeft(QPointF(x, y))

    def _update_cursor(self, pos: QPointF) -> None:
        if self._box.isEmpty():
            self.unsetCursor()
            return
        corner = self._corner_at(pos)
        if corner is not None:
            opposite = self._opposite(corner)
            same_sign = (corner.x() - opposite.x()) * (corner.y() - opposite.y()) > 0
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if same_sign else Qt.CursorShape.SizeBDiagCursor)
        elif self._widget_box().contains(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self.update()
