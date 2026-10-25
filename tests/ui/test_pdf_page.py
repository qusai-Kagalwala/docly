"""End-to-end tests for the PDF page (grid, edits, passwords, save, split)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from docly.core.pdf_ops import PageRef
from docly.ui.pages.pdf_page import PdfPage
from tests.core import images, pdfs

TIMEOUT = 15_000


@pytest.fixture
def page(qtbot, theme_manager) -> Iterator[PdfPage]:
    widget = PdfPage(theme_manager)
    qtbot.addWidget(widget)
    widget.resize(1100, 720)
    widget.show()
    qtbot.waitExposed(widget)
    yield widget
    widget.thumbnails.shutdown()


@pytest.fixture
def form(tmp_path: Path) -> Path:
    return pdfs.write_pdf(tmp_path / "form.pdf", ["f1", "f2", "f3", "f4"])


@pytest.fixture
def cert(tmp_path: Path) -> Path:
    return pdfs.write_pdf(tmp_path / "cert.pdf", ["c1"])


def add(qtbot, page: PdfPage, *paths: Path, pages: int) -> None:
    page.add_files(list(paths))
    qtbot.waitUntil(lambda: len(page.model) == pages and page._opening is None, timeout=TIMEOUT)


def build(qtbot, page: PdfPage) -> bytes:
    page.create_pdf()
    qtbot.waitUntil(lambda: bool(page.result_card.results), timeout=TIMEOUT)
    return page.result_card.results[0].data


def test_starts_on_drop_zone(page: PdfPage) -> None:
    assert page.stack.currentWidget() is page.drop_zone
    assert not page.result_card.create_button.isEnabled()
    assert not page.split_card.isVisibleTo(page)


def test_merge_files_and_photo(qtbot, page: PdfPage, form: Path, cert: Path, tmp_path: Path) -> None:
    photo = images.save(images.photo_like(600, 800), tmp_path / "id.jpg")
    add(qtbot, page, form, cert, photo, pages=6)
    assert page.stack.currentWidget() is page.workspace
    assert [r.name for r in page.file_list.rows] == ["form.pdf", "cert.pdf", "id.jpg"]
    assert page.page_size_card.isVisibleTo(page)
    assert page.grid.source_label(page.model.ref(4)) == "cert.pdf"  # several files: pages are captioned
    data = build(qtbot, page)
    assert pdfs.labels_of(data) == ["f1", "f2", "f3", "f4", "c1", ""]
    assert page.result_card.results[0].suggested_name == "form_merged.pdf"
    page.thumbnails.request([])
    qtbot.waitUntil(lambda: page.thumbnails.get((0, 0)) is not None, timeout=TIMEOUT)


def test_edit_then_undo(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    assert page.grid.source_label(page.model.ref(0)) == ""  # one file: no captions
    page.grid.select_rows([0])
    page.grid.rotate_right_action.trigger()
    page.grid.select_rows([2])
    page.grid.delete_action.trigger()
    page.model.move([3 - 1], 0)  # f4 to the front
    data = build(qtbot, page)
    assert pdfs.labels_of(data) == ["f4", "f1", "f2"]
    assert pdfs.rotations_of(data) == [0, 90, 0]
    assert page.result_card.results[0].suggested_name == "form_edited.pdf"

    page.grid.undo_action.trigger()  # undo the move: the result is now out of date
    assert not page.result_card.results
    assert page.result_card.create_button.isVisible()
    page.grid.undo_action.trigger()
    page.grid.undo_action.trigger()
    assert page.model.plan == [PageRef(0, i) for i in range(4)]
    assert not page.grid.undo_action.isEnabled()
    page.grid.redo_action.trigger()
    assert page.model.ref(0).rotate == 90


def test_delete_all_is_refused_with_message(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.grid.selectAll()
    page.grid.delete_selected()
    assert len(page.model) == 4
    assert "at least one page" in page.banner.text()


def test_duplicate_and_extract_selected(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.grid.select_rows([1])
    page.grid.duplicate_action.trigger()
    assert [r.page for r in page.model.plan] == [0, 1, 1, 2, 3]
    assert page.grid.selected_rows() == [2]
    page.extract_rows([0, 4])
    qtbot.waitUntil(lambda: bool(page.result_card.results), timeout=TIMEOUT)
    result = page.result_card.results[0]
    assert pdfs.labels_of(result.data) == ["f1", "f4"]
    assert result.suggested_name == "form_pages-1_5.pdf"


def test_password_prompt_retries_then_opens(qtbot, page: PdfPage, tmp_path: Path, monkeypatch) -> None:
    locked = pdfs.write_pdf(tmp_path / "marks.pdf", ["m1", "m2"], password="right")
    asked: list[tuple[str, bool]] = []
    answers = iter(["wrong", "right"])

    def fake_ask(name: str, wrong: bool) -> str | None:
        asked.append((name, wrong))
        return next(answers)

    monkeypatch.setattr(page, "ask_password", fake_ask)
    add(qtbot, page, locked, pages=2)
    assert asked == [("marks.pdf", False), ("marks.pdf", True)]
    data = build(qtbot, page)
    assert pdfs.labels_of(data) == ["m1", "m2"]
    qtbot.waitUntil(lambda: page.thumbnails.get((0, 0)) is not None, timeout=TIMEOUT)  # preview uses it too


def test_password_skip_moves_on(qtbot, page: PdfPage, tmp_path: Path, cert: Path, monkeypatch) -> None:
    locked = pdfs.write_pdf(tmp_path / "marks.pdf", ["m1"], password="pw")
    monkeypatch.setattr(page, "ask_password", lambda name, wrong: None)
    add(qtbot, page, locked, cert, pages=1)
    assert [r.name for r in page.file_list.rows] == ["cert.pdf"]
    assert "Skipped marks.pdf" in page.banner.text()


def test_bad_files_are_reported_and_others_still_open(qtbot, page: PdfPage, tmp_path: Path, cert: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n garbage")
    notes = tmp_path / "notes.txt"
    notes.write_text("hi", encoding="utf-8")
    page.add_files([notes])
    assert "notes.txt" in page.banner.text()
    add(qtbot, page, broken, cert, pages=1)
    assert page.banner.isVisible()
    assert [r.name for r in page.file_list.rows] == ["cert.pdf"]


def test_save_goes_to_docly_output_and_originals_unchanged(qtbot, page: PdfPage, form: Path) -> None:
    before = hashlib.sha256(form.read_bytes()).hexdigest()
    add(qtbot, page, form, pages=4)
    page.grid.select_rows([0, 1, 2, 3])
    page.grid.rotate_left_action.trigger()
    build(qtbot, page)
    first = page.result_card.save()
    second = page.result_card.save()
    assert first[0] == form.parent / "Docly_Output" / "form_edited.pdf"
    assert second[0].name == "form_edited (2).pdf"  # never overwrites
    assert hashlib.sha256(form.read_bytes()).hexdigest() == before


def test_split_ranges_into_subfolder(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.split_mode.set_value("ranges")
    page.split_mode.valueChanged.emit("ranges")
    assert not page.split_button.isEnabled()
    page.split_ranges.setText("1-2, 9")
    assert not page.split_button.isEnabled()
    assert "9" in page.split_hint.text()
    page.split_ranges.setText("1-2, 3-")
    assert page.split_hint.text() == "Makes 2 PDFs."
    page.split_pdf()
    qtbot.waitUntil(lambda: len(page.result_card.results) == 2, timeout=TIMEOUT)
    assert page.result_card.save_button.text() == "Save all"
    paths = page.result_card.save()
    assert [p.relative_to(form.parent).as_posix() for p in paths] == [
        "Docly_Output/form_split/form_pages-1-2.pdf",
        "Docly_Output/form_split/form_pages-3-4.pdf",
    ]
    assert pdfs.labels_of(paths[1].read_bytes()) == ["f3", "f4"]


def test_split_every_n_follows_grid_order(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.model.move([3], 0)
    page.split_mode.set_value("every")
    page.split_mode.valueChanged.emit("every")
    page.split_every.setValue(3)
    assert page.split_groups() == [[0, 1, 2], [3]]
    page.split_pdf()
    qtbot.waitUntil(lambda: len(page.result_card.results) == 2, timeout=TIMEOUT)
    assert [pdfs.labels_of(r.data) for r in page.result_card.results] == [["f4", "f1", "f2"], ["f3"]]


def test_remove_file_and_clear(qtbot, page: PdfPage, form: Path, cert: Path) -> None:
    add(qtbot, page, form, cert, pages=5)
    page.file_list.remove_buttons[1].click()
    assert page.model.sources_used() == [0]
    page.grid.undo_action.trigger()
    assert page.model.sources_used() == [0, 1]
    page.file_list.remove_buttons[0].click()
    page.file_list.remove_buttons[1].click()  # last file: start over
    assert len(page.model) == 0 and page.sources == []
    assert page.stack.currentWidget() is page.drop_zone
    add(qtbot, page, cert, pages=1)
    page.clear_button.click()
    assert page.stack.currentWidget() is page.drop_zone


def test_files_dropped_on_grid_insert_at_gap(qtbot, page: PdfPage, form: Path, cert: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.grid.filesDropped.emit([cert], 2)
    qtbot.waitUntil(lambda: len(page.model) == 5, timeout=TIMEOUT)
    assert [(r.source, r.page) for r in page.model.plan] == [(0, 0), (0, 1), (1, 0), (0, 2), (0, 3)]


def test_drop_on_page_adds_files(qtbot, page: PdfPage, cert: Path) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(cert))])
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dropEvent(drop)
    qtbot.waitUntil(lambda: len(page.model) == 1, timeout=TIMEOUT)


def test_page_size_for_photos(qtbot, page: PdfPage, tmp_path: Path) -> None:
    photo = images.save(images.photo_like(400, 300), tmp_path / "wide.jpg")
    add(qtbot, page, photo, pages=1)
    page.page_size.set_value("fit")
    page.page_size.valueChanged.emit("fit")
    data = build(qtbot, page)
    import io

    import pikepdf

    with pikepdf.open(io.BytesIO(data)) as pdf:
        box = [float(v) for v in pdf.pages[0].mediabox]
    assert box[2] > box[3]  # page follows the landscape photo


def test_cancel_returns_to_idle(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.result_card.show_busy()
    page.cancel()
    assert page.result_card.create_button.isVisible()
    assert "4 pages arranged" in page.result_card.subtitle.text()


def test_gap_at_positions(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    first = page.grid.visualRect(page.model.index(0))
    assert page.grid.gap_at(QPoint(first.left() + 5, first.center().y())) == 0
    assert page.grid.gap_at(QPoint(first.right() - 5, first.center().y())) == 1
    assert page.grid.gap_at(QPoint(page.grid.viewport().width() - 3, page.grid.viewport().height() - 3)) == 4


def test_selection_actions_follow_selection(qtbot, page: PdfPage, form: Path) -> None:
    add(qtbot, page, form, pages=4)
    page.grid.select_rows([])
    assert not page.grid.delete_action.isEnabled()
    page.grid.select_rows([1, 2])
    assert page.grid.delete_action.isEnabled()
    assert page.selection_label.text() == "2 selected"


class _InternalDrop(QDropEvent):
    """A drop that says it came from the grid itself (real drags set this)."""

    def __init__(self, grid, pos: QPoint, mime: QMimeData) -> None:
        super().__init__(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self._grid = grid

    def source(self):  # noqa: ANN201
        return self._grid


def test_dragging_pages_reorders_with_undo(qtbot, page: PdfPage, form: Path) -> None:
    from docly.ui.pdf.page_grid import MIME_ROWS

    add(qtbot, page, form, pages=4)
    mime = QMimeData()
    mime.setData(MIME_ROWS, b"0,1")
    last = page.grid.visualRect(page.model.index(3))
    event = _InternalDrop(page.grid, QPoint(last.right() - 5, last.center().y()), mime)
    page.grid.dropEvent(event)
    assert [r.page for r in page.model.plan] == [2, 3, 0, 1]
    assert page.grid.selected_rows() == [2, 3]
    assert event.isAccepted()
    page.grid.undo_action.trigger()
    assert [r.page for r in page.model.plan] == [0, 1, 2, 3]