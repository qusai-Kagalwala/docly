"""Tests for Fill & Sign (Qt-free parts; render checks live in tests/ui)."""

from __future__ import annotations

import hashlib
import io
from datetime import date
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Name

from docly.core.errors import InvalidPageRangeError
from docly.core.image_io import load_image_bytes
from docly.core.pdf_fill import (
    BLUE_INK,
    COVER_WARNING,
    Box,
    FillItem,
    ItemKind,
    UnsupportedTextError,
    _display_to_user,
    check_text,
    cover_item,
    date_item,
    displayed_size,
    fill_pdf,
    format_date,
    image_item,
    mark_item,
    text_item,
    text_size,
)
from docly.core.pdf_ops import load_source
from tests.core import images, pdfs


@pytest.fixture
def form(tmp_path: Path):
    source = load_source(pdfs.write_pdf(tmp_path / "form.pdf", ["p1", "p2"]))
    yield source
    source.close()


def page_content(data: bytes, index: int = 0) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[index]
        page.contents_coalesce()
        return page.obj.Contents.read_bytes()


def transparent_signature() -> bytes:
    image = images.signature_like(300, 100).convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, _ = pixels[x, y]
            pixels[x, y] = (r, g, b, 0 if r > 200 else 255)  # paper see-through, ink solid
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


# ----------------------------------------------------------------------
def test_text_box_size_from_font_metrics() -> None:
    w, h = text_size("Hello", 10)
    assert w == pytest.approx((722 + 556 + 222 + 222 + 556) / 100)  # Helvetica widths
    assert h == pytest.approx(12)
    _, two_lines = text_size("a\nb", 10)
    assert two_lines == pytest.approx(24)
    item = text_item(0, 10, 20, "Hi", 14, BLUE_INK)
    assert item.box.x == 10 and item.box.y == 20 and item.colour == BLUE_INK


def test_dates() -> None:
    day = date(2026, 1, 5)
    assert format_date(day) == "05/01/2026"
    assert format_date(day, "YYYY-MM-DD") == "2026-01-05"
    assert format_date(day, "DD Mon YYYY") == "05 Jan 2026"
    assert date_item(0, 0, 0, day, "DD-MM-YYYY").text == "05-01-2026"
    with pytest.raises(ValueError):
        format_date(day, "nope")


def test_unsupported_characters_are_named() -> None:
    check_text("Café – naïve © “quotes” €5")  # Latin and Windows-1252 symbols are fine
    with pytest.raises(UnsupportedTextError, match="₹"):
        check_text("₹ 500")
    with pytest.raises(UnsupportedTextError, match="न"):
        check_text("नाम")


def test_text_is_drawn_with_escapes_and_lines(form) -> None:
    result = fill_pdf(form, [text_item(0, 72, 100, "A (b) \\ c\nLine 2", 12)])
    content = page_content(result.data)
    assert b"(A \\(b\\) \\\\ c) Tj" in content and b"T*" in content and b"(Line 2) Tj" in content
    assert result.suggested_name == "form_signed.pdf"
    with pikepdf.open(io.BytesIO(result.data)) as pdf:
        fonts = pdf.pages[0].obj.Resources.Font
        helv = [fonts[k] for k in fonts.keys() if str(k).startswith("/DoclyHelv")]
        assert helv and helv[0].BaseFont == Name.Helvetica and helv[0].Encoding == Name.WinAnsiEncoding


def test_non_ascii_latin_text_is_encoded(form) -> None:
    result = fill_pdf(form, [text_item(0, 72, 100, "Café €", 12)])
    assert b"(Caf\\351 \\200) Tj" in page_content(result.data)


def test_existing_content_is_isolated(form) -> None:
    content = page_content(fill_pdf(form, [mark_item(ItemKind.TICK, 0, 50, 50)]).data)
    assert content.startswith(b"q\n")  # original drawing wrapped in q … Q
    assert content.count(b"q") >= 3 and content.rstrip().endswith(b"Q")


def test_marks_and_cover(form) -> None:
    result = fill_pdf(
        form, [mark_item(ItemKind.TICK, 0, 50, 50), mark_item(ItemKind.CROSS, 1, 50, 50), cover_item(0, 10, 10, 50, 20)]
    )
    assert b" re f" in page_content(result.data, 0)
    assert b"\nS\n" in page_content(result.data, 1)  # a stroked path
    assert COVER_WARNING in result.warnings
    assert result.page_count == 2
    with pytest.raises(ValueError):
        mark_item(ItemKind.TEXT, 0, 0, 0)


def test_signature_keeps_transparency(form) -> None:
    data = transparent_signature()
    item = image_item(0, 380, 700, data, 150)
    assert item.box.w == 150 and item.box.h == pytest.approx(50)
    result = fill_pdf(form, [item])
    with pikepdf.open(io.BytesIO(result.data)) as pdf:
        xobjects = pdf.pages[0].obj.Resources.XObject
        image = xobjects[next(k for k in xobjects.keys() if str(k).startswith("/DoclyIm"))]
        assert Name.SMask in image  # see-through paper stays see-through
        assert image.Width == 300


