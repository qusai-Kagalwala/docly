"""Fill & Sign output checked by actually rendering it (QtPdf/PDFium, as Chrome does)."""

from __future__ import annotations

import io

import pikepdf
import pytest
from pikepdf import Array
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtPdf import QPdfDocument

from docly.core.pdf_fill import ItemKind, cover_item, fill_pdf, image_item, mark_item, text_item
from docly.core.pdf_io import open_pdf_bytes
from docly.core.pdf_ops import Source
from tests.core import images, pdfs


def source_for(data: bytes) -> Source:
    return Source(None, "form.pdf", pdf=open_pdf_bytes(data), data=data)


def render(data: bytes, page: int = 0) -> tuple[QImage, str]:
    """Page at 72 dpi (1 pixel = 1 point) on white, plus its text."""
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    document.load(buffer)
    size = document.pagePointSize(page)
    image = document.render(page, QSize(round(size.width()), round(size.height())))
    backed = QImage(image.size(), QImage.Format.Format_RGB32)
    backed.fill(QColor("white"))
    painter = QPainter(backed)
    painter.drawImage(0, 0, image)
    painter.end()
    text = document.getAllText(page).text()
    document.close()
    return backed, text


def dark(image: QImage, x: int, y: int) -> bool:
    return image.pixelColor(x, y).lightness() < 80


def make(rotate: int, cropped: bool) -> bytes:
    data = pdfs.make_pdf(["a"], rotate=rotate)
    if not cropped:
        return data
    pdf = pikepdf.open(io.BytesIO(data))
    pdf.pages[0].obj.CropBox = Array([50, 60, 545, 800])
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


@pytest.mark.parametrize("cropped", [False, True])
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_box_lands_where_placed_on_any_page(qapp, rotate: int, cropped: bool) -> None:
    result = fill_pdf(source_for(make(rotate, cropped)), [cover_item(0, 40, 100, 100, 50, (0, 0, 0))])
    image, _ = render(result.data)
    for x, y in ((45, 105), (135, 145), (90, 125)):
        assert dark(image, x, y), (x, y)
    for x, y in ((35, 125), (145, 125), (90, 95), (90, 155)):
        assert not dark(image, x, y), (x, y)


@pytest.mark.parametrize("rotate", [0, 90])
def test_text_is_real_text_and_upright(qapp, rotate: int) -> None:
    result = fill_pdf(source_for(make(rotate, False)), [text_item(0, 72, 200, "Qusai Kagalwala", 20)])
    image, text = render(result.data)
    assert "Qusai Kagalwala" in text  # selectable text, not a picture
    # Upright and inside its box: ink in the box, none just above or below it.
    w = 150
    ink = sum(dark(image, x, y) for x in range(72, 72 + w, 2) for y in range(200, 224))
    above = sum(dark(image, x, y) for x in range(72, 72 + w, 2) for y in range(185, 199))
    below = sum(dark(image, x, y) for x in range(72, 72 + w, 2) for y in range(226, 240))
    assert ink > 50 and above == 0 and below == 0


def test_tick_and_cross_are_drawn(qapp) -> None:
    data = pdfs.make_pdf(["a"])
    items = [mark_item(ItemKind.TICK, 0, 100, 300, 30), mark_item(ItemKind.CROSS, 0, 200, 300, 30)]
    image, _ = render(fill_pdf(source_for(data), items).data)
    assert dark(image, 215, 315)  # centre of the cross
    assert sum(dark(image, x, y) for x in range(100, 130) for y in range(300, 330)) > 20


def test_signature_paper_stays_see_through(qapp) -> None:
    data = pdfs.make_pdf(["a"])
    # Black page area first, then a signature with see-through paper on top of it.
    signature = images.signature_like(300, 100).convert("RGBA")
    pixels = signature.load()
    for y in range(signature.height):
        for x in range(signature.width):
            r, g, b, _ = pixels[x, y]
            pixels[x, y] = (r, g, b, 0 if r > 200 else 255)
    buffer = io.BytesIO()
    signature.save(buffer, "PNG")
    items = [cover_item(0, 100, 600, 300, 100, (0, 0, 0)), image_item(0, 100, 600, buffer.getvalue(), 300)]
    image, _ = render(fill_pdf(source_for(data), items).data)
    # Where the paper was, the black box still shows through.
    assert sum(dark(image, x, 605) for x in range(105, 395, 5)) > 50
