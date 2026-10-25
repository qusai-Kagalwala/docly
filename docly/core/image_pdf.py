"""Put an image on a PDF page.

* JPEG photos are embedded **as they are**: the original bytes go straight
  into the PDF, so there is no re-compression and no quality loss. If the
  camera stored the photo sideways with a rotation tag, the *page* is
  rotated instead of re-encoding the picture.
* Other formats (PNG, WebP, …) are stored losslessly.
* Pages are A4 by default, turned portrait or landscape to match the image;
  the image is scaled to fit and centred.
"""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass
from enum import Enum

import pikepdf
from pikepdf import Array, Dictionary, Name
from PIL import Image

from docly.core.image_io import LoadedImage, load_image_bytes

POINTS_PER_INCH = 72.0


class PageSize(str, Enum):
    """Paper for images → PDF."""

    A4 = "a4"
    LETTER = "letter"
    FIT = "fit"  # page has the image's shape (long side as long as A4's)


#: Portrait width × height in points.
PAPER: dict[PageSize, tuple[float, float]] = {
    PageSize.A4: (595.276, 841.89),
    PageSize.LETTER: (612.0, 792.0),
}

#: EXIF orientation → clockwise page rotation that shows the photo upright.
_EXIF_ROTATION = {1: 0, 3: 180, 6: 90, 8: 270}
_PASSTHROUGH_MODES = {"RGB": Name.DeviceRGB, "L": Name.DeviceGray}


@dataclass(frozen=True)
class ImageOnPage:
    """How an image was placed (useful for tests and the UI)."""

    passthrough: bool  # original JPEG bytes embedded unchanged
    rotate: int  # page rotation applied for an EXIF tag
    width_px: int
    height_px: int


def add_image_page(
    pdf: pikepdf.Pdf,
    data: bytes,
    name: str = "image",
    page_size: PageSize = PageSize.A4,
    margin_pt: float = 0.0,
) -> ImageOnPage:
    """Append a page showing the image in ``data`` (any supported format).

    Raises the usual image errors (unsupported, too large, damaged) from
    :mod:`docly.core.image_io`.
    """
    loaded = load_image_bytes(data, name)  # validates everything first
    passthrough = _jpeg_passthrough(data, loaded)
    if passthrough is not None:
        stream, (w, h), rotate = passthrough
        xobject = pdf.make_stream(stream)
        xobject.Type = Name.XObject
        xobject.Subtype = Name.Image
        xobject.Width, xobject.Height = w, h
        xobject.ColorSpace = _PASSTHROUGH_MODES[_jpeg_mode(data)]
        xobject.BitsPerComponent = 8
        xobject.Filter = Name.DCTDecode
    else:
        rgb = loaded.image  # rotation already applied, RGB, transparency on white
        w, h = rgb.size
        rotate = 0
        xobject = pdf.make_stream(zlib.compress(rgb.tobytes(), 6))
        xobject.Type = Name.XObject
        xobject.Subtype = Name.Image
        xobject.Width, xobject.Height = w, h
        xobject.ColorSpace = Name.DeviceRGB
        xobject.BitsPerComponent = 8
        xobject.Filter = Name.FlateDecode

    page_w, page_h = _page_box(w, h, page_size)
    draw_w, draw_h, x, y = _fit(w, h, page_w, page_h, margin_pt)
    content = f"q {draw_w:.4f} 0 0 {draw_h:.4f} {x:.4f} {y:.4f} cm /Im0 Do Q".encode()
    page = Dictionary(
        Type=Name.Page,
        MediaBox=Array([0, 0, round(page_w, 3), round(page_h, 3)]),
        Resources=Dictionary(XObject=Dictionary(Im0=xobject)),
        Contents=pdf.make_stream(content),
    )
    if rotate:
        page.Rotate = rotate
    pdf.pages.append(pikepdf.Page(page))
    return ImageOnPage(passthrough is not None, rotate, w, h)


# ----------------------------------------------------------------------
def _jpeg_mode(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as probe:
        return probe.mode


def _jpeg_passthrough(data: bytes, loaded: LoadedImage) -> tuple[bytes, tuple[int, int], int] | None:
    """Original JPEG bytes + stored size + page rotation, if they can be used as-is.

    Not possible for CMYK JPEGs (Adobe stores them inverted), mirrored
    orientation tags, or multi-picture (MPO) files.
    """
    if loaded.source_format != "JPEG":
        return None
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.mode not in _PASSTHROUGH_MODES:
                return None
            orientation = probe.getexif().get(0x0112, 1) or 1
            size = probe.size
    except Exception:
        return None
    if orientation not in _EXIF_ROTATION:
        return None  # mirrored: re-encode losslessly instead
    return data, size, _EXIF_ROTATION[orientation]


def _page_box(w: int, h: int, page_size: PageSize) -> tuple[float, float]:
    """Page width × height in points, turned to match the image's shape."""
    if page_size == PageSize.FIT:
        long_side = PAPER[PageSize.A4][1]
        scale = long_side / max(w, h)
        return w * scale, h * scale
    short, long = PAPER[page_size]
    return (long, short) if w > h else (short, long)


def _fit(w: int, h: int, page_w: float, page_h: float, margin: float) -> tuple[float, float, float, float]:
    """Largest size of a w × h image inside the page, centred."""
    avail_w = max(1.0, page_w - 2 * margin)
    avail_h = max(1.0, page_h - 2 * margin)
    scale = min(avail_w / w, avail_h / h)
    draw_w, draw_h = w * scale, h * scale
    return draw_w, draw_h, (page_w - draw_w) / 2, (page_h - draw_h) / 2
