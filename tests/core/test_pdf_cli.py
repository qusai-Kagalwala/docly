"""Tests for the PDF command-line demo."""

from __future__ import annotations

from pathlib import Path

import pytest

from docly.core.pdf_cli import main
from tests.core import images, pdfs


@pytest.fixture
def form(tmp_path: Path) -> Path:
    return pdfs.write_pdf(tmp_path / "form.pdf", ["f1", "f2", "f3", "f4"])


def outputs(tmp_path: Path) -> list[str]:
    folder = tmp_path / "Docly_Output"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_info(form: Path, capsys) -> None:
    assert main(["info", str(form)]) == 0
    text = capsys.readouterr().out
    assert "Pages: 4" in text and "210 × 297 mm" in text


def test_merge_with_image(form: Path, tmp_path: Path) -> None:
    photo = images.save(images.photo_like(300, 200), tmp_path / "page 2.jpg")
    assert main(["merge", str(form), str(photo)]) == 0
    saved = tmp_path / "Docly_Output" / "form_merged.pdf"
    assert pdfs.labels_of(saved.read_bytes()) == ["f1", "f2", "f3", "f4", ""]


def test_extract_delete_rotate_split(form: Path, tmp_path: Path) -> None:
    assert main(["extract", str(form), "--pages", "4, 1"]) == 0
    assert main(["delete", str(form), "--pages", "1"]) == 0
    assert main(["rotate", str(form), "--pages", "2", "--angle", "90"]) == 0
    assert main(["split", str(form), "--ranges", "1-2, 3-"]) == 0
    assert main(["split", str(form), "--every", "3"]) == 0
    assert outputs(tmp_path) == [
        "form_edited.pdf",
        "form_pages-1-2.pdf",
        "form_pages-1-3.pdf",
        "form_pages-3-4.pdf",
        "form_pages-4.pdf",
        "form_pages-4_1.pdf",
        "form_rotated.pdf",
    ]


def test_nothing_overwritten(form: Path, tmp_path: Path) -> None:
    main(["extract", str(form), "--pages", "1"])
    main(["extract", str(form), "--pages", "1"])
    assert outputs(tmp_path) == ["form_pages-1 (2).pdf", "form_pages-1.pdf"]


def test_bad_range_reports_error(form: Path, capsys) -> None:
    assert main(["extract", str(form), "--pages", "9"]) == 2
    assert "Page 9 doesn't exist" in capsys.readouterr().out


def test_password_prompt(tmp_path: Path, capsys) -> None:
    locked = pdfs.write_pdf(tmp_path / "locked.pdf", ["a"], password="pw")
    answers = iter(["wrong", "pw"])
    assert main(["extract", str(locked), "--pages", "1"], ask=lambda prompt: next(answers)) == 0
    assert "doesn't open locked.pdf" in capsys.readouterr().out
    saved = tmp_path / "Docly_Output" / "locked_pages-1.pdf"
    assert pdfs.labels_of(saved.read_bytes()) == ["a"]  # opens without a password


def test_password_gives_up_after_three_tries(tmp_path: Path, capsys) -> None:
    locked = pdfs.write_pdf(tmp_path / "locked.pdf", ["a"], password="pw")
    assert main(["info", str(locked)], ask=lambda prompt: "nope") == 2
    assert "Error:" in capsys.readouterr().out


def test_custom_output_folder(form: Path, tmp_path: Path) -> None:
    out = tmp_path / "elsewhere"
    assert main(["extract", str(form), "--pages", "1", "--out", str(out)]) == 0
    assert (out / "form_pages-1.pdf").exists()


def test_compress(tmp_path: Path, capsys) -> None:
    photo = images.save(images.photo_like(1240, 1754), tmp_path / "scan.jpg", quality=92)
    assert main(["merge", str(photo)]) == 0
    merged = tmp_path / "Docly_Output" / "scan.pdf"
    limit_kb = merged.stat().st_size / 1000 / 3
    out = tmp_path / "small"
    assert main(["compress", str(merged), "--kb", f"{limit_kb:.0f}", "--out", str(out)]) == 0
    saved = out / "scan.pdf"
    assert saved.stat().st_size <= round(limit_kb) * 1000


def test_compress_reports_best_and_needs_a_limit(form: Path, capsys) -> None:
    assert main(["compress", str(form), "--kb", "0.1"]) == 0
    assert "smallest readable version" in capsys.readouterr().out
    assert main(["compress", str(form)]) == 2
    assert "--kb" in capsys.readouterr().out