def test_opaque_image_has_no_mask(form) -> None:
    item = image_item(0, 10, 10, images.encode(images.photo_like(200, 100), "JPEG"), 100)
    with pikepdf.open(io.BytesIO(fill_pdf(form, [item]).data)) as pdf:
        xobjects = pdf.pages[0].obj.Resources.XObject
        image = xobjects[next(k for k in xobjects.keys() if str(k).startswith("/DoclyIm"))]
        assert Name.SMask not in image


def test_large_signature_is_shrunk(form) -> None:
    big = images.encode(images.signature_like(4000, 1200), "PNG")
    with pikepdf.open(io.BytesIO(fill_pdf(form, [image_item(0, 10, 10, big, 200)]).data)) as pdf:
        xobjects = pdf.pages[0].obj.Resources.XObject
        image = xobjects[next(iter(xobjects.keys()))]
        assert max(int(image.Width), int(image.Height)) <= 1600


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (FillItem(ItemKind.TEXT, 5, Box(0, 0, 10, 10), "x"), "Page 6"),
        (FillItem(ItemKind.TEXT, 0, Box(0, 0, 10, 10), "   "), "empty"),
        (FillItem(ItemKind.TEXT, 0, Box(0, 0, 10, 10), "x", font_size=200), "Font size"),
        (FillItem(ItemKind.TEXT, 0, Box(0, 0, 10, 10), "x" * 501), "500"),
        (FillItem(ItemKind.TICK, 0, Box(0, 0, 0, 10)), "no size"),
        (FillItem(ItemKind.IMAGE, 0, Box(0, 0, 10, 10)), "no image"),
        (FillItem(ItemKind.COVER, 0, Box(0, 0, 10, 10), colour=(300, 0, 0)), "0–255"),
    ],
)
def test_bad_items(form, item: FillItem, message: str) -> None:
    with pytest.raises(InvalidPageRangeError, match=message):
        fill_pdf(form, [item])


def test_nothing_to_add(form) -> None:
    with pytest.raises(InvalidPageRangeError, match="Add something"):
        fill_pdf(form, [])


@pytest.mark.parametrize(
    ("rotate", "expected"),
    [(0, (1, 0, 0, 1, 0, 0)), (90, (0, 1, -1, 0, 595, 0)), (180, (-1, 0, 0, -1, 595, 842)), (270, (0, -1, 1, 0, 0, 842))],
)
def test_display_matrix_for_rotations(rotate: int, expected) -> None:
    with pikepdf.open(io.BytesIO(pdfs.make_pdf(["a"], rotate=rotate))) as pdf:
        page = pdf.pages[0]
        assert _display_to_user(page) == pytest.approx(expected)
        assert displayed_size(page) == ((842, 595) if rotate in (90, 270) else (595, 842))


def test_cropbox_is_what_counts() -> None:
    pdf = pikepdf.open(io.BytesIO(pdfs.make_pdf(["a"])))
    pdf.pages[0].obj.CropBox = Array([50, 60, 545, 800])
    assert displayed_size(pdf.pages[0]) == (495, 740)
    assert _display_to_user(pdf.pages[0]) == (1, 0, 0, 1, 50, 60)


def test_images_become_pages_and_can_be_signed(tmp_path: Path) -> None:
    photo = load_source(images.save(images.photo_like(800, 1100), tmp_path / "scan.jpg"))
    result = fill_pdf(photo, [text_item(0, 50, 50, "Signed")])
    assert result.page_count == 1 and result.suggested_name == "scan_signed.pdf"


def test_inherited_resources_and_odd_files(tmp_path: Path) -> None:
    # Resources stored on the parent /Pages node instead of the page.
    pdf = pikepdf.open(io.BytesIO(pdfs.make_pdf(["a"])))
    page = pdf.pages[0].obj
    pdf.Root.Pages.Resources = page.Resources
    del page[Name.Resources]
    path = tmp_path / "inherit.pdf"
    pdf.save(path)
    source = load_source(path)
    result = fill_pdf(source, [text_item(0, 50, 50, "ok")])
    assert pdfs.labels_of(result.data) == ["a"]  # original text still there


def test_original_untouched_and_output_clean(tmp_path: Path) -> None:
    path = pdfs.write_pdf(tmp_path / "risky.pdf", ["a"], extras=True)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    source = load_source(path)
    result = fill_pdf(source, [text_item(0, 50, 50, "Signed")])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pikepdf.open(io.BytesIO(result.data)) as out:
        assert "/OpenAction" not in out.Root and "/Info" not in out.trailer and not out.is_encrypted


def test_keep_alpha_loading() -> None:
    data = transparent_signature()
    assert load_image_bytes(data).image.mode == "RGB"  # default: white paper
    assert load_image_bytes(data, keep_alpha=True).image.mode == "RGBA"
    opaque = images.encode(images.photo_like(50, 50), "PNG")
    assert load_image_bytes(opaque, keep_alpha=True).image.mode == "RGB"  # nothing see-through: stays RGB
