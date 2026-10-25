"""Tests for the result card and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

from docly.core.image_io import load_image
from docly.core.pipeline import process_loaded
from docly.ui import desktop
from docly.ui.widgets import result_card as result_module
from docly.ui.widgets.result_card import ResultCard
from tests.core import images


@pytest.fixture
def card(qtbot, theme_manager) -> ResultCard:
    widget = ResultCard(theme_manager)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def passing(photo_file: Path, bundled_presets):
    preset = bundled_presets.by_id("in-ibps-photo")
    return process_loaded(load_image(photo_file), preset)


def test_idle_state(card: ResultCard) -> None:
    assert card.title.text() == "Waiting for a photo"
    assert not card.save_button.isEnabled()
    assert not card.reveal_button.isEnabled()


def test_passing_result(card: ResultCard, passing, photo_file: Path) -> None:
    card.show_result(passing, photo_file)
    assert card.title.text() == "Ready to upload"
    assert card.title.property("state") == "pass"
    assert "200 × 230 px" in card.subtitle.text()
    assert card.save_button.isEnabled()
    assert not card.reveal_button.isEnabled()  # nothing saved yet
    assert card.preview.pixmap() is not None and not card.preview.pixmap().isNull()


def test_failing_result(card: ResultCard, photo_file: Path) -> None:
    impossible = images.preset(width_px=1200, height_px=1600, kb_max=5)
    result = process_loaded(load_image(photo_file), impossible)
    card.show_result(result, photo_file)
    assert card.title.text() == "Needs attention"
    assert card.title.property("state") == "fail"
    assert card.save_button.isEnabled()  # you can still save the best attempt


def test_save_goes_to_docly_output_and_never_overwrites(qtbot, card, passing, photo_file: Path) -> None:
    card.show_result(passing, photo_file)
    with qtbot.waitSignal(card.saved, timeout=1000):
        first = card.save()
    second = card.save()
    folder = photo_file.parent / "Docly_Output"
    assert first == folder / "my photo_in-ibps-photo.jpg"
    assert second == folder / "my photo_in-ibps-photo (2).jpg"
    assert first.read_bytes() == passing.data
    assert card.reveal_button.isEnabled()
    assert str(second) in card.saved_label.text()


def test_read_only_folder_falls_back_to_pictures(card, passing, photo_file: Path, tmp_path: Path, monkeypatch) -> None:
    blocker = tmp_path / "not_a_folder"
    blocker.write_bytes(b"")
    monkeypatch.setattr(desktop, "output_folder_for", lambda source: blocker / "Docly_Output")
    monkeypatch.setattr(desktop, "pictures_output_folder", lambda: tmp_path / "Pictures" / "Docly_Output")
    card.show_result(passing, photo_file)
    saved = card.save()
    assert saved is not None and saved.parent == tmp_path / "Pictures" / "Docly_Output"
    assert "couldn't write to the usual folder" in card.saved_label.text()


def test_save_error_is_shown(card, passing, photo_file: Path, tmp_path: Path, monkeypatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    monkeypatch.setattr(desktop, "output_folder_for", lambda source: blocker / "a")
    monkeypatch.setattr(desktop, "pictures_output_folder", lambda: blocker / "b")
    card.show_result(passing, photo_file)
    assert card.save() is None
    assert card.saved_label.property("banner") == "danger"
    assert not card.reveal_button.isEnabled()


def test_save_as(card, passing, photo_file: Path, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "chosen" / "final.jpg"
    target.parent.mkdir()
    target.write_bytes(b"old")  # the dialog already asked before replacing
    monkeypatch.setattr(result_module, "ask_save_path", lambda parent, suggested, ext: target)
    card.show_result(passing, photo_file)
    assert card.save_as() == target
    assert target.read_bytes() == passing.data
    assert not list(target.parent.glob(".*docly-tmp"))  # no temp file left behind


def test_save_as_cancelled(card, passing, photo_file: Path, monkeypatch) -> None:
    monkeypatch.setattr(result_module, "ask_save_path", lambda parent, suggested, ext: None)
    card.show_result(passing, photo_file)
    assert card.save_as() is None
    assert card.saved_path is None


def test_open_folder(card, passing, photo_file: Path, monkeypatch) -> None:
    revealed: list[Path] = []
    monkeypatch.setattr(desktop, "reveal_in_folder", lambda path: revealed.append(path) or True)
    card.show_result(passing, photo_file)
    saved = card.save()
    card.reveal_button.click()
    assert revealed == [saved]


def test_error_state(card: ResultCard) -> None:
    card.show_error("photo.jpg looks damaged.")
    assert card.title.text() == "Couldn't process this photo"
    assert card.subtitle.text() == "photo.jpg looks damaged."
    assert not card.save_button.isEnabled()
