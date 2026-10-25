"""Thumbnail grid: select, drag to reorder, rotate, delete, duplicate.

Desktop concept — *delegate*: a ``QListView`` asks a "delegate" to paint
each item. Ours draws the page thumbnail on a small card with its page
number, so the grid looks the same in light and dark mode.

Drag-to-reorder is handled here (not by Qt's default behaviour) so every
move goes through the undoable :class:`PlanModel` and the drop position
is shown with a clear accent line.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QMimeData, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QAbstractItemView, QListView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from docly.core.pdf_ops import PageRef
from docly.ui.icons import make_icon
from docly.ui.pdf.plan_model import PAGE_REF_ROLE, PlanModel
from docly.ui.pdf.thumbnails import ThumbnailCache, rotated
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.drop_zone import paths_from_mime

CELL = QSize(150, 196)
THUMB_BOX = QSize(124, 150)
MIME_ROWS = "application/x-docly-page-rows"


class PageDelegate(QStyledItemDelegate):
    """Paints one page: thumbnail, number, and which file it came from."""

    def __init__(self, grid: PageGrid) -> None:
        super().__init__(grid)
        self._grid = grid

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return CELL

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        tokens = self._grid.tokens
        ref: PageRef | None = index.data(PAGE_REF_ROLE)
        if ref is None:
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        cell = QRectF(option.rect).adjusted(5, 5, -5, -5)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected or hovered:
            fill = QColor(tokens.accent)
            fill.setAlpha(46 if selected else 18)
            painter.setPen(QPen(QColor(tokens.accent), 2) if selected else Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(cell, 8, 8)

        box = QRectF(
            cell.center().x() - THUMB_BOX.width() / 2, cell.top() + 8, THUMB_BOX.width(), THUMB_BOX.height()
        )
        image = self._grid.thumbnail_for(ref)
        if image is not None and not image.isNull():
            scaled = image.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, scaled.width(), scaled.height())
            target.moveCenter(box.center())
            painter.setPen(QPen(QColor(tokens.border), 1))
            painter.setBrush(QColor("white"))
            painter.drawRect(target.adjusted(-0.5, -0.5, 0.5, 0.5))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, image)
        else:
            placeholder = QRectF(0, 0, box.width() * 0.78, box.height())
            placeholder.moveCenter(box.center())
            painter.setPen(QPen(QColor(tokens.border), 1, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(tokens.surface_alt))
            painter.drawRoundedRect(placeholder, 4, 4)
            painter.setPen(QColor(tokens.text_muted))
            text = "No preview" if self._grid.thumbnail_failed(ref) else "…"
            painter.drawText(placeholder, Qt.AlignmentFlag.AlignCenter, text)

        label_rect = QRectF(cell.left(), box.bottom() + 6, cell.width(), 18)
        painter.setPen(QColor(tokens.text))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        number = str(index.row() + 1)
        if ref.rotate:
            number += f"  · {ref.rotate}°"
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, number)
        source_label = self._grid.source_label(ref)
        if source_label:
            font.setBold(False)
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
            painter.setFont(font)
            painter.setPen(QColor(tokens.text_muted))
            caption = QRectF(cell.left() + 4, label_rect.bottom(), cell.width() - 8, 16)
            elided = painter.fontMetrics().elidedText(source_label, Qt.TextElideMode.ElideMiddle, int(caption.width()))
            painter.drawText(caption, Qt.AlignmentFlag.AlignCenter, elided)
        painter.restore()


class PageGrid(QListView):
    """Grid of page thumbnails backed by a :class:`PlanModel`.

    Signals:
        filesDropped(object, int): local file paths dropped from Explorer,
            and the row to insert them at.
        message(str): something to tell the user (e.g. "keep one page").
        extractRequested(object): rows the user wants saved as a new PDF.
    """

    filesDropped = Signal(object, int)
    message = Signal(str)
    extractRequested = Signal(object)

    def __init__(
        self,
        model: PlanModel,
        thumbnails: ThumbnailCache,
        theme: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageGrid")
        self.plan_model = model
        self.thumbnails = thumbnails
        self.tokens: Tokens = theme.tokens
        self._source_labels: Callable[[PageRef], str] = lambda _ref: ""
        self._drop_gap: int | None = None  # gap index shown while dragging

        self.setModel(model)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)  # we handle moves ourselves
        self.setUniformItemSizes(True)
        self.setGridSize(CELL)
        self.setSpacing(0)
        self.setWrapping(True)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(PageDelegate(self))
        self.setAccessibleName("Pages")

        self._build_actions()
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(30)
        self._request_timer.timeout.connect(self.request_thumbnails)

        model.modelReset.connect(self._schedule_request)
        model.selectionWanted.connect(self.select_rows)
        thumbnails.thumbnailReady.connect(self._on_thumbnail)
        self.verticalScrollBar().valueChanged.connect(self._schedule_request)
        self.selectionModel().selectionChanged.connect(self._update_actions)
        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    # ----- public ---------------------------------------------------------
    def set_source_labels(self, fn: Callable[[PageRef], str]) -> None:
        """How to caption each page with its file (empty for one file)."""
        self._source_labels = fn
        self.viewport().update()

    def source_label(self, ref: PageRef) -> str:
        return self._source_labels(ref)

    def thumbnail_for(self, ref: PageRef):  # -> QImage | None
        image = self.thumbnails.get((ref.source, ref.page))
        return rotated(image, ref.rotate) if image is not None else None

    def thumbnail_failed(self, ref: PageRef) -> bool:
        return self.thumbnails.failed((ref.source, ref.page))

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedIndexes())

    def select_rows(self, rows: list[int]) -> None:
        selection = self.selectionModel()
        selection.clearSelection()
        for row in rows:
            index = self.plan_model.index(row)
            selection.select(index, selection.SelectionFlag.Select)
        if rows:
            current = self.plan_model.index(rows[-1])
            selection.setCurrentIndex(current, selection.SelectionFlag.NoUpdate)
            self.scrollTo(current)
        self._update_actions()

    def visible_rows(self) -> list[int]:
        area = self.viewport().rect()
        return [r for r in range(self.plan_model.rowCount()) if self.visualRect(self.plan_model.index(r)).intersects(area)]

    def request_thumbnails(self) -> None:
        """Ask for missing thumbnails: what's on screen first, then the rest."""
        plan = self.plan_model.plan
        visible = self.visible_rows()
        order = visible + [r for r in range(len(plan)) if r not in set(visible)]
        self.thumbnails.request([(plan[r].source, plan[r].page) for r in order])

    # ----- actions --------------------------------------------------------
    def rotate_selected(self, angle: int) -> None:
        self.plan_model.rotate(self.selected_rows(), angle)

    def delete_selected(self) -> None:
        rows = self.selected_rows()
        if rows and not self.plan_model.delete(rows):
            self.message.emit("Keep at least one page. To start over, use Clear.")

    def duplicate_selected(self) -> None:
        self.plan_model.duplicate(self.selected_rows())

    def _build_actions(self) -> None:
        def make(text: str, shortcut: QKeySequence | str | None, slot: Callable[[], None], icon: str = "") -> QAction:
            action = QAction(text, self)
            action.setObjectName(f"action_{text.split()[0].lower()}")
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(slot)
            action.setData(icon)
            self.addAction(action)
            return action

        self.rotate_left_action = make("Turn left", "Ctrl+Shift+R", lambda: self.rotate_selected(-90), "rotate-ccw")
        self.rotate_right_action = make("Turn right", "Ctrl+R", lambda: self.rotate_selected(90), "rotate-cw")
        self.duplicate_action = make("Duplicate", "Ctrl+D", self.duplicate_selected, "copy")
        self.extract_action = make(
            "Save selected as new PDF…", None, lambda: self.extractRequested.emit(self.selected_rows())
        )
        self.delete_action = make("Delete", QKeySequence.StandardKey.Delete, self.delete_selected, "trash-2")
        self.select_all_action = make("Select all", QKeySequence.StandardKey.SelectAll, self.selectAll)
        undo = self.plan_model.undo_stack
        self.undo_action = make("Undo", QKeySequence.StandardKey.Undo, undo.undo, "undo-2")
        self.redo_action = make("Redo", QKeySequence.StandardKey.Redo, undo.redo, "redo-2")
        undo.canUndoChanged.connect(self.undo_action.setEnabled)
        undo.canRedoChanged.connect(self.redo_action.setEnabled)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.selection_actions = [
            self.rotate_left_action,
            self.rotate_right_action,
            self.duplicate_action,
            self.extract_action,
            self.delete_action,
        ]
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        has_selection = bool(self.selectionModel().selectedIndexes()) if self.selectionModel() else False
        for action in self.selection_actions:
            action.setEnabled(has_selection)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        index = self.indexAt(event.pos())
        if index.isValid() and index.row() not in self.selected_rows():
            self.select_rows([index.row()])
        if not self.selected_rows():
            return
        menu = QMenu(self)
        for action in (self.rotate_left_action, self.rotate_right_action, self.duplicate_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.extract_action)
        menu.addSeparator()
        menu.addAction(self.delete_action)
        menu.exec(event.globalPos())

    # ----- drag & drop ----------------------------------------------------
    def startDrag(self, supported: Qt.DropAction) -> None:  # noqa: N802
        rows = self.selected_rows()
        if not rows:
            return
        mime = QMimeData()
        mime.setData(MIME_ROWS, ",".join(map(str, rows)).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        first = self.thumbnail_for(self.plan_model.ref(rows[0]))
        if first is not None and not first.isNull():
            pixmap = QPixmap.fromImage(first).scaled(
                72, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)
        self._set_drop_gap(None)

    def gap_at(self, pos: QPoint) -> int:
        """The gap (0 … rows) a drop at ``pos`` (viewport coordinates) goes into."""
        count = self.plan_model.rowCount()
        if count == 0:
            return 0
        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            return index.row() + (1 if pos.x() > rect.center().x() else 0)
        # Between or after items: nearest item on the same row, else the end.
        best, best_distance = count, None
        for row in range(count):
            rect = self.visualRect(self.plan_model.index(row))
            if rect.top() <= pos.y() <= rect.bottom():
                distance = abs(rect.center().x() - pos.x())
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best = row + (1 if pos.x() > rect.center().x() else 0)
        return best

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_ROWS) or paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if not (mime.hasFormat(MIME_ROWS) or paths_from_mime(mime)):
            event.ignore()
            return
        self._set_drop_gap(self.gap_at(event.position().toPoint()))
        self._autoscroll(event.position().toPoint())
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drop_gap(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        gap = self.gap_at(event.position().toPoint())
        self._set_drop_gap(None)
        if mime.hasFormat(MIME_ROWS) and event.source() is self:
            rows = [int(r) for r in bytes(mime.data(MIME_ROWS).data()).decode().split(",") if r.isdigit()]
            # Our startDrag never deletes rows after the drag, so the move
            # below is the only change.
            self.plan_model.move(rows, gap)
            event.accept()
            return
        paths = paths_from_mime(mime)
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths, gap)
            return
        event.ignore()

    def _autoscroll(self, pos: QPoint) -> None:
        margin = 30
        bar = self.verticalScrollBar()
        if pos.y() < margin:
            bar.setValue(bar.value() - 12)
        elif pos.y() > self.viewport().height() - margin:
            bar.setValue(bar.value() + 12)

    def _set_drop_gap(self, gap: int | None) -> None:
        if gap != self._drop_gap:
            self._drop_gap = gap
            self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._drop_gap is None or self.plan_model.rowCount() == 0:
            return
        line = self._gap_line(self._drop_gap)
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(self.tokens.accent), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(line.topLeft(), line.bottomLeft())
        painter.end()

    def _gap_line(self, gap: int) -> QRect:
        count = self.plan_model.rowCount()
        if gap < count:
            rect = self.visualRect(self.plan_model.index(gap))
            return QRect(rect.left() + 2, rect.top() + 8, 0, rect.height() - 16)
        rect = self.visualRect(self.plan_model.index(count - 1))
        return QRect(rect.right() - 2, rect.top() + 8, 0, rect.height() - 16)

    # ----- internals ------------------------------------------------------
    def _schedule_request(self, *_args: object) -> None:
        self._request_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self._schedule_request()

    def _on_thumbnail(self, _key: object) -> None:
        self.viewport().update()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self.tokens = tokens
        for action in self.actions():
            icon = action.data()
            if icon:
                action.setIcon(make_icon(icon, tokens.text, 18, self.devicePixelRatioF()))
        self.viewport().update()
