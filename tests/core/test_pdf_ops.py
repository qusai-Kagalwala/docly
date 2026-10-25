"""Tests for page plans and the everyday PDF operations."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pikepdf
import pytest

from docly.core.errors import CancelledError, InvalidPageRangeError, PasswordRequiredError
from docly.core.pdf_ops import (
    PageRef,
    build_pdf,
    close_all,
    delete_pages,
    extract,
    load_source,
    merge,
    rotate,
    split_by_ranges,
    split_every,
)
from tests.core import images, pdfs


@pytest.fixture
def form(tmp_path: Path):
    source = load_source(pdfs.write_pdf(tmp_path / "form.pdf", ["f1", "f2", "f3", "f4", "f5"]))
    yield source
    source.close()


@pytest.fixture
def cert(tmp_path: Path):
    source = load_source(pdfs.write_pdf(tmp_path / "cert.pdf", ["c1"]))
    yield source
    source.close()


def test_merge_keeps_order(form, cert, tmp_path: Path) -> None:
    photo = load_source(images.save(images.photo_like(400, 300), tmp_path / "photo.jpg"))
    result = merge([cert, photo, form])
    assert pdfs.labels_of(result.data) == ["c1", "", "f1", "f2", "f3", "f4", "f5"]
    assert result.page_count == 7
    assert result.suggested_name == "cert_merged.pdf"


def test_extract_in_given_order(form) -> None:
    result = extract(form, "5, 1-2")
    assert pdfs.labels_of(result.data) == ["f5", "f1", "f2"]
    assert result.suggested_name == "form_pages-5_1-2.pdf"


def test_delete(form) -> None:
    result = delete_pages(form, "2, 4")
    assert pdfs.labels_of(result.data) == ["f1", "f3", "f5"]
    with pytest.raises(InvalidPageRangeError, match="every page"):
        delete_pages(form, "1-")


def test_rotate_adds_to_existing_rotation(tmp_path: Path) -> None:
    source = load_source(pdfs.write_pdf(tmp_path / "scan.pdf", ["a", "b", "c"], rotate=90))
    result = rotate(source, "2-3", 180)
    assert pdfs.rotations_of(result.data) == [90, 270, 270]
    with pytest.raises(InvalidPageRangeError):
        rotate(source, "1", 45)


def test_split_by_ranges(form) -> None:
    parts = split_by_ranges(form, "1-2, 3, 4-")
    assert [pdfs.labels_of(p.data) for p in parts] == [["f1", "f2"], ["f3"], ["f4", "f5"]]
    assert [p.suggested_name for p in parts] == ["form_pages-1-2.pdf", "form_pages-3.pdf", "form_pages-4-5.pdf"]


def test_split_every(form) -> None:
    parts = split_every(form, 2)
    assert [pdfs.labels_of(p.data) for p in parts] == [["f1", "f2"], ["f3", "f4"], ["f5"]]
    singles = split_every(form, 1)
    assert len(singles) == 5
    with pytest.raises(InvalidPageRangeError):
        split_every(form, 0)


def test_plan_can_repeat_and_rotate_individual_copies(form, cert) -> None:
    plan = [PageRef(1, 0), PageRef(0, 2, 90), PageRef(0, 2), PageRef(1, 0, 270), PageRef(0, 2, 180)]
    result = build_pdf([form, cert], plan)
    assert pdfs.labels_of(result.data) == ["c1", "f3", "f3", "c1", "f3"]
    assert pdfs.rotations_of(result.data) == [0, 90, 0, 270, 180]  # each copy turned on its own


def test_bad_plans(form) -> None:
    with pytest.raises(InvalidPageRangeError, match="no pages"):
        build_pdf([form], [])
    with pytest.raises(InvalidPageRangeError, match="Page 9"):
        build_pdf([form], [PageRef(0, 8)])
    with pytest.raises(InvalidPageRangeError, match="isn't open"):
        build_pdf([form], [PageRef(3, 0)])


def test_output_is_clean(tmp_path: Path) -> None:
    source = load_source(
        pdfs.write_pdf(tmp_path / "risky.pdf", ["a", "b"], password="pw", extras=True), password="pw"
    )
    result = merge([source])
    with pikepdf.open(io.BytesIO(result.data)) as out:
        assert not out.is_encrypted  # no password on the output
        assert "/OpenAction" not in out.Root and "/Names" not in out.Root  # no document scripts
        assert "/Info" not in out.trailer  # no author/creator metadata
        page = out.pages[0].obj
        assert "/AA" not in page
        assert all(a.get("/Subtype") != pikepdf.Name.FileAttachment for a in page.Annots)
    assert any("could run programs" in w for w in result.warnings)


def test_repaired_source_warning_is_passed_on(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(pdfs.make_pdf(["a"]).replace(b"xref", b"xrfe"))
    source = load_source(path)
    assert any("repaired" in w for w in merge([source]).warnings)


def test_originals_are_untouched(tmp_path: Path) -> None:
    path = pdfs.write_pdf(tmp_path / "orig.pdf", ["a", "b"])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    source = load_source(path)
    rotate(source, "1", 90)
    delete_pages(source, "2")
    source.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_password_source(tmp_path: Path) -> None:
    path = pdfs.write_pdf(tmp_path / "locked.pdf", ["a"], password="pw")
    with pytest.raises(PasswordRequiredError):
        load_source(path)
    assert load_source(path, password="pw").page_count == 1


def test_progress_and_cancel(form) -> None:
    seen: list[tuple[int, int]] = []
    build_pdf([form], [PageRef(0, i) for i in range(5)], progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    with pytest.raises(CancelledError):
        build_pdf([form], [PageRef(0, 0)], cancel=lambda: True)


def test_non_pdf_non_image_source(tmp_path: Path) -> None:
    from docly.core.errors import UnsupportedFormatError

    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        load_source(path)


def test_close_all(form, cert) -> None:
    close_all([form, cert])  # closing twice must be harmless
    close_all([form, cert])
