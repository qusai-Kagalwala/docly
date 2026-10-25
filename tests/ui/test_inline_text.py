"""Tests for typing text on the page in Fill & Sign, and the panel's text box."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QTextCharFormat

from docly.ui.pages.sign_page import SignPage
from docly.ui.sign.items import TextItem
from docly.ui.sign.text_editing import InlineTextEditor, count_text
from tests.core import pdfs

TIMEOUT = 15_000


@pytest.fixture
def page(qtbot, theme_manager, bundled_presets, tmp_path: Path) -> Iterator[SignPage]:
    widget = SignPage(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(widget)
    widget.resize(1100, 720)
    widget.show()
    qtbot.waitExposed(widget)
    widget.open_file(pdfs.write_pdf(tmp_path / "form.pdf", ["p1", "p2"]))
    qtbot.waitUntil(lambda: widget.source is not None and len(widget.page_sizes) == 2, timeout=TIMEOUT)
    yield widget


def place_text(page: SignPage) -> tuple[TextItem, InlineTextEditor]:
    item = page.place("text", QPointF(60, 80))
    assert isinstance(item, TextItem) and page.inline_editor is not None
    return item, page.inline_editor


def test_placing_text_opens_the_editor_on_the_page(page: SignPage) -> None:
    item, editor = place_text(page)
    assert editor.isVisible() and editor.parent() is page.view.viewport()
    assert editor.textCursor().selectedText() == item.text  # type over the default
    assert item.editing  # the editor draws the text while open
    item_rect = page.view.mapFromScene(item.sceneBoundingRect()).boundingRect()
    assert abs(editor.geometry().left() - item_rect.left()) <= 4


def test_typing_updates_item_and_panel_in_one_undo_step(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    undo_before = page.undo.count()
    qtbot.keyClicks(editor, "Qusai")
    assert item.text == "Qusai"
    assert page.panel.text_edit.toPlainText() == "Qusai"
    assert page.panel.counter.text() == "5 characters"
    assert page.undo.count() == undo_before + 1  # every letter merged into one step
    editor.close_editor(accept=True)
    assert page.inline_editor is None and not item.editing
    page.undo.undo()
    assert item.text == "Your text"


def test_escape_puts_text_back(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    qtbot.keyClicks(editor, "oops")
    qtbot.keyClick(editor, Qt.Key.Key_Escape)
    assert item.text == "Your text" and page.inline_editor is None
    assert page.tool == "select"


def test_enter_adds_a_line_and_ctrl_enter_finishes(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    qtbot.keyClicks(editor, "Line one")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "Line two")
    assert item.text == "Line one\nLine two"
    qtbot.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert page.inline_editor is None


def test_delete_key_edits_text_not_the_item(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    qtbot.keyClick(editor, Qt.Key.Key_Delete)
    assert item.scene() is not None and item.text == ""


def test_double_click_opens_editor(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    editor.close_editor()
    centre = page.view.mapFromScene(item.sceneBoundingRect().center())
    qtbot.mouseDClick(page.view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    assert page.inline_editor is not None and page.inline_editor.item is item


def test_dates_are_not_typed(qtbot, page: SignPage) -> None:
    item = page.place("date", QPointF(60, 200))
    assert page.inline_editor is None
    centre = page.view.mapFromScene(item.sceneBoundingRect().center())
    qtbot.mouseDClick(page.view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    assert page.inline_editor is None


def test_switching_page_closes_editor(page: SignPage) -> None:
    item, _editor = place_text(page)
    page.show_page(1)
    assert page.inline_editor is None and not item.editing


def test_unsupported_letters_are_underlined(qtbot, page: SignPage) -> None:
    item, editor = place_text(page)
    editor.insertPlainText("Rs ₹5")  # QTest can only "type" Latin-1 keys
    block = editor.document().firstBlock()
    styles = [r.format.underlineStyle() for r in block.layout().formats()]
    assert QTextCharFormat.UnderlineStyle.WaveUnderline in styles
    assert page.panel.text_warning.isVisibleTo(page.panel) and "₹" in page.panel.text_warning.text()


@pytest.mark.parametrize(("text", "shown"), [("", "0 characters"), ("A", "1 character"), ("ab\ncd", "4 characters · 2 lines")])
def test_count_text(text: str, shown: str) -> None:
    assert count_text(text) == shown
