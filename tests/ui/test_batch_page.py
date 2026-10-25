"""End-to-end tests for the Batch page."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from docly.core.batch import BatchKind, Status
from docly.ui.pages.batch_page import STATUS_TEXT, WAITING, BatchPage
from tests.core import images, pdfs

TIMEOUT = 30_000


@pytest.fixture
def page(qtbot, theme_manager, bundled_presets) -> Iterator[BatchPage]:
    widget = BatchPage(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(widget)
    widget.resize(1100, 720)
    widget.show()
    qtbot.waitExposed(widget)
    yield widget


@pytest.fixture
def photos(tmp_path: Path) -> list[Path]:
    files = [images.save(images.photo_like(700, 900), tmp_path / f"p{i}.jpg") for i in range(3)]
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"nope")
    return [*files, bad]


def run(qtbot, page: BatchPage) -> None:
    page.start()
    qtbot.waitUntil(lambda: page.report is not None and not page.running, timeout=TIMEOUT)


def test_starts_empty(page: BatchPage) -> None:
    assert page.stack.currentWidget() is page.drop_zone
    assert not page.start_button.isEnabled()
    assert page.kind == BatchKind.PHOTO
    assert page.photo_picker.isVisibleTo(page) and not page.sign_picker.isVisibleTo(page)


def test_adding_files_filters_and_dedupes(page: BatchPage, photos: list[Path], tmp_path: Path) -> None:
    pdf = pdfs.write_pdf(tmp_path / "doc.pdf", ["a"])
    page.add_files([*photos, photos[0], pdf])
    assert page.files == photos  # duplicate dropped, PDF skipped in photo mode
    assert "aren't images" in page.banner.text()
    assert page.table.rowCount() == 4 and page.table.item(0, 1).text() == WAITING
    page.table.selectRow(3)
    page.remove_selected()
    assert page.files == photos[:3]
    page.clear()
    assert page.files == [] and page.stack.currentWidget() is page.drop_zone


def test_photo_batch_runs_and_reports(qtbot, page: BatchPage, photos: list[Path]) -> None:
    page.add_files(photos)
    page.photo_picker.select("in-ibps-photo")
    page.frame_person.setChecked(False)
    run(qtbot, page)
    statuses = [page.table.item(row, 1).text() for row in range(4)]
    assert statuses[3] == STATUS_TEXT[Status.FAILED]
    assert all(s in (STATUS_TEXT[Status.READY], STATUS_TEXT[Status.CHECK]) for s in statuses[:3])
    assert "200×230" in page.table.item(0, 2).text()
    assert "failed" in page.summary.text()
    report = page.report
    assert report.report_path.exists() and report.folder.parent.name == "Docly_Output"
    assert page.open_folder_button.isVisible() and page.open_report_button.isVisible()


def test_cancel_stops_after_current_file(qtbot, page: BatchPage, photos: list[Path]) -> None:
    page.add_files(photos)
    page.photo_picker.select("in-ibps-photo")
    page.frame_person.setChecked(False)
    page.start()
    page.cancel()  # before or during the first file
    qtbot.waitUntil(lambda: page.report is not None and not page.running, timeout=TIMEOUT)
    assert page.report.cancelled
    assert page.table.item(3, 1).text() == STATUS_TEXT[Status.NOT_DONE]


def test_signature_mode(qtbot, page: BatchPage, tmp_path: Path) -> None:
    page.mode.set_value("signature")
    page.mode.valueChanged.emit("signature")
    assert page.sign_picker.isVisibleTo(page) and page.sign_options.isVisibleTo(page)
    page.add_files([images.save(images.signature_photo(), tmp_path / "s.jpg")])
    page.sign_picker.select("in-ibps-signature")
    page.black_ink.setChecked(True)
    assert page.settings().clean.black_ink
    run(qtbot, page)
    assert page.table.item(0, 1).text() == STATUS_TEXT[Status.READY]


def test_pdf_mode(qtbot, page: BatchPage, tmp_path: Path, photos: list[Path]) -> None:
    page.add_files(photos)
    page.mode.set_value("pdf")
    page.mode.valueChanged.emit("pdf")
    assert page.files == []  # photos don't fit PDF mode
    assert not page.preset_card.isVisibleTo(page) and page.compress_card.isVisibleTo(page)
    page.add_files([pdfs.write_pdf(tmp_path / "a.pdf", ["a"])])
    page.start()  # no size limit chosen
    assert "size limit" in page.banner.text() and not page.running
    page.compress_card.select("custom")
    page.compress_card.custom_kb.setValue(200)
    run(qtbot, page)
    assert page.table.item(0, 1).text() == STATUS_TEXT[Status.READY]


def test_strict_preset_blocks_background(qtbot, page: BatchPage, photos: list[Path]) -> None:
    page.add_files(photos)
    page.photo_picker.show_all.setChecked(True)
    page.photo_picker.select("us-visa-photo")
    page.background_card.select("white")
    assert page.settings().background is None  # card is locked for this preset


def test_controls_lock_while_running(qtbot, page: BatchPage, photos: list[Path]) -> None:
    page.add_files(photos)
    page.photo_picker.select("in-ibps-photo")
    page.start()
    assert not page.add_button.isEnabled() and page.cancel_button.isVisible()
    page.add_files(photos)  # ignored while running
    assert len(page.files) == 4
    qtbot.waitUntil(lambda: not page.running, timeout=TIMEOUT)
    assert page.add_button.isEnabled()


def test_side_column_fits(qtbot, page: BatchPage, photos: list[Path]) -> None:
    page.add_files(photos)
    qtbot.wait(50)
    assert page.side_scroll.widget().minimumSizeHint().width() <= page.side_scroll.viewport().width()
