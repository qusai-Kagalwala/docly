"""The page you place things on: one scene per page, a zoomable view, undo.

Desktop concept — *scene and view*: a ``QGraphicsScene`` holds the page
picture and the items on it; a ``QGraphicsView`` is a zoomable window onto
a scene. Each page of the document has its own scene, and the view simply
switches between them.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QMouseEvent, QPainter, QPixmap, QUndoCommand, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QWidget

from docly.ui.sign.items import SignItem, State, TextItem

ZOOM_STEP = 1.25
MIN_ZOOM, MAX_ZOOM = 0.2, 6.0


class PageScene(QGraphicsScene):
    """One page: a white sheet, its picture (when rendered), and the items.

    Remembers item states when a drag starts, so the finished move or
    resize can be undone as one step (``moveFinished``).
    """

    moveFinished = Signal(object, object)  # {item: state before}, {item: state after}

    def __init__(self, index: int, width: float, height: float) -> None:
        super().__init__()
        self.index = index
        self.page_rect = QRectF(0, 0, width, height)
        margin = 16.0  # a little grey around the sheet
        self.setSceneRect(self.page_rect.adjusted(-margin, -margin, margin, margin))
        self.sheet = QGraphicsRectItem(self.page_rect)
        self.sheet.setBrush(QBrush(QColor("white")))
        self.sheet.setPen(QColor(0, 0, 0, 40))
        self.sheet.setZValue(-2)
        self.addItem(self.sheet)
        self.picture: QGraphicsPixmapItem | None = None
        self._before: dict[SignItem, State] = {}

    @property
    def rendered(self) -> bool:
        return self.picture is not None

    def set_picture(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        if self.picture is None:
            self.picture = QGraphicsPixmapItem()
            self.picture.setZValue(-1)
            self.picture.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.addItem(self.picture)
        self.picture.setPixmap(pixmap)
        # The picture is rendered larger than the page for sharpness; scale it to fit.
        self.picture.setScale(self.page_rect.width() / max(1, pixmap.width()))

    def sign_items(self) -> list[SignItem]:
        return [item for item in self.items(Qt.SortOrder.AscendingOrder) if isinstance(item, SignItem)]

    def add_sign_item(self, item: SignItem) -> None:
        item.page_rect = self.page_rect
        self.addItem(item)

    # ----- undo bookkeeping for drags ---------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802, ANN001
        super().mousePressEvent(event)
        self._before = {item: item.state() for item in self.sign_items() if item.isSelected()}

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802, ANN001
        super().mouseReleaseEvent(event)
        if not self._before:
            return
        after = {item: item.state() for item in self._before}
        changed = {item: state for item, state in self._before.items() if after[item] != state}
        if changed:
            self.moveFinished.emit(changed, {item: after[item] for item in changed})
        self._before = {}


class PageView(QGraphicsView):
    """Shows one :class:`PageScene`; zooms; reports clicks for placing items.

    Signals:
        pageClicked(QPointF): a click on the page where nothing is (scene points).
        zoomChanged(float)
    """

    pageClicked = Signal(QPointF)
    zoomChanged = Signal(float)
    textEditRequested = Signal(object)  # a TextItem was double-clicked

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SignPageView")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.zoom = 1.0
        self.fit_width = True
        self.placing = False  # a tool is active: clicks place items instead of selecting

    def page_scene(self) -> PageScene | None:
        scene = self.scene()
        return scene if isinstance(scene, PageScene) else None

    # ----- zoom ---------------------------------------------------------------
    def set_zoom(self, zoom: float, fit_width: bool = False) -> None:
        self.fit_width = fit_width
        self.zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        self.resetTransform()
        self.scale(self.zoom, self.zoom)
        self.zoomChanged.emit(self.zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom / ZOOM_STEP)

    def fit_page_width(self) -> None:
        scene = self.page_scene()
        if scene is None:
            return
        available = self.viewport().width() - 4
        self.set_zoom(available / scene.sceneRect().width(), fit_width=True)

    def scroll_to_top(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        if self.fit_width:
            self.fit_page_width()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            (self.zoom_in if event.angleDelta().y() > 0 else self.zoom_out)()
            event.accept()
            return
        super().wheelEvent(event)

    # ----- placing ---------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        scene = self.page_scene()
        if self.placing and scene is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if scene.page_rect.contains(point):
                self.pageClicked.emit(point)
                event.accept()
                return
        super().mousePressEvent(event)


    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, TextItem):
            item = item.parentItem()
        if isinstance(item, TextItem) and not item.is_date and event.button() == Qt.MouseButton.LeftButton:
            self.textEditRequested.emit(item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SnapshotCommand(QUndoCommand):
    """Undo/redo by restoring saved item states (moves, resizes, edits)."""

    def __init__(
        self,
        text: str,
        before: dict[SignItem, State],
        after: dict[SignItem, State],
        show: Callable[[SignItem], None],
        merge_key: object | None = None,
    ) -> None:
        super().__init__(text)
        self.before, self.after = before, after
        self._show = show
        self._merge_key = merge_key
        self._first = True

    def id(self) -> int:  # noqa: A003
        return 1 if self._merge_key is not None else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, SnapshotCommand) or other._merge_key != self._merge_key or self._merge_key is None:
            return False
        self.after = other.after  # typing in the same box becomes one undo step
        return True

    def redo(self) -> None:
        if self._first:  # the change already happened on screen
            self._first = False
            return
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)

    def _apply(self, states: dict[SignItem, State]) -> None:
        for item, state in states.items():
            self._show(item)
            item.set_state(state)


class AddRemoveCommand(QUndoCommand):
    """Adding or deleting items (undo does the opposite)."""

    def __init__(
        self, text: str, scene: PageScene, items: list[SignItem], adding: bool, show: Callable[[SignItem], None]
    ) -> None:
        super().__init__(text)
        self.scene, self.items, self.adding = scene, list(items), adding
        self._show = show

    def redo(self) -> None:
        self._set(present=self.adding)

    def undo(self) -> None:
        self._set(present=not self.adding)

    def _set(self, present: bool) -> None:
        for item in self.items:
            if present and item.scene() is None:
                self.scene.add_sign_item(item)
                self._show(item)
            elif not present and item.scene() is self.scene:
                item.setSelected(False)
                self.scene.removeItem(item)
