"""Tests for putting images on PDF pages."""

from __future__ import annotations

import io

import pikepdf
import pytest
from PIL import Image

from docly.core.image_pdf import PAPER, PageSize, add_image_page
from tests.core import images


def page_info(pdf: pikepdf.Pdf, index: int = 0):
    page = pdf.pages[index]
    box = [float(v) for v in page.mediabox]
    xobject = page.obj.Resources.XObject.Im0
    return box, xobject, int(page.obj.get("/Rotate", 0))


def test_jpeg_bytes_embedded_unchanged() -> None:
    data = images.encode(images.photo_like(800, 600), quality=85)
    pdf = pikepdf.Pdf.new()
    placed = add_image_page(pdf, data, "photo.jpg")
    _, xobject, _ = page_info(pdf)
    assert placed.passthrough
    assert xobject.Filter == pikepdf.Name.DCTDecode
    assert xobject.read_raw_bytes() == data  # exactly the original file
    assert (int(xobject.Width), int(xobject.Height)) == (800, 600)


def test_rotated_phone_photo_rotates_the_page() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways, "rotate 90° to view"
    data = images.encode(images.photo_like(800, 600), exif=exif)
    pdf = pikepdf.Pdf.new()
    placed = add_image_page(pdf, data, "phone.jpg")
    box, xobject, rotate = page_info(pdf)
    assert placed.passthrough and placed.rotate == 90
    assert rotate == 90
    assert xobject.read_raw_bytes() == data  # still no re-encoding


def test_mirrored_orientation_falls_back_to_lossless() -> None:
    exif = Image.Exif()
    exif[0x0112] = 2  # mirrored
    pdf = pikepdf.Pdf.new()
    placed = add_image_page(pdf, images.encode(images.flat(40, 20), exif=exif), "m.jpg")
    assert not placed.passthrough
    assert page_info(pdf)[1].Filter == pikepdf.Name.FlateDecode


def test_png_is_lossless() -> None:
    source = images.photo_like(120, 90)
    pdf = pikepdf.Pdf.new()
    placed = add_image_page(pdf, images.encode(source, "PNG"), "scan.png")
    _, xobject, _ = page_info(pdf)
    assert not placed.passthrough
    restored = pikepdf.PdfImage(xobject).as_pil_image().convert("RGB")
    assert restored.tobytes() == source.convert("RGB").tobytes()


def test_cmyk_jpeg_is_converted() -> None:
    data = images.encode(Image.new("CMYK", (30, 30), (0, 0, 0, 0)))
    pdf = pikepdf.Pdf.new()
    assert not add_image_page(pdf, data, "print.jpg").passthrough


def test_greyscale_jpeg_passthrough() -> None:
    data = images.encode(Image.new("L", (50, 40), 128))
    pdf = pikepdf.Pdf.new()
    assert add_image_page(pdf, data, "grey.jpg").passthrough
    assert page_info(pdf)[1].ColorSpace == pikepdf.Name.DeviceGray


@pytest.mark.parametrize(
    "size,shape,expected",
    [
        (PageSize.A4, (600, 800), PAPER[PageSize.A4]),
        (PageSize.A4, (800, 600), PAPER[PageSize.A4][::-1]),  # landscape image → landscape page
        (PageSize.LETTER, (600, 800), PAPER[PageSize.LETTER]),
    ],
)
def test_paper_sizes(size, shape, expected) -> None:
    pdf = pikepdf.Pdf.new()
    add_image_page(pdf, images.encode(images.flat(*shape)), "x.jpg", size)
    box = page_info(pdf)[0]
    assert (box[2], box[3]) == pytest.approx(expected, abs=0.01)


def test_fit_page_has_image_shape() -> None:
    pdf = pikepdf.Pdf.new()
    add_image_page(pdf, images.encode(images.flat(1000, 250)), "wide.jpg", PageSize.FIT)
    box = page_info(pdf)[0]
    assert box[2] / box[3] == pytest.approx(4.0, rel=1e-4)
    assert max(box[2], box[3]) == pytest.approx(PAPER[PageSize.A4][1])


def test_image_is_centred_and_fits() -> None:
    pdf = pikepdf.Pdf.new()
    add_image_page(pdf, images.encode(images.flat(100, 100)), "sq.jpg", margin_pt=20)
    content = pdf.pages[0].obj.Contents.read_bytes().decode()
    w, _, _, h, x, y = (float(v) for v in content.split()[1:7])
    assert w == pytest.approx(PAPER[PageSize.A4][0] - 40)
    assert x == pytest.approx(20) and y == pytest.approx((PAPER[PageSize.A4][1] - h) / 2)


def test_bad_image_raises_friendly_error() -> None:
    from docly.core.errors import UnsupportedFormatError

    with pytest.raises(UnsupportedFormatError):
        add_image_page(pikepdf.Pdf.new(), b"not an image", "x.jpg")


def test_saved_pdf_opens(tmp_path) -> None:
    pdf = pikepdf.Pdf.new()
    add_image_page(pdf, images.encode(images.photo_like(300, 200)), "a.jpg")
    buffer = io.BytesIO()
    pdf.save(buffer)
    with pikepdf.open(io.BytesIO(buffer.getvalue())) as reopened:
        assert len(reopened.pages) == 1
