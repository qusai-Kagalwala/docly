"""The things you place on a page: text, date, tick, cross, signature, cover-up.

Desktop concept — *graphics items*: each placed thing is a small object in
a ``QGraphicsScene``. Qt handles selecting and dragging them; we draw them
and add a resize handle in the bottom-right corner.

Scene units are PDF points (1/72 inch) with the origin at the page's
top-left, exactly the coordinates the engine (:mod:`docly.core.pdf_fill`)
uses, so what you see is where it prints.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsSceneMouseEvent, QStyleOptionGraphicsItem, QWidget

from docly.core.helvetica import ASCENT
from docly.core.pdf_fill import (
    BLACK,
    LINE_HEIGHT,
    MAX_FONT,
    MIN_FONT,
    TEXT_TOP_PAD,
    Box,
    FillItem,
    ItemKind,
    format_date,
    text_size,
)

HANDLE_PX = 10  # resize handle size on screen, whatever the zoom
State = dict[str, Any]


class SignItem(QGraphicsObject):
    """Base class: a movable, selectable box with a resize handle.

    Signals:
        edited(): a property changed (the side panel refreshes).
    """

    edited = Signal()
    KIND: ItemKind = ItemKind.COVER
    #: Selection colour; the page sets it from the theme's accent.
    accent = QColor(Qt.GlobalColor.darkBlue)
    KEEP_ASPECT = False
    MIN_SIZE = 6.0

    def __init__(self, w: float, h: float) -> None:
        super().__init__()
        self._w, self._h = float(w), float(h)
        self.page_rect = QRectF()
        self._resizing = False
        self._press_size = (self._w, self._h)
        self._press_state: State = {}
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    # ----- geometry --------------------------------------------------------
    @property
    def kind(self) -> ItemKind:
        return self.KIND

    @property
    def size(self) -> tuple[float, float]:
        return self._w, self._h

    def box(self) -> Box:
        return Box(self.pos().x(), self.pos().y(), self._w, self._h)

    def set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w, self._h = max(self.MIN_SIZE, w), max(self.MIN_SIZE, h)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        margin = self._handle_size() + 2
        return QRectF(-2, -2, self._w + margin + 2, self._h + margin + 2)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self._w, self._h))
        path.addRect(self._handle_rect())
        return path

    def _scale(self) -> float:
        views = self.scene().views() if self.scene() is not None else []
        return views[0].transform().m11() if views else 1.0

    def _handle_size(self) -> float:
        return HANDLE_PX / max(self._scale(), 0.05)

    def _handle_rect(self) -> QRectF:
        s = self._handle_size()
        return QRectF(self._w - s / 2, self._h - s / 2, s, s)

    # ----- state (for undo) -------------------------------------------------
    def state(self) -> State:
        return {"x": self.pos().x(), "y": self.pos().y(), "w": self._w, "h": self._h}

    def set_state(self, state: State) -> None:
        self.set_size(state["w"], state["h"])
        self.setPos(state["x"], state["y"])
        self.edited.emit()

    def to_fill(self, page: int) -> FillItem:
        raise NotImplementedError

    # ----- painting -----------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        painter.save()
        self.paint_content(painter)
        painter.restore()
        if self.isSelected():
            scale = max(painter.worldTransform().m11(), 0.05)
            pen = QPen(self.accent, 1.5 / scale, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, self._w, self._h))
            painter.setPen(QPen(QColor("white"), 1 / scale))
            painter.setBrush(self.accent)
            painter.drawRect(self._handle_rect())

    def paint_content(self, painter: QPainter) -> None:
        raise NotImplementedError

    # ----- dragging and resizing ----------------------------------------------------
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self.page_rect.isNull():
            return self._clamped(QPointF(value))
        return super().itemChange(change, value)

    def _clamped(self, point: QPointF) -> QPointF:
        """Keep at least part of the item on the page."""
        r = self.page_rect
        keep = min(12.0, self._w / 2, self._h / 2)
        x = min(max(point.x(), r.left() - self._w + keep), r.right() - keep)
        y = min(max(point.y(), r.top() - self._h + keep), r.bottom() - keep)
        return QPointF(x, y)

    def hoverMoveEvent(self, event) -> None:  # noqa: N802, ANN001
        on_handle = self.isSelected() and self._handle_rect().contains(event.pos())
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if on_handle else Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self.isSelected() and self._handle_rect().contains(event.pos()):
            self._resizing = True
            self._press_size = (self._w, self._h)
            self._press_state = self.state()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._resizing:
            self.resize_to(event.pos().x(), event.pos().y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # noqa: N802
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resize_to(self, w: float, h: float) -> None:
        """Drag the bottom-right handle to (w, h) in item coordinates."""
        if self.KEEP_ASPECT:
            ratio = self._press_size[0] / self._press_size[1]
            w = max(w, h * ratio)
            h = w / ratio
        self.set_size(w, h)
        self.edited.emit()


# ----------------------------------------------------------------------
class TextItem(SignItem):
    """Typed text or a date. Resizing changes the font size."""

    KIND = ItemKind.TEXT
    KEEP_ASPECT = True

    def __init__(
        self, text: str = "Your text", font_size: float = 12.0, colour: tuple[int, int, int] = BLACK,
        date_style: str | None = None, day: date | None = None,
    ) -> None:  # fmt: skip
        self.text = text
        self.font_size = font_size
        self.colour = colour
        self.date_style = date_style
        self.day = day or date.today()
        if date_style:
            self.text = format_date(self.day, date_style)
        super().__init__(*text_size(self.text, font_size))

    @property
    def is_date(self) -> bool:
        return self.date_style is not None

    def set_text(self, text: str) -> None:
        self.text = text
        self._refit()

    def set_font_size(self, size: float) -> None:
        self.font_size = min(MAX_FONT, max(MIN_FONT, size))
        self._refit()

    def set_colour(self, colour: tuple[int, int, int]) -> None:
        self.colour = colour
        self.update()
        self.edited.emit()

    def set_date_style(self, style: str) -> None:
        self.date_style = style
        self.text = format_date(self.day, style)
        self._refit()

    def _refit(self) -> None:
        self.set_size(*text_size(self.text or " ", self.font_size))
        self.edited.emit()

    def state(self) -> State:
        return {**super().state(), "text": self.text, "font_size": self.font_size, "colour": self.colour,
                "date_style": self.date_style}  # fmt: skip

    def set_state(self, state: State) -> None:
        self.text, self.font_size = state["text"], state["font_size"]
        self.colour, self.date_style = state["colour"], state["date_style"]
        super().set_state(state)

    def resize_to(self, w: float, h: float) -> None:
        start_w, start_h = self._press_size
        start_font = self._press_state.get("font_size", self.font_size)
        factor = max(w / start_w, h / start_h, 0.05)
        self.set_font_size(round(start_font * factor, 1))

    def to_fill(self, page: int) -> FillItem:
        return FillItem(ItemKind.TEXT, page, self.box(), self.text, self.font_size, self.colour)

    def paint_content(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Arial")  # Windows' stand-in for Helvetica, with the same widths
        font.setPixelSize(100)
        painter.setFont(font)
        painter.setPen(QColor(*self.colour))
        fs = self.font_size
        for index, line in enumerate(self.text.split("\n")):
            baseline = fs * TEXT_TOP_PAD + fs * ASCENT / 1000.0 + index * fs * LINE_HEIGHT
            painter.save()
            painter.translate(0, baseline)
            painter.scale(fs / 100.0, fs / 100.0)
            painter.drawText(QPointF(0, 0), line)
            painter.restore()


class MarkItem(SignItem):
    """A tick or a cross, always square."""

    KEEP_ASPECT = True

    def __init__(self, kind: ItemKind, size: float = 14.0, colour: tuple[int, int, int] = BLACK) -> None:
        super().__init__(size, size)
        self._kind = kind
        self.colour = colour

    @property
    def kind(self) -> ItemKind:
        return self._kind

    def set_colour(self, colour: tuple[int, int, int]) -> None:
        self.colour = colour
        self.update()
        self.edited.emit()

    def state(self) -> State:
        return {**super().state(), "colour": self.colour}

    def set_state(self, state: State) -> None:
        self.colour = state["colour"]
        super().set_state(state)

    def to_fill(self, page: int) -> FillItem:
        return FillItem(self._kind, page, self.box(), colour=self.colour)

    def paint_content(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self._w, self._h
        pen = QPen(QColor(*self.colour), max(0.6, 0.12 * min(w, h)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        if self._kind == ItemKind.TICK:  # same shape as the engine draws (y down here)
            path.moveTo(0.12 * w, 0.5 * h)
            path.lineTo(0.4 * w, 0.82 * h)
            path.lineTo(0.9 * w, 0.15 * h)
        else:
            path.moveTo(0.15 * w, 0.15 * h)
            path.lineTo(0.85 * w, 0.85 * h)
            path.moveTo(0.15 * w, 0.85 * h)
            path.lineTo(0.85 * w, 0.15 * h)
        painter.drawPath(path)


class ImageItem(SignItem):
    """A signature (or stamp) image; see-through areas stay see-through."""

    KIND = ItemKind.IMAGE
    KEEP_ASPECT = True

    def __init__(self, data: bytes, width: float = 150.0) -> None:
        self.data = data
        self.image = QImage.fromData(data)
        self._scaled: QImage | None = None
        ratio = self.image.height() / self.image.width() if not self.image.isNull() and self.image.width() else 0.4
        super().__init__(width, width * ratio)

    def to_fill(self, page: int) -> FillItem:
        return FillItem(ItemKind.IMAGE, page, self.box(), image=self.data)

    def paint_content(self, painter: QPainter) -> None:
        # Shrinking a large image straight onto the screen loses thin pen strokes,
        # so draw a copy made at the on-screen size (cached until the zoom changes).
        transform = painter.worldTransform()
        target = (max(1, round(self._w * transform.m11())), max(1, round(self._h * transform.m22())))
        if self._scaled is None or self._scaled.size().toTuple() != target:
            self._scaled = self.image.scaled(
                *target, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(0, 0, self._w, self._h), self._scaled)


class CoverItem(SignItem):
    """A white box. Hides what's under it on the page; doesn't delete it."""

    KIND = ItemKind.COVER

    def __init__(self, w: float = 120.0, h: float = 24.0) -> None:
        super().__init__(w, h)
        self.colour = (255, 255, 255)
        self.setToolTip("Cover-up box: hides what's under it, but the text can still be copied.")

    def to_fill(self, page: int) -> FillItem:
        return FillItem(ItemKind.COVER, page, self.box(), colour=self.colour)

    def paint_content(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*self.colour))
        painter.drawRect(QRectF(0, 0, self._w, self._h))
        if not self.isSelected():  # a faint outline so it can be found on a white page
            scale = max(painter.worldTransform().m11(), 0.05)
            painter.setPen(QPen(QColor(0, 0, 0, 60), 1 / scale, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, self._w, self._h))
