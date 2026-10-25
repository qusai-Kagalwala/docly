"""Typing text for Fill & Sign: on the page itself, and in the side panel.

* :class:`UnsupportedHighlighter` underlines characters the built-in PDF
  font can't print (e.g. Hindi, emoji) with a red squiggle, like a spelling
  mistake, so you see *which* character is the problem.
* :class:`InlineTextEditor` opens over a text item when you double-click
  it (or place a new one) so you type where the text will print.

Desktop note: the inline editor is a normal text box placed over the
``QGraphicsView``'s viewport — the *overlay* pattern again. Each keystroke
goes through the page's undoable ``change_item`` (merged into one undo
step), so the item, the side panel and the editor stay in sync.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QKeyEvent,
    QSyntaxHighlighter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QGraphicsView, QPlainTextEdit

from docly.core.helvetica import ASCENT
from docly.core.pdf_fill import LINE_HEIGHT, TEXT_TOP_PAD, can_print
from docly.ui.sign.items import TextItem

EDGE = 3  # px around the text so the caret isn't clipped


class UnsupportedHighlighter(QSyntaxHighlighter):
    """Red wavy underline under characters the PDF font can't print."""

    def __init__(self, document: QTextDocument, colour: QColor) -> None:
        super().__init__(document)
        self._format = QTextCharFormat()
        self._format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        self._format.setUnderlineColor(colour)

    def set_colour(self, colour: QColor) -> None:
        self._format.setUnderlineColor(colour)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for index, ch in enumerate(text):
            if not can_print(ch):
                self.setFormat(index, 1, self._format)


def count_text(text: str) -> str:
    """"12 characters · 2 lines" for the panel's counter."""
    chars = len(text.replace("\n", ""))
    lines = text.count("\n") + 1 if text else 0
    words = f"{chars} character" + ("" if chars == 1 else "s")
    return words if lines <= 1 else f"{words} · {lines} lines"


class InlineTextEditor(QPlainTextEdit):
    """Edits a :class:`TextItem` in place.

    Enter adds a line; Esc puts the text back as it was; Ctrl+Enter, Tab or
    clicking elsewhere finishes.

    Signals:
        textEdited(str): every change (the page applies it to the item).
        finished(bool): closed; ``False`` if cancelled with Esc.
    """

    textEdited = Signal(str)
    finished = Signal(bool)

    def __init__(self, view: QGraphicsView, item: TextItem, warn: QColor) -> None:
        super().__init__(view.viewport())
        self.setObjectName("InlineTextEditor")
        self.view, self.item = view, item
        self.original = item.text
        self._closing = False
        self._formatting = False  # our own font/line-height changes aren't typing
        self._line_px = -1.0
        self._blocks = 0
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)
        self.setAccessibleName("Text on the page")
        self.document().setDocumentMargin(0)
        r, g, b = item.colour
        # Per-item ink colour (rgb(), not a theme colour); the page shows through.
        self.setStyleSheet(
            "QPlainTextEdit#InlineTextEditor { background: transparent; border: none; padding: 0;"
            f" color: rgb({r}, {g}, {b}); }}"
        )
        self.highlighter = UnsupportedHighlighter(self.document(), warn)
        self.setPlainText(item.text)
        self.selectAll()
        self.textChanged.connect(self._on_text)
        item.edited.connect(self.reposition)
        view.horizontalScrollBar().valueChanged.connect(self.reposition)
        view.verticalScrollBar().valueChanged.connect(self.reposition)
        view.viewport().installEventFilter(self)
        item.set_editing(True)
        self.reposition()
        self.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    # ----- geometry ---------------------------------------------------------
    def zoom(self) -> float:
        return max(self.view.transform().m11(), 0.05)

    def reposition(self, *_args: object) -> None:
        if self._closing:
            return
        zoom = self.zoom()
        font = QFont("Arial")
        font.setPixelSize(max(4, round(self.item.font_size * zoom)))
        self._formatting = True
        try:
            if font != self.font():
                self.setFont(font)
            self._set_line_height(self.item.font_size * LINE_HEIGHT * zoom)
        finally:
            self._formatting = False
        # The item's own box (its bounding rect also holds the resize handle).
        box = self.item.mapRectToScene(QRectF(0, 0, *self.item.size))
        rect = self.view.mapFromScene(box).boundingRect()
        # Line the editor's first baseline up with where the PDF prints it.
        fs = self.item.font_size
        baseline = rect.y() + (fs * TEXT_TOP_PAD + fs * ASCENT / 1000.0) * zoom
        top = round(baseline - EDGE - self._first_baseline())
        self.setViewportMargins(0, EDGE, EDGE, 0)
        self.setGeometry(QRect(rect.x(), top, rect.width() + EDGE + 12, rect.bottom() + 2 * EDGE - top))

    def _first_baseline(self) -> float:
        """Distance from the top of the text area to the first line's baseline."""
        block = self.document().firstBlock()
        layout = block.layout()
        if layout is None or layout.lineCount() == 0:
            return self.fontMetrics().ascent()
        line = layout.lineAt(0)
        return self.blockBoundingGeometry(block).y() + layout.position().y() + line.y() + line.ascent()

    def _set_line_height(self, pixels: float) -> None:
        if abs(pixels - self._line_px) < 0.01 and self.document().blockCount() == self._blocks:
            return
        self._line_px, self._blocks = pixels, self.document().blockCount()
        block_format = QTextBlockFormat()
        block_format.setLineHeight(pixels, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(block_format)

    # ----- editing ----------------------------------------------------------
    def _on_text(self) -> None:
        if self._closing or self._formatting:
            return
        if self.document().blockCount() != self._blocks:  # new line: give it the same spacing
            self.reposition()
        self.textEdited.emit(self.toPlainText())

    def event(self, event: QEvent) -> bool:
        # Claim Esc and Ctrl+Enter before the page's shortcuts (Esc = "select tool").
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Delete):
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_editor(accept=False)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.close_editor(accept=True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:  # e.g. the right-click menu
            self.close_editor(accept=True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self.reposition()
        return False

    def close_editor(self, accept: bool = True) -> None:
        if self._closing:
            return
        if not accept and self.toPlainText() != self.original:
            self.textEdited.emit(self.original)  # merges back into the same undo step
        self._closing = True
        try:
            self.item.edited.disconnect(self.reposition)
        except (RuntimeError, TypeError):
            pass
        try:
            self.item.set_editing(False)
        except RuntimeError:  # item already deleted
            pass
        self.view.viewport().removeEventFilter(self)
        self.hide()
        self.finished.emit(accept)
        self.deleteLater()
