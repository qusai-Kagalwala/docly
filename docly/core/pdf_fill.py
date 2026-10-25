"""Fill & Sign: put text, dates, ticks, signatures and cover-up boxes on PDF pages.

Everything is *burned into* the page (added to its drawing instructions),
so every viewer and portal shows it and nobody can drag it away later.
The original file is never changed; a cleaned copy is written instead.

Positions are in **points** (1/72 inch) on the page *as it is displayed*:
origin at the top-left, y growing downwards, after the page's own
rotation. Docly converts that to the PDF's internal coordinates, so an
item placed bottom-right stays bottom-right on rotated or offset pages.

Text uses the PDF's built-in Helvetica font with Windows-1252 ("WinAnsi")
characters: English and other Latin-script text. Characters outside that
set raise :class:`UnsupportedTextError` instead of printing as boxes.
"""

from __future__ import annotations

import io
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import numpy as np
import pikepdf
from pikepdf import Name
from PIL import Image

from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, DoclyError, InvalidPageRangeError
from docly.core.files import safe_stem
from docly.core.helvetica import ASCENT, text_width
from docly.core.image_io import load_image_bytes
from docly.core.pdf_io import save_pdf
from docly.core.pdf_ops import PdfResult, Source, all_pages, build_pdf
from docly.logger import get_logger

log = get_logger(__name__)

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
BLUE_INK: RGB = (18, 52, 160)  # a ballpoint-pen blue, as many Indian forms ask for
WHITE: RGB = (255, 255, 255)

MIN_FONT, MAX_FONT = 4.0, 72.0
MAX_TEXT = 500
LINE_HEIGHT = 1.2  # × font size
TEXT_TOP_PAD = 0.12  # × font size, space above capitals inside the box
MAX_IMAGE_SIDE = 1600  # signatures are shrunk to this before embedding
FONT_KEY = "DoclyHelv"

COVER_WARNING = (
    "Cover-up boxes hide text but don't delete it: the words underneath can still be "
    "selected or copied. Don't rely on them to remove private information."
)

DATE_FORMATS: dict[str, str] = {
    "DD/MM/YYYY": "%d/%m/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "MM/DD/YYYY": "%m/%d/%Y",
    "DD Mon YYYY": "%d %b %Y",
}


class UnsupportedTextError(DoclyError):
    """Text contains characters the built-in PDF font can't print."""


class ItemKind(str, Enum):
    TEXT = "text"  # also used for dates (the text is already formatted)
    TICK = "tick"
    CROSS = "cross"
    IMAGE = "image"  # e.g. a transparent signature
    COVER = "cover"


@dataclass(frozen=True)
class Box:
    """A rectangle on the displayed page, in points, top-left origin."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class FillItem:
    """One thing to draw on one page (0-based ``page``)."""

    kind: ItemKind
    page: int
    box: Box
    text: str = ""
    font_size: float = 12.0
    colour: RGB = BLACK
    image: bytes = field(default=b"", repr=False)  # PNG/JPG bytes for IMAGE items


# ----------------------------------------------------------------------
# Building items
# ----------------------------------------------------------------------
def text_size(text: str, font_size: float) -> tuple[float, float]:
    """Width and height in points that ``text`` needs (several lines allowed)."""
    lines = text.split("\n") or [""]
    width = max(text_width(_encode(line), font_size) for line in lines)
    return width, font_size * LINE_HEIGHT * len(lines)


def text_item(page: int, x: float, y: float, text: str, font_size: float = 12.0, colour: RGB = BLACK) -> FillItem:
    """Text whose box's top-left corner is at (x, y)."""
    w, h = text_size(text, font_size)
    return FillItem(ItemKind.TEXT, page, Box(x, y, w, h), text, font_size, colour)


def format_date(day: date, style: str = "DD/MM/YYYY") -> str:
    if style not in DATE_FORMATS:
        raise ValueError(f"Unknown date format {style!r}")
    return day.strftime(DATE_FORMATS[style])


def date_item(page: int, x: float, y: float, day: date | None = None, style: str = "DD/MM/YYYY", **kwargs) -> FillItem:
    return text_item(page, x, y, format_date(day or date.today(), style), **kwargs)


def mark_item(kind: ItemKind, page: int, x: float, y: float, size: float = 14.0, colour: RGB = BLACK) -> FillItem:
    """A tick or cross in a ``size`` × ``size`` box at (x, y)."""
    if kind not in (ItemKind.TICK, ItemKind.CROSS):
        raise ValueError("mark_item makes ticks and crosses")
    return FillItem(kind, page, Box(x, y, size, size), colour=colour)


def image_item(page: int, x: float, y: float, data: bytes, width: float) -> FillItem:
    """An image ``width`` points wide at (x, y), keeping its shape."""
    picture = load_image_bytes(data, "signature", keep_alpha=True).image
    height = width * picture.height / picture.width
    return FillItem(ItemKind.IMAGE, page, Box(x, y, width, height), image=data)


def cover_item(page: int, x: float, y: float, w: float, h: float, colour: RGB = WHITE) -> FillItem:
    return FillItem(ItemKind.COVER, page, Box(x, y, w, h), colour=colour)


