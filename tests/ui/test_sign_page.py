"""End-to-end tests for the Fill & Sign page."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import QPointF, Qt

from docly.core.pdf_fill import BLUE_INK, COVER_WARNING, ItemKind
from docly.ui.pages.sign_page import SignPage, prepare_signature
from docly.ui.sign.items import CoverItem, ImageItem, MarkItem, TextItem
from tests.core import images, pdfs

TIMEOUT = 15_000


@pytest.fixture
def page(qtbot, theme_manager, bundled_presets) -> Iterator[SignPage]:
    widget = SignPage(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(widget)
    widget.resize(1100, 720)
    widget.show()
    qtbot.waitExposed(widget)
    yield widget


@pytest.fixture
def form(tmp_path: Path) -> Path:
    return pdfs.write_pdf(tmp_path / "form.pdf", ["p1", "p2", "p3"])


def open_form(qtbot, page: SignPage, path: Path, pages: int = 3) -> None:
    page.open_file(path)
    qtbot.waitUntil(lambda: page.source is not None and len(page.page_sizes) == pages, timeout=TIMEOUT)
    qtbot.waitUntil(lambda: page.scene_for(page.current).rendered, timeout=TIMEOUT)


def create(qtbot, page: SignPage) -> bytes:
    page.create_pdf()
    qtbot.waitUntil(lambda: bool(page.result_card.results), timeout=TIMEOUT)
    return page.result_card.results[0].data


def signature_png() -> bytes:
    return prepare_signature(images.encode(images.signature_photo(), "JPEG"))


# ----------------------------------------------------------------------
def test_starts_empty(page: SignPage) -> None:
    assert page.stack.currentWidget() is page.drop_zone
    assert not page.result_card.create_button.isEnabled()
    assert page.panel.hint.isVisibleTo(page.panel)


def test_open_and_navigate(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    assert page.stack.currentWidget() is page.workspace
    assert page.page_label.text() == "Page 1 of 3"
    assert not page.prev_button.isEnabled() and page.next_button.isEnabled()
    page.next_button.click()
    qtbot.waitUntil(lambda: page.scene_for(1).rendered, timeout=TIMEOUT)
    assert page.page_label.text() == "Page 2 of 3"
    assert page.view.scene() is page.scene_for(1)
    assert page.scene_for(0).page_rect.width() == pytest.approx(595)


def test_place_items_and_create(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    text = page.place("text", QPointF(72, 100))
    assert isinstance(text, TextItem) and text.isSelected()
    assert page.tool == "select"  # one item per click, then back to selecting
    page.change_item(text, "text", "Qusai Kagalwala")
    page.change_item(text, "colour", BLUE_INK)
    page.place("date", QPointF(400, 100))
    page.show_page(2)
    tick = page.place("tick", QPointF(100, 300))
    assert isinstance(tick, MarkItem) and tick.pos() == QPointF(100 - 7, 300 - 7)  # centred on the click
    assert page.result_card.create_button.isEnabled()

    data = create(qtbot, page)
    assert page.result_card.results[0].suggested_name == "form_signed.pdf"
    assert pdfs.labels_of(data) == ["p1", "p2", "p3"]
    with pikepdf.open(io.BytesIO(data)) as pdf:
        first = pdf.pages[0]
        first.contents_coalesce()
        content = first.obj.Contents.read_bytes()
        assert b"(Qusai Kagalwala) Tj" in content
        third = pdf.pages[2]
        third.contents_coalesce()
        assert b"\nS\n" in third.obj.Contents.read_bytes()


def test_undo_redo_add_move_edit(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    text = page.place("text", QPointF(72, 100))
    page.change_item(text, "text", "Hello")
    page.change_item(text, "text", "Hello world")  # typing merges into one step
    assert page.undo.count() == 2
    page.nudge(10, 0)
    page.nudge(10, 0)  # arrow nudges merge too
    assert text.pos().x() == pytest.approx(92)
    page.undo.undo()
    assert text.pos().x() == pytest.approx(72)
    page.undo.undo()
    assert text.text == "Your text"
    page.undo.undo()
    assert text.scene() is None  # the add was undone
    page.undo.redo()
    assert text.scene() is page.scene_for(0)


def test_delete(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    item = page.place("cross", QPointF(100, 100))
    page.delete_selected()
    assert item.scene() is None
    assert page.panel.item is None
    page.undo.undo()
    assert item.scene() is not None


def test_items_stay_on_the_page(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    item = page.place("cover", QPointF(500, 800))
    item.setPos(5000, 5000)
    assert item.pos().x() < 595 and item.pos().y() < 842


def test_resizing_text_changes_font_size(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    text = page.place("text", QPointF(72, 100))
    start = text.font_size
    text._press_size = text.size
    text._press_state = text.state()
    w, h = text.size
    text.resize_to(w * 2, h * 2)
    assert text.font_size == pytest.approx(start * 2, abs=0.2)


def test_panel_edits_selected_item(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    date_item = page.place("date", QPointF(72, 100))
    assert page.panel.date_row.isVisibleTo(page.panel) and not page.panel.text_edit.isVisibleTo(page.panel)
    page.panel.date_format.setCurrentText("YYYY-MM-DD")
    assert date_item.text.count("-") == 2 and date_item.text[:2] == "20"
    page.panel.size.setValue(20)
    assert date_item.font_size == 20
    page.panel.ink.valueChanged.emit("blue")
    assert date_item.colour == BLUE_INK


def test_unsupported_text_warns_and_create_explains(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    page.place("text", QPointF(72, 100))
    page.panel.text_edit.setPlainText("₹ 500")
    assert page.panel.text_warning.isVisibleTo(page.panel) and "₹" in page.panel.text_warning.text()
    page.create_pdf()
    qtbot.waitUntil(lambda: page.result_card.title.text() == "Couldn't create the PDF", timeout=TIMEOUT)
    assert "can't be printed" in page.result_card.subtitle.text()


def test_signature_from_file_and_last_result(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    page.load_signature(images.encode(images.signature_photo(), "JPEG"))  # a photo of ink on paper
    qtbot.waitUntil(lambda: page.signature_png is not None, timeout=TIMEOUT)
    assert page.tool == "signature"
    item = page.place("signature", QPointF(350, 700))
    assert isinstance(item, ImageItem)
    assert item.image.hasAlphaChannel()  # paper made see-through
    page.set_last_signature(images.encode(images.signature_like(300, 100), "PNG"))
    page.signature_png = None
    page.use_last_signature()
    qtbot.waitUntil(lambda: page.signature_png is not None, timeout=TIMEOUT)
    data = create(qtbot, page)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        xobjects = pdf.pages[0].obj.Resources.XObject
        image = xobjects[next(k for k in xobjects.keys() if str(k).startswith("/DoclyIm"))]
        assert pikepdf.Name.SMask in image


def test_cover_warns(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    cover = page.place("cover", QPointF(72, 100))
    assert isinstance(cover, CoverItem)
    assert page.panel.cover_note.isVisibleTo(page.panel)
    create(qtbot, page)
    assert COVER_WARNING in page.result_card.notes.text()


def test_photo_of_a_form_becomes_a_page(qtbot, page: SignPage, tmp_path: Path) -> None:
    photo = images.save(images.photo_like(1000, 1400), tmp_path / "paper form.jpg")
    open_form(qtbot, page, photo, pages=1)
    page.place("tick", QPointF(100, 100))
    data = create(qtbot, page)
    assert page.result_card.results[0].suggested_name == "paper form_signed.pdf"
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.pages) == 1


def test_password_protected_form(qtbot, page: SignPage, tmp_path: Path, monkeypatch) -> None:
    locked = pdfs.write_pdf(tmp_path / "locked.pdf", ["secret"], password="pw")
    answers = iter(["nope", "pw"])
    monkeypatch.setattr(page, "ask_password", lambda name, wrong: next(answers))
    open_form(qtbot, page, locked, pages=1)  # rendering needs the password too
    page.place("tick", QPointF(100, 100))
    data = create(qtbot, page)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert not pdf.is_encrypted


def test_new_document_clears_items_and_undo(qtbot, page: SignPage, form: Path, tmp_path: Path) -> None:
    open_form(qtbot, page, form)
    page.place("tick", QPointF(100, 100))
    other = pdfs.write_pdf(tmp_path / "other.pdf", ["x"])
    page.open_file(other)
    qtbot.waitUntil(lambda: page.source is not None and page.source.name == "other.pdf", timeout=TIMEOUT)
    assert page.all_items() == [] and page.undo.count() == 0


def test_shrink_applies(qtbot, page: SignPage, tmp_path: Path) -> None:
    photo = images.save(images.photo_like(1240, 1754), tmp_path / "scan.jpg", quality=92)
    open_form(qtbot, page, photo, pages=1)
    page.place("tick", QPointF(100, 100))
    page.compress_card.select("custom")
    page.compress_card.custom_kb.setValue(120)
    create(qtbot, page)
    result = page.result_card.results[0]
    assert result.met_target and result.size_bytes <= 120_000


def test_zoom_and_tools(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    start = page.view.zoom
    page.zoom_in_button.click()
    assert page.view.zoom > start and not page.view.fit_width
    page.fit_button.click()
    assert page.view.fit_width
    page.tool_buttons["text"].click()
    assert page.tool == "text" and page.view.placing
    qtbot.keyClick(page.view, Qt.Key.Key_Escape)
    assert page.tool == "select" and not page.view.placing


def test_side_column_fits(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    page.place("text", QPointF(72, 100))
    qtbot.wait(50)
    assert page.side_scroll.widget().minimumSizeHint().width() <= page.side_scroll.viewport().width()


def test_main_window_wires_signature_page(main_window) -> None:
    signature, sign = main_window.page("signature"), main_window.page("sign")
    signature.signatureMade.emit(b"png-bytes")
    assert sign.last_signature == b"png-bytes"
    assert "sign" in main_window.page("home").feature_cards


def test_marks_kind(qtbot, page: SignPage, form: Path) -> None:
    open_form(qtbot, page, form)
    assert page.place("tick", QPointF(50, 50)).to_fill(0).kind == ItemKind.TICK
    assert page.place("cross", QPointF(90, 50)).to_fill(0).kind == ItemKind.CROSS


def test_prepare_signature_keeps_existing_transparency() -> None:
    png = signature_png()
    from PIL import Image

    assert Image.open(io.BytesIO(png)).mode == "RGBA"
