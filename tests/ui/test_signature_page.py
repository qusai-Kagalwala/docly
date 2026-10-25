"""End-to-end tests for the Signature page."""

from __future__ import annotations

from pathlib import Path

import pytest

from docly.presets.models import PresetKind
from docly.ui.pages.signature_page import SignaturePage
from tests.core import images

TIMEOUT = 15_000


@pytest.fixture
def signature_file(tmp_path: Path) -> Path:
    return images.save(images.signature_photo(), tmp_path / "my sign.jpg", "JPEG", quality=90)


@pytest.fixture
def page(qtbot, theme_manager, bundled_presets) -> SignaturePage:
    widget = SignaturePage(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(widget)
    widget.resize(1000, 700)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def wait_ready(qtbot, page: SignaturePage) -> None:
    qtbot.waitUntil(lambda: page.result_card.title.text() == "Ready to upload", timeout=TIMEOUT)


def loaded_page(qtbot, page: SignaturePage, path: Path, preset_id: str = "in-ibps-signature") -> SignaturePage:
    page.picker.select(preset_id)
    page.load_file(path)
    wait_ready(qtbot, page)
    return page


def test_lists_signature_and_ink_presets_only(page: SignaturePage, bundled_presets) -> None:
    page.picker.show_all.setChecked(True)
    ids = set(page.picker.visible_preset_ids())
    allowed = {p.id for p in bundled_presets.presets if p.kind in (PresetKind.SIGNATURE, PresetKind.IMAGE)}
    assert ids == allowed
    assert "in-ibps-thumb" in ids and "in-ibps-declaration" in ids
    assert "in-ibps-photo" not in ids


def test_clean_and_save(qtbot, page: SignaturePage, signature_file: Path) -> None:
    loaded_page(qtbot, page, signature_file)
    assert page.crop_view.free and page.crop_view.is_whole_image
    assert page.cleaned_view.image is not None
    assert (page.cleaned_view.image.width(), page.cleaned_view.image.height()) == (140, 60)
    assert not page.reset_button.isVisible()  # nothing to reset yet
    saved = page.result_card.save()
    assert saved is not None and saved.name == "my sign_in-ibps-signature.jpg"


def test_strength_change_reprocesses(qtbot, page: SignaturePage, signature_file: Path) -> None:
    loaded_page(qtbot, page, signature_file, "intl-signature")
    started: list[bool] = []
    page.processor.started.connect(lambda: started.append(True))
    page.strength.setValue(80)
    assert page.strength_value.text() == "80"
    qtbot.waitUntil(lambda: bool(started), timeout=TIMEOUT)
    wait_ready(qtbot, page)
    assert page.job_settings()[0].strength == 80


def test_black_ink_toggle_changes_output(qtbot, page: SignaturePage, signature_file: Path) -> None:
    loaded_page(qtbot, page, signature_file, "intl-signature")
    before = page.cleaned_view.image.copy()
    page.black_ink.setChecked(True)
    qtbot.waitUntil(lambda: page.cleaned_view.image is not None and page.cleaned_view.image != before, timeout=TIMEOUT)
    wait_ready(qtbot, page)
    assert page.options().black_ink


def test_format_switch_only_for_png_presets(qtbot, page: SignaturePage, signature_file: Path) -> None:
    page.picker.select("in-ibps-signature")
    assert not page.format_row.isVisibleTo(page)
    page.picker.select("intl-signature")
    assert page.format_row.isVisibleTo(page)
    loaded_page(qtbot, page, signature_file, "intl-signature")
    page.format_switch.buttons["png"].click()
    qtbot.waitUntil(lambda: page.result_card._result is not None and page.result_card._result.format.value == "png",
                    timeout=TIMEOUT)
    wait_ready(qtbot, page)
    assert page.result_card._result.suggested_name.endswith(".png")
    # Switching to a JPG-only preset falls back to JPG.
    page.picker.select("in-upsc-signature")
    assert page.output_format().value == "jpg"


def test_selecting_an_area_reprocesses_and_shows_reset(qtbot, page: SignaturePage, signature_file: Path) -> None:
    from PySide6.QtCore import QRectF

    loaded_page(qtbot, page, signature_file)
    page.crop_view._box = QRectF(100, 100, 1000, 800)  # as if the user dragged the edges
    page.crop_view.cropChanged.emit()
    assert page.reset_button.isVisible()
    wait_ready(qtbot, page)
    assert page.job_settings()[2] is False  # area is in use
    page.reset_button.click()
    assert page.crop_view.is_whole_image
    assert not page.reset_button.isVisible()


def test_area_survives_preset_change(qtbot, page: SignaturePage, signature_file: Path) -> None:
    from PySide6.QtCore import QRectF

    loaded_page(qtbot, page, signature_file)
    area = QRectF(100, 100, 1000, 800)
    page.crop_view._box = QRectF(area)
    page.picker.select("in-upsc-signature")
    assert page.crop_view.display_box == area


def test_blank_page_message(qtbot, page: SignaturePage, tmp_path: Path) -> None:
    blank = images.save(images.blank_paper(), tmp_path / "blank.jpg")
    page.load_file(blank)
    qtbot.waitUntil(lambda: page.result_card.title.text() == "Couldn't process this photo", timeout=TIMEOUT)
    assert "couldn't find a signature" in page.result_card.subtitle.text()
    assert page.cleaned_view.image is None


def test_main_window_has_signature_page(main_window) -> None:
    main_window.show_page("signature")
    assert isinstance(main_window.pages[1], SignaturePage)