def can_print(ch: str) -> bool:
    """True if the built-in PDF font can print ``ch`` (newlines count as fine)."""
    return ch == "\n" or _encodable(ch)


def check_text(text: str) -> None:
    """Raise :class:`UnsupportedTextError` naming characters Helvetica can't print."""
    bad = sorted({ch for ch in text if not can_print(ch)})
    if bad:
        shown = " ".join(bad[:8])
        raise UnsupportedTextError(
            f"These characters can't be printed with the built-in PDF font: {shown}. "
            "Docly can type English and other Latin-alphabet text."
        )


# ----------------------------------------------------------------------
# Applying items
# ----------------------------------------------------------------------
def fill_pdf(
    source: Source,
    items: Sequence[FillItem],
    suggested_name: str | None = None,
    cancel: CancelCheck | None = None,
) -> PdfResult:
    """A clean copy of ``source`` with ``items`` drawn on its pages."""
    if not items:
        raise InvalidPageRangeError("Add something to the page first.")
    for item in items:
        _validate(item, source.page_count)
    name = suggested_name or f"{_stem(source.name)}_signed.pdf"
    base = build_pdf([source], all_pages([source]), name, cancel=cancel)
    with pikepdf.open(io.BytesIO(base.data)) as pdf:
        by_page: dict[int, list[FillItem]] = {}
        for item in items:
            by_page.setdefault(item.page, []).append(item)
        for index, page_items in sorted(by_page.items()):
            if cancel is not None and cancel():
                raise CancelledError()
            draw_items(pdf, pdf.pages[index], page_items)
        data = save_pdf(pdf)
    warnings = list(base.warnings)
    if any(item.kind == ItemKind.COVER for item in items):
        warnings.append(COVER_WARNING)
    log.info("Filled %d item(s) on %d page(s)", len(items), len({i.page for i in items}))
    return PdfResult(data, base.page_count, name, warnings)


def displayed_size(page: pikepdf.Page) -> tuple[float, float]:
    """Width × height in points of ``page`` as viewers show it."""
    x0, y0, x1, y1 = _visible_box(page)
    w, h = x1 - x0, y1 - y0
    return (h, w) if _rotation(page) in (90, 270) else (w, h)


def draw_items(pdf: pikepdf.Pdf, page: pikepdf.Page, items: Sequence[FillItem]) -> None:
    """Append drawing instructions for ``items`` to ``page``."""
    _, height = displayed_size(page)
    matrix = _display_to_user(page)
    ops: list[str] = ["q", "{:.4f} {:.4f} {:.4f} {:.4f} {:.4f} {:.4f} cm".format(*matrix)]
    font_name: str | None = None
    for item in items:
        # Display space here is y-up with its origin at the bottom-left.
        x, w, h = item.box.x, item.box.w, item.box.h
        y = height - item.box.y - h
        if item.kind == ItemKind.TEXT:
            if font_name is None:
                font_name = _add_font(pdf, page)
            ops += _text_ops(item, x, y + h, font_name)
        elif item.kind in (ItemKind.TICK, ItemKind.CROSS):
            ops += _mark_ops(item, x, y, w, h)
        elif item.kind == ItemKind.IMAGE:
            image_name = page.add_resource(_image_xobject(pdf, item.image), Name.XObject, prefix="DoclyIm")
            ops += ["q", f"{w:.4f} 0 0 {h:.4f} {x:.4f} {y:.4f} cm", f"{image_name} Do", "Q"]
        elif item.kind == ItemKind.COVER:
            ops += ["q", _colour(item.colour, fill=True), f"{x:.4f} {y:.4f} {w:.4f} {h:.4f} re f", "Q"]
    ops.append("Q")
    # Wrap the existing content in q … Q so its leftover drawing state
    # (scaling, colours) can't shift or recolour what we add.
    page.contents_add(pdf.make_stream(b"q\n"), prepend=True)
    page.contents_add(pdf.make_stream(b"\nQ\n" + "\n".join(ops).encode("ascii")))


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _validate(item: FillItem, page_count: int) -> None:
    if not 0 <= item.page < page_count:
        raise InvalidPageRangeError(f"Page {item.page + 1} doesn't exist (the PDF has {page_count}).")
    box = item.box
    if not all(np.isfinite([box.x, box.y, box.w, box.h])) or box.w <= 0 or box.h <= 0:
        raise InvalidPageRangeError("An item has no size.")
    if item.kind == ItemKind.TEXT:
        if not item.text.strip():
            raise InvalidPageRangeError("A text box is empty.")
        if len(item.text) > MAX_TEXT:
            raise InvalidPageRangeError(f"Text boxes can hold up to {MAX_TEXT} characters.")
        if not MIN_FONT <= item.font_size <= MAX_FONT:
            raise InvalidPageRangeError(f"Font size must be between {MIN_FONT:g} and {MAX_FONT:g}.")
        check_text(item.text)
    if item.kind == ItemKind.IMAGE and not item.image:
        raise InvalidPageRangeError("A signature item has no image.")
    if not all(0 <= c <= 255 for c in item.colour):
        raise InvalidPageRangeError("Colours must be 0–255.")


