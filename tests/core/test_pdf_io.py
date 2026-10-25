"""Tests for safe PDF opening and clean saving."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf
import pytest

from docly.core import pdf_io
from docly.core.errors import (
    CorruptPdfError,
    FileTooLargeError,
    PasswordRequiredError,
    WrongPasswordError,
)
from docly.core.pdf_io import open_pdf, open_pdf_bytes, sanitize_page, save_pdf
from tests.core import pdfs


def test_open_and_info(tmp_path: Path) -> None:
    path = pdfs.write_pdf(tmp_path / "form.pdf", ["a", "b", "c"])
    opened = open_pdf(path)
    assert opened.page_count == 3
    assert opened.name == "form.pdf"
    assert not opened.encrypted and not opened.repaired and opened.warnings == []
    assert opened.page_size(0) == pytest.approx((595, 842))
    opened.close()


def test_page_size_follows_rotation() -> None:
    opened = open_pdf_bytes(pdfs.make_pdf(["x"], rotate=90))
    assert opened.page_size(0) == pytest.approx((842, 595))


def test_unicode_name(tmp_path: Path) -> None:
    path = pdfs.write_pdf(tmp_path / "प्रमाणपत्र ✓.pdf", ["x"])
    assert open_pdf(path).name == "प्रमाणपत्र ✓.pdf"


@pytest.mark.parametrize(
    "data,fragment",
    [
        (b"", "empty"),
        (b"hello, I am a text file pretending to be a PDF", "isn't a PDF"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 100, "isn't a PDF"),
        (b"%PDF-1.7\n" + b"garbage " * 200, "damaged and can't be repaired"),
    ],
)
def test_bad_files(data: bytes, fragment: str) -> None:
    with pytest.raises(CorruptPdfError, match=fragment):
        open_pdf_bytes(data, "bad.pdf")


def test_damaged_pdf_is_repaired_with_warning() -> None:
    data = pdfs.make_pdf(["a", "b"]).replace(b"xref", b"xrfe")  # break the page index
    opened = open_pdf_bytes(data, "broken.pdf")
    assert opened.page_count == 2
    assert opened.repaired
    assert "was damaged and has been repaired" in opened.warnings[0]


def test_password_required_then_wrong_then_right() -> None:
    data = pdfs.make_pdf(["a"], password="open-sesame")
    with pytest.raises(PasswordRequiredError, match="password-protected"):
        open_pdf_bytes(data, "locked.pdf")
    with pytest.raises(WrongPasswordError, match="doesn't open locked.pdf"):
        open_pdf_bytes(data, "locked.pdf", password="nope")
    opened = open_pdf_bytes(data, "locked.pdf", password="open-sesame")
    assert opened.encrypted and opened.page_count == 1


def test_owner_restricted_pdf_opens_without_password() -> None:
    opened = open_pdf_bytes(pdfs.make_pdf(["a"], owner_only=True), "marksheet.pdf")
    assert opened.encrypted and opened.page_count == 1


def test_size_and_page_limits(monkeypatch) -> None:
    data = pdfs.make_pdf(["a", "b", "c"])
    monkeypatch.setattr(pdf_io, "MAX_PAGES", 2)
    with pytest.raises(FileTooLargeError, match="3 pages"):
        open_pdf_bytes(data, "long.pdf")
    monkeypatch.setattr(pdf_io, "MAX_PDF_BYTES", 100)
    with pytest.raises(FileTooLargeError):
        open_pdf_bytes(data, "big.pdf")


def test_file_too_large_on_disk(tmp_path: Path, monkeypatch) -> None:
    path = pdfs.write_pdf(tmp_path / "big.pdf", ["a"])
    monkeypatch.setattr(pdf_io, "MAX_PDF_BYTES", 50)
    with pytest.raises(FileTooLargeError):
        open_pdf(path)


def test_save_removes_password_and_metadata() -> None:
    opened = open_pdf_bytes(pdfs.make_pdf(["a"], password="pw", extras=True), password="pw")
    data = save_pdf(opened.pdf)
    with pikepdf.open(io.BytesIO(data)) as out:  # opens without a password
        assert not out.is_encrypted
        assert "/Info" not in out.trailer


def test_save_size_limit(monkeypatch) -> None:
    opened = open_pdf_bytes(pdfs.make_pdf(["a"]))
    monkeypatch.setattr(pdf_io, "MAX_OUTPUT_BYTES", 10)
    with pytest.raises(FileTooLargeError, match="over Docly's"):
        save_pdf(opened.pdf)


def test_sanitize_page_removes_risky_items_only() -> None:
    opened = open_pdf_bytes(pdfs.make_pdf(["a"], extras=True))
    page = opened.pdf.pages[0]
    removed = sanitize_page(page)
    assert removed == 3  # page auto-action, attachment, launch action
    assert "/AA" not in page.obj
    annots = page.obj.Annots
    assert len(annots) == 2  # the two links remain…
    assert "/A" not in annots[0]  # …but the launch action is gone
    assert annots[1].A.S == pikepdf.Name.URI  # web links are kept
