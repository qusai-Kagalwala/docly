"""Options for the selected item: text, size, ink colour, date format."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from docly.core.pdf_fill import BLACK, BLUE_INK, COVER_WARNING, DATE_FORMATS, ItemKind, UnsupportedTextError, check_text
from docly.ui.sign.items import CoverItem, ImageItem, MarkItem, SignItem, TextItem
from docly.ui.sign.text_editing import UnsupportedHighlighter, count_text
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.segmented import SegmentedControl
from docly.ui.widgets.status_badge import Banner

EMPTY_HINT = "Pick a tool above, then click on the page. Click an item to change it; drag its corner to resize."
INKS = {"black": BLACK, "blue": BLUE_INK}


def _row(label: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    line = QHBoxLayout(holder)
    line.setContentsMargins(0, 0, 0, 0)
    text = QLabel(label)
    text.setProperty("role", "body")
    line.addWidget(text)
    line.addStretch(1)
    line.addWidget(widget)
    return holder


class ItemPanel(Card):
    """Edits one selected item. Every change goes through ``changeRequested``
    so the page can make it undoable.

    Signals:
        changeRequested(object, str, object): item, property name, new value.
        deleteRequested()
    """

    changeRequested = Signal(object, str, object)
    deleteRequested = Signal()

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.item: SignItem | None = None
        self._loading = False
        self.title = QLabel("Item")
        self.title.setProperty("role", "section")
        self.body.addWidget(self.title)

        self.hint = QLabel(EMPTY_HINT)
        self.hint.setProperty("role", "caption")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)

        self.text_box = QWidget()
        text_layout = QVBoxLayout(self.text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(76)
        self.text_edit.setAccessibleName("Text")
        self.text_edit.setPlaceholderText("Type here, or double-click the text on the page")
        self.text_edit.setTabChangesFocus(True)
        self.highlighter = UnsupportedHighlighter(self.text_edit.document(), QColor(theme.tokens.danger))
        self.counter = QLabel()
        self.counter.setProperty("role", "caption")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        text_layout.addWidget(self.text_edit)
        text_layout.addWidget(self.counter)
        self.body.addWidget(self.text_box)

        self.text_warning = Banner(theme)
        self.body.addWidget(self.text_warning)
        theme.themeChanged.connect(lambda t: self.highlighter.set_colour(QColor(t.danger)))

        self.date_format = QComboBox()
        self.date_format.setAccessibleName("Date format")
        self.date_format.addItems(list(DATE_FORMATS))
        self.date_row = _row("Format", self.date_format)
        self.body.addWidget(self.date_row)

        self.size = QSpinBox()
        self.size.setAccessibleName("Size")
        self.size.setRange(4, 72)
        self.size.setSuffix(" pt")
        self.size_row = _row("Size", self.size)
        self.body.addWidget(self.size_row)

        self.width = QSpinBox()
        self.width.setAccessibleName("Width")
        self.width.setRange(20, 600)
        self.width.setSuffix(" pt")
        self.width_row = _row("Width", self.width)
        self.body.addWidget(self.width_row)

        self.ink = SegmentedControl([("black", "Black"), ("blue", "Blue")])
        self.ink_row = _row("Ink", self.ink)
        self.body.addWidget(self.ink_row)

        self.cover_note = Banner(theme)
        self.cover_note.show_message(COVER_WARNING, "warning")
        self.body.addWidget(self.cover_note)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Remove this item (Delete key)")
        self.body.addWidget(self.delete_button)

        self.text_edit.textChanged.connect(self._on_text)
        self.date_format.currentTextChanged.connect(lambda v: self._emit("date_style", v))
        self.size.valueChanged.connect(self._on_size)
        self.width.valueChanged.connect(lambda v: self._emit("width", float(v)))
        self.ink.valueChanged.connect(lambda v: self._emit("colour", INKS[v]))
        self.delete_button.clicked.connect(self.deleteRequested)
        self.show_item(None)

    # ----- showing ----------------------------------------------------------
    def show_item(self, item: SignItem | None) -> None:
        if self.item is not None:
            try:
                self.item.edited.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        self.item = item
        if item is not None:
            item.edited.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        item = self.item
        self._loading = True
        try:
            is_text = isinstance(item, TextItem)
            is_date = is_text and item.is_date  # type: ignore[union-attr]
            self.hint.setVisible(item is None)
            self.text_box.setVisible(is_text and not is_date)
            self.date_row.setVisible(is_date)
            self.size_row.setVisible(isinstance(item, (TextItem, MarkItem)))
            self.width_row.setVisible(isinstance(item, ImageItem))
            self.ink_row.setVisible(isinstance(item, (TextItem, MarkItem)))
            self.cover_note.setVisible(isinstance(item, CoverItem))
            self.delete_button.setVisible(item is not None)
            self.text_warning.hide()
            self.title.setText(_title(item))
            if isinstance(item, TextItem):
                if self.text_edit.toPlainText() != item.text:
                    self.text_edit.setPlainText(item.text)
                if item.date_style:
                    self.date_format.setCurrentText(item.date_style)
                self.size.setValue(round(item.font_size))
                self._check(item.text)
            if isinstance(item, MarkItem):
                self.size.setValue(round(item.size[0]))
            if isinstance(item, (TextItem, MarkItem)):
                self.ink.set_value("blue" if item.colour == BLUE_INK else "black")
            if isinstance(item, ImageItem):
                self.width.setValue(round(item.size[0]))
        finally:
            self._loading = False

    # ----- editing ---------------------------------------------------------------
    def _emit(self, name: str, value: object) -> None:
        if not self._loading and self.item is not None:
            self.changeRequested.emit(self.item, name, value)

    def _on_text(self) -> None:
        text = self.text_edit.toPlainText()
        self._check(text)
        self._emit("text", text)

    def _on_size(self, value: int) -> None:
        self._emit("font_size" if isinstance(self.item, TextItem) else "size", float(value))

    def _check(self, text: str) -> None:
        self.counter.setText(count_text(text))
        try:
            check_text(text)
        except UnsupportedTextError as exc:
            self.text_warning.show_message(str(exc), "danger")
            return
        self.text_warning.hide()


def _title(item: SignItem | None) -> str:
    if item is None:
        return "Item"
    if isinstance(item, TextItem):
        return "Date" if item.is_date else "Text"
    if isinstance(item, MarkItem):
        return "Tick" if item.kind == ItemKind.TICK else "Cross"
    if isinstance(item, ImageItem):
        return "Signature"
    return "Cover-up box"