def _visible_box(page: pikepdf.Page) -> tuple[float, float, float, float]:
    """The CropBox if there is one (that's what viewers show), else the MediaBox."""
    media = [float(v) for v in page.mediabox]
    crop = page.obj.get(Name.CropBox)
    box = [float(v) for v in crop] if crop is not None else media
    x0, x1 = sorted((box[0], box[2]))
    y0, y1 = sorted((box[1], box[3]))
    return x0, y0, x1, y1


def _rotation(page: pikepdf.Page) -> int:
    try:
        return int(page.obj.get(Name.Rotate, 0)) % 360
    except (TypeError, ValueError):
        return 0


def _display_to_user(page: pikepdf.Page) -> tuple[float, float, float, float, float, float]:
    """PDF matrix [a b c d e f] from display space (y-up, origin bottom-left) to the page's own space.

    A page shown rotated 90° clockwise has its bottom-left corner at the
    top-left of the screen, and so on round.
    """
    x0, y0, x1, y1 = _visible_box(page)
    rotation = _rotation(page)
    if rotation == 90:
        return (0, 1, -1, 0, x1, y0)
    if rotation == 180:
        return (-1, 0, 0, -1, x1, y1)
    if rotation == 270:
        return (0, -1, 1, 0, x0, y1)
    return (1, 0, 0, 1, x0, y0)


def _colour(rgb: RGB, fill: bool) -> str:
    r, g, b = (c / 255 for c in rgb)
    return f"{r:.4f} {g:.4f} {b:.4f} {'rg' if fill else 'RG'}"


def _encodable(ch: str) -> bool:
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return ord(ch) >= 32 and ord(ch) != 127


def _encode(text: str) -> bytes:
    return text.encode("cp1252", errors="replace")


def _pdf_string(data: bytes) -> str:
    out = []
    for b in data:
        if b in (0x28, 0x29, 0x5C):  # ( ) \
            out.append("\\" + chr(b))
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _text_ops(item: FillItem, x: float, top: float, font: str) -> list[str]:
    size = item.font_size
    first_baseline = top - size * TEXT_TOP_PAD - size * ASCENT / 1000.0
    ops = ["BT", _colour(item.colour, fill=True), f"{font} {size:.2f} Tf", f"{size * LINE_HEIGHT:.4f} TL"]
    ops.append(f"1 0 0 1 {x:.4f} {first_baseline:.4f} Tm")
    for index, line in enumerate(item.text.split("\n")):
        if index:
            ops.append("T*")
        ops.append(f"{_pdf_string(_encode(line))} Tj")
    ops.append("ET")
    return ops


def _mark_ops(item: FillItem, x: float, y: float, w: float, h: float) -> list[str]:
    def at(fx: float, fy: float) -> str:  # fractions of the box, y-up
        return f"{x + fx * w:.4f} {y + fy * h:.4f}"

    width = max(0.6, 0.12 * min(w, h))
    ops = ["q", _colour(item.colour, fill=False), f"{width:.4f} w", "1 J", "1 j"]
    if item.kind == ItemKind.TICK:
        ops += [f"{at(0.12, 0.5)} m", f"{at(0.4, 0.18)} l", f"{at(0.9, 0.85)} l", "S"]
    else:
        ops += [f"{at(0.15, 0.15)} m", f"{at(0.85, 0.85)} l", f"{at(0.15, 0.85)} m", f"{at(0.85, 0.15)} l", "S"]
    ops.append("Q")
    return ops


def _add_font(pdf: pikepdf.Pdf, page: pikepdf.Page) -> str:
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica, Encoding=Name.WinAnsiEncoding
        )
    )
    return str(page.add_resource(font, Name.Font, prefix=FONT_KEY))


def _image_xobject(pdf: pikepdf.Pdf, data: bytes) -> pikepdf.Stream:
    """RGB image (Flate) plus a soft mask when it has see-through parts."""
    picture = load_image_bytes(data, "signature", keep_alpha=True).image
    if max(picture.size) > MAX_IMAGE_SIDE:
        picture = picture.copy()
        picture.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    rgba = picture.convert("RGBA")
    rgb = rgba.convert("RGB")
    image = pdf.make_stream(zlib.compress(rgb.tobytes(), 9))
    image.Type, image.Subtype = Name.XObject, Name.Image
    image.Width, image.Height = rgb.size
    image.ColorSpace, image.BitsPerComponent = Name.DeviceRGB, 8
    image.Filter = Name.FlateDecode
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 255:
        mask = pdf.make_stream(zlib.compress(alpha.tobytes(), 9))
        mask.Type, mask.Subtype = Name.XObject, Name.Image
        mask.Width, mask.Height = alpha.size
        mask.ColorSpace, mask.BitsPerComponent = Name.DeviceGray, 8
        mask.Filter = Name.FlateDecode
        image.SMask = mask
    return image


def _stem(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
    return safe_stem(stem, fallback="document")
