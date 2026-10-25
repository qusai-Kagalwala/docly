"""Tests for saving PDF results."""

from __future__ import annotations

from pathlib import Path

from docly.core.errors import FileAccessError
from docly.core.pdf_ops import PdfResult
from docly.ui import desktop
from docly.ui.widgets import pdf_result_card
from docly.ui.widgets.pdf_result_card import PdfResultCard, format_size


def result(name: str, pages: int = 1, warnings: list[str] | None = None) -> PdfResult:
    return PdfResult(b"%PDF-1.7\n" + name.encode(), pages, name, warnings or [])


def card(qtbot, theme_manager) -> PdfResultCard:
    widget = PdfResultCard(theme_manager)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_single_result(qtbot, theme_manager, tmp_path: Path) -> None:
    c = card(qtbot, theme_manager)
    c.show_results([result("cv.pdf", 3, ["cv.pdf was damaged and has been repaired."])], tmp_path / "cv.pdf")
    assert c.title.text() == "PDF ready"
    assert "3 pages" in c.subtitle.text()
    assert c.notes.isVisible() and "repaired" in c.notes.text()
    assert c.save_button.text() == "Save"
    assert not c.reveal_button.isEnabled()
    with qtbot.waitSignal(c.saved) as blocker:
        paths = c.save()
    assert paths == [tmp_path / "Docly_Output" / "cv.pdf"]
    assert blocker.args[0] == paths
    assert c.reveal_button.isEnabled()


def test_split_results_go_in_subfolder(qtbot, theme_manager, tmp_path: Path) -> None:
    c = card(qtbot, theme_manager)
    c.show_results([result("cv_pages-1.pdf"), result("cv_pages-2.pdf")], tmp_path / "cv.pdf", split=True)
    assert c.title.text() == "2 PDFs ready"
    assert c.split_folder_name() == "cv_split"
    paths = c.save()
    assert [p.parent for p in paths] == [tmp_path / "Docly_Output" / "cv_split"] * 2
    assert "Saved 2 files" in c.saved_label.text()


def test_read_only_folder_falls_back_to_pictures(qtbot, theme_manager, tmp_path: Path, monkeypatch) -> None:
    pictures = tmp_path / "Pictures" / "Docly_Output"
    monkeypatch.setattr(desktop, "pictures_output_folder", lambda: pictures)
    real_write = pdf_result_card.write_new_file

    def picky_write(folder: Path, name: str, data: bytes) -> Path:
        if "Pictures" not in str(folder):
            raise FileAccessError("read-only")
        return real_write(folder, name, data)

    monkeypatch.setattr(pdf_result_card, "write_new_file", picky_write)
    c = card(qtbot, theme_manager)
    c.show_results([result("a_pages-1.pdf"), result("a_pages-2.pdf")], tmp_path / "a.pdf", split=True)
    paths = c.save()
    assert paths[0].parent == pictures / "a_split"
    assert "read-only" in c.saved_label.text()


def test_error_and_idle(qtbot, theme_manager) -> None:
    c = card(qtbot, theme_manager)
    c.show_error("Page 9 doesn't exist.")
    assert c.title.text() == "Couldn't create the PDF"
    assert c.create_button.isVisible() and not c.save_button.isVisible()
    c.show_idle("3 pages arranged.")
    assert c.results == []


def test_format_size() -> None:
    assert format_size(2048) == "2 KB"
    assert format_size(3 * 1024 * 1024) == "3.0 MB"
