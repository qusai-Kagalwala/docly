"""End-to-end tests for the Photo page."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from docly.ui.pages.photo_page import NO_CROP_HINT, PhotoPage

TIMEOUT = 15_000


@pytest.fixture
def page(qtbot, theme_manager, bundled_presets) -> PhotoPage:
    widget = PhotoPage(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(widget)
    widget.resize(1000, 700)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def wait_for_result(qtbot, page: PhotoPage, title: str = "Ready to upload") -> None:
    qtbot.waitUntil(lambda: page.result_card.title.text() == title, timeout=TIMEOUT)


def test_starts_with_drop_zone(page: PhotoPage) -> None:
    assert page.stack.currentWidget() is page.drop_zone
    assert page.result_card.title.text() == "Waiting for a photo"
    assert page.preset is not None
    assert not page.replace_button.isVisible()


def test_load_process_and_save(qtbot, page: PhotoPage, photo_file: Path) -> None:
    page.picker.select("in-ibps-photo")
    page.load_file(photo_file)
    wait_for_result(qtbot, page)
    assert page.stack.currentWidget() is page.crop_card
    assert page.crop_view.has_crop
    assert "1200 × 1600 px" in page.file_label.text()
    saved = page.result_card.save()
    assert saved is not None and saved.exists()
    assert saved.parent.name == "Docly_Output"


def test_changing_preset_reprocesses(qtbot, page: PhotoPage, photo_file: Path) -> None:
    page.picker.select("in-ibps-photo")
    page.load_file(photo_file)
    wait_for_result(qtbot, page)
    page.picker.select("in-upsc-photo")  # KB-only: no crop frame
    qtbot.waitUntil(lambda: "200 × 230" not in page.result_card.subtitle.text()
                    and page.result_card.title.text() == "Ready to upload", timeout=TIMEOUT)
    assert not page.crop_view.has_crop
    assert page.crop_hint.text() == NO_CROP_HINT
    assert page.crop_hint.isVisible()


def test_moving_the_crop_reprocesses(qtbot, page: PhotoPage, photo_file: Path) -> None:
    page.picker.select("intl-photo-35x45")
    page.load_file(photo_file)
    wait_for_result(qtbot, page)
    started: list[bool] = []
    page.processor.started.connect(lambda: started.append(True))
    page.crop_view.set_ratio(page.preset.ratio)
    page.crop_view.move_box(0, 200)
    page.crop_view.cropChanged.emit()
    qtbot.waitUntil(lambda: bool(started), timeout=TIMEOUT)
    wait_for_result(qtbot, page)


def test_damaged_file_shows_banner(qtbot, page: PhotoPage, tmp_path: Path) -> None:
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"this is not a photo")
    page.load_file(bad)
    qtbot.waitUntil(lambda: page.banner.isVisible(), timeout=TIMEOUT)
    assert "isn't an image" in page.banner.text()
    assert page.stack.currentWidget() is page.drop_zone
    assert page.result_card.title.text() == "Waiting for a photo"


def test_bad_file_keeps_previous_photo(qtbot, page: PhotoPage, photo_file: Path, tmp_path: Path) -> None:
    page.picker.select("in-ibps-photo")
    page.load_file(photo_file)
    wait_for_result(qtbot, page)
    heic = tmp_path / "IMG_0001.HEIC"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
    page.load_file(heic)
    qtbot.waitUntil(lambda: page.banner.isVisible(), timeout=TIMEOUT)
    assert "HEIC" in page.banner.text()
    wait_for_result(qtbot, page)  # the previous photo is still there and valid
    assert page.loaded is not None and page.loaded.name == "my photo.jpg"
    saved = page.result_card.save()
    assert saved is not None and saved.parent == photo_file.parent / "Docly_Output"


def test_dropping_on_the_page(qtbot, page: PhotoPage, photo_file: Path) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(photo_file))])
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dropEvent(drop)
    wait_for_result(qtbot, page)


def test_dropping_a_document_on_the_page(page: PhotoPage) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/docs/form.pdf")])
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dropEvent(drop)
    assert page.banner.isVisible()
    assert "form.pdf" in page.banner.text()


def test_main_window_uses_real_photo_page(main_window) -> None:
    assert isinstance(main_window.page("photo"), PhotoPage)


# ----------------------------------------------------------------------
# Background colour (Phase 9) — uses the real bundled model
# ----------------------------------------------------------------------
def test_background_colour_end_to_end(qtbot, page: PhotoPage, photo_file: Path) -> None:
    page.picker.select("in-ibps-photo")
    page.load_file(photo_file)
    wait_for_result(qtbot, page)
    assert page.crop_view.showing_original
    started: list[bool] = []
    page.processor.started.connect(lambda: started.append(True))
    page.background_card.select("light_blue")
    qtbot.waitUntil(lambda: bool(started), timeout=TIMEOUT)
    wait_for_result(qtbot, page)
    qtbot.waitUntil(lambda: not page.crop_view.showing_original, timeout=TIMEOUT)  # live preview
    assert any("Background replaced" in note for note in page.result_card.notes.text().splitlines())
    page.background_card.select("keep")
    qtbot.waitUntil(lambda: page.crop_view.showing_original, timeout=TIMEOUT)


def test_strict_preset_never_edits(qtbot, page: PhotoPage, photo_file: Path) -> None:
    page.picker.show_all.setChecked(True)
    page.picker.select("us-visa-photo")
    page.background_card.select("white")
    assert page.background_card.blocked and page.job_settings() is None
    page.load_file(photo_file)
    qtbot.waitUntil(lambda: page.result_card.save_button.isEnabled(), timeout=TIMEOUT)
    assert page.crop_view.showing_original
    assert "Background replaced" not in page.result_card.notes.text()
