"""Compress an image into a preset's file-size window.

Strategy for JPEG:
1. Binary-search the quality (95 → 10) for the highest quality that fits.
2. If even the lowest quality is too big and the preset lets the size
   change, shrink the image and search again.
3. If the file is below the minimum, raise quality to the top, then enlarge
   (if allowed), and finally pad the file with a harmless comment block.
4. If nothing works, return the best result with an honest message.

Outputs contain no EXIF/GPS or other metadata — only the DPI.
"""

from __future__ import annotations

import io
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, PngImagePlugin

from docly.core.errors import CancelledError
from docly.core.resize import has_fixed_size, resize_by
from docly.presets.models import FileFormat, Preset

QUALITY_MAX = 95
QUALITY_MIN = 10
QUALITY_TOP = 100  # used only when the file is too small
GOOD_QUALITY = 75  # below this, prefer a smaller image over a blockier one
PREFERRED_MIN_SIDE = 400  # ...but don't shrink below this just for quality
MAX_SHRINKS = 8
MAX_ENLARGES = 3
PNG_COLOURS = (256, 128, 64, 32, 16)
PAD_MARGIN = 256  # bytes of headroom above kb_min when padding

CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class ByteWindow:
    """Allowed output size in bytes. ``None`` means no limit on that side."""

    low: int | None
    high: int | None
    relaxed: bool = False  # the safe window was impossible, so 1024-byte KB was used

    def fits(self, size: int) -> bool:
        return (self.low is None or size >= self.low) and (self.high is None or size <= self.high)


def byte_window(preset: Preset) -> ByteWindow:
    """Target size that passes whether a portal counts 1 KB as 1000 or 1024 bytes.

    Aim *below* ``kb_max × 1000`` and *above* ``kb_min × 1024``.
    """
    low = math.ceil(preset.kb_min * 1024) if preset.kb_min is not None else None
    high = math.floor(preset.kb_max * 1000) if preset.kb_max is not None else None
    if low is not None and high is not None and low > high:
        return ByteWindow(low, math.floor(preset.kb_max * 1024), relaxed=True)  # type: ignore[operator]
    return ByteWindow(low, high)


@dataclass(frozen=True)
class CompressResult:
    """The encoded file and how it was produced."""

    data: bytes
    format: FileFormat
    width: int
    height: int
    quality: int | None  # JPEG quality, or None for PNG
    hit_target: bool
    shrunk: bool = False
    enlarged: bool = False
    padded: bool = False
    attempts: int = 0
    message: str = ""

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class _Encoder:
    """Encodes images and counts attempts; checks for cancellation."""

    def __init__(self, fmt: FileFormat, dpi: int | None, cancel: CancelCheck | None) -> None:
        self.fmt = fmt
        self.dpi = dpi
        self.cancel = cancel
        self.attempts = 0

    def jpeg(self, image: Image.Image, quality: int, full_colour: bool = False) -> bytes:
        self._tick()
        buffer = io.BytesIO()
        options: dict = {
            "quality": quality,
            "optimize": True,
            "progressive": False,  # some portals reject progressive JPEGs
            "subsampling": 0 if full_colour else 2,  # 4:4:4 vs 4:2:0
        }
        if self.dpi:
            options["dpi"] = (self.dpi, self.dpi)
        image.save(buffer, "JPEG", **options)
        return buffer.getvalue()

    def png(self, image: Image.Image, padding: int = 0) -> bytes:
        self._tick()
        buffer = io.BytesIO()
        options: dict = {"optimize": True}
        if self.dpi:
            options["dpi"] = (self.dpi, self.dpi)
        if padding > 0:
            info = PngImagePlugin.PngInfo()
            info.add_text("Comment", " " * padding)  # uncompressed tEXt chunk
            options["pnginfo"] = info
        image.save(buffer, "PNG", **options)
        return buffer.getvalue()

    def _tick(self) -> None:
        if self.cancel is not None and self.cancel():
            raise CancelledError()
        self.attempts += 1


def compress_to_target(
    image: Image.Image,
    preset: Preset,
    fmt: FileFormat | None = None,
    cancel: CancelCheck | None = None,
) -> CompressResult:
    """Encode ``image`` so its file size fits the preset. Never raises on a
    missed target; check :attr:`CompressResult.hit_target` instead."""
    chosen = fmt or preset.formats[0]
    if not preset.accepts(chosen):
        raise ValueError(f"Preset {preset.id} does not accept {chosen.value}")
    if chosen == FileFormat.PDF:
        raise ValueError("PDF output is handled by the PDF engine")
    encoder = _Encoder(chosen, preset.dpi, cancel)
    window = byte_window(preset)
    if chosen == FileFormat.PNG:
        return _compress_png(image, preset, window, encoder)
    return _compress_jpeg(image, preset, window, encoder)


# ----------------------------------------------------------------------
# JPEG
# ----------------------------------------------------------------------
def _best_quality_under(image: Image.Image, high: int, enc: _Encoder) -> tuple[tuple[bytes, int] | None, int]:
    """Highest quality whose file is ≤ ``high`` bytes.

    Returns ``((data, quality), smallest_size)``; the first item is ``None``
    when even the lowest quality is too big.
    """
    top = enc.jpeg(image, QUALITY_MAX)
    if len(top) <= high:
        return (top, QUALITY_MAX), len(top)
    bottom = enc.jpeg(image, QUALITY_MIN)
    if len(bottom) > high:
        return None, len(bottom)
    best, best_q = bottom, QUALITY_MIN
    lo, hi = QUALITY_MIN + 1, QUALITY_MAX - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        data = enc.jpeg(image, mid)
        if len(data) <= high:
            best, best_q = data, mid
            lo = mid + 1
        else:
            hi = mid - 1
    return (best, best_q), len(bottom)


def _compress_jpeg(image: Image.Image, preset: Preset, window: ByteWindow, enc: _Encoder) -> CompressResult:
    shrunk = enlarged = False
    current = image

    # 1. Fit under the maximum, shrinking if allowed.
    if window.high is None:
        data, quality = enc.jpeg(current, QUALITY_MAX), QUALITY_MAX
    else:
        found, smallest = _best_quality_under(current, window.high, enc)
        shrinks = 0
        while found is None and shrinks < MAX_SHRINKS:
            scale = min(0.92, max(0.5, math.sqrt(window.high / smallest) * 0.95))
            smaller = resize_by(current, scale, preset)
            if smaller is None:
                break
            current, shrunk, shrinks = smaller, True, shrinks + 1
            found, smallest = _best_quality_under(current, window.high, enc)
        if found is None:
            data = enc.jpeg(current, QUALITY_MIN)
            return _result(
                data, FileFormat.JPG, current, QUALITY_MIN, False, enc, shrunk=shrunk,
                message=_too_big_message(len(data), window, preset),
            )  # fmt: skip
        data, quality = found

        # 1b. A big photo squeezed to low quality looks blocky. When the
        # preset lets the size change, trade resolution for quality instead.
        tries = 0
        while quality < GOOD_QUALITY and tries < MAX_SHRINKS and not has_fixed_size(preset):
            tries += 1
            reference = enc.jpeg(current, GOOD_QUALITY)
            scale = min(0.92, max(0.5, math.sqrt(window.high / len(reference)) * 0.95))
            if min(current.size) * scale < PREFERRED_MIN_SIDE:
                break
            smaller = resize_by(current, scale, preset)
            if smaller is None:
                break
            candidate = _best_quality_under(smaller, window.high, enc)[0]
            if candidate is None or candidate[1] <= quality:
                break
            current, shrunk = smaller, True
            data, quality = candidate

    # 2. Reach the minimum.
    if window.low is not None and len(data) < window.low:
        data, quality = _raise_quality(current, window, enc, data, quality)
        enlarges = 0
        while len(data) < window.low and enlarges < MAX_ENLARGES:
            scale = min(2.0, max(1.1, math.sqrt(window.low / len(data)) * 1.05))
            bigger = resize_by(current, scale, preset)
            if bigger is None:
                break
            current, enlarged, enlarges = bigger, True, enlarges + 1
            found = _best_quality_under(current, window.high, enc)[0] if window.high else None
            data, quality = found if found else (enc.jpeg(current, QUALITY_MAX), QUALITY_MAX)
            if len(data) < window.low:
                data, quality = _raise_quality(current, window, enc, data, quality)
        if len(data) < window.low:
            padded = _pad_jpeg(data, window.low + PAD_MARGIN)
            if window.high is not None and len(padded) > window.high:
                padded = _pad_jpeg(data, window.low)
            return _result(padded, FileFormat.JPG, current, quality, window.fits(len(padded)), enc,
                           shrunk=shrunk, enlarged=enlarged, padded=True,
                           message="Padded the file to meet the minimum size; the picture is unchanged.")

    return _result(data, FileFormat.JPG, current, quality, window.fits(len(data)), enc,
                   shrunk=shrunk, enlarged=enlarged)


def _raise_quality(
    image: Image.Image, window: ByteWindow, enc: _Encoder, data: bytes, quality: int
) -> tuple[bytes, int]:
    """Try top quality with full colour detail; keep it only if it still fits."""
    for q, full in ((QUALITY_TOP, False), (QUALITY_TOP, True)):
        candidate = enc.jpeg(image, q, full_colour=full)
        if window.high is not None and len(candidate) > window.high:
            break
        data, quality = candidate, q
        if window.low is not None and len(data) >= window.low:
            break
    return data, quality


def _pad_jpeg(data: bytes, target: int) -> bytes:
    """Insert JPEG comment (COM) segments after the start marker until the
    file reaches ``target`` bytes. Image viewers and portals ignore them."""
    missing = target - len(data)
    if missing <= 0 or data[:2] != b"\xff\xd8":
        return data
    # Keep the JFIF header (APP0, which holds the DPI) right after the start
    # marker, as strict readers expect, and put the padding after it.
    insert_at = 2
    if data[2:4] == b"\xff\xe0":
        insert_at = 4 + struct.unpack(">H", data[4:6])[0]
    segments = []
    while missing > 0:
        payload = max(1, min(missing - 4, 65533))
        segments.append(b"\xff\xfe" + struct.pack(">H", payload + 2) + b" " * payload)
        missing -= payload + 4
    return data[:insert_at] + b"".join(segments) + data[insert_at:]


# ----------------------------------------------------------------------
# PNG
# ----------------------------------------------------------------------
def _compress_png(image: Image.Image, preset: Preset, window: ByteWindow, enc: _Encoder) -> CompressResult:
    current = image
    shrunk = False
    data = enc.png(current)
    candidate_image = current

    if window.high is not None and len(data) > window.high:
        for colours in PNG_COLOURS:
            quantized = current.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
            data = enc.png(quantized)
            candidate_image = quantized
            if len(data) <= window.high:
                break
        shrinks = 0
        while len(data) > window.high and shrinks < MAX_SHRINKS:
            scale = min(0.92, max(0.5, math.sqrt(window.high / len(data)) * 0.95))
            smaller = resize_by(current, scale, preset)
            if smaller is None:
                break
            current, shrunk, shrinks = smaller, True, shrinks + 1
            candidate_image = current.quantize(colors=PNG_COLOURS[-1], method=Image.Quantize.MEDIANCUT)
            data = enc.png(candidate_image)
        if len(data) > window.high:
            return _result(data, FileFormat.PNG, current, None, False, enc, shrunk=shrunk,
                           message=_too_big_message(len(data), window, preset))

    if window.low is not None and len(data) < window.low:
        padding = window.low + PAD_MARGIN - len(data)
        padded = enc.png(candidate_image, padding)
        if window.high is not None and len(padded) > window.high:
            padded = enc.png(candidate_image, window.low - len(data) + 32)
        return _result(padded, FileFormat.PNG, current, None, window.fits(len(padded)), enc,
                       shrunk=shrunk, padded=True,
                       message="Padded the file to meet the minimum size; the picture is unchanged.")
    return _result(data, FileFormat.PNG, current, None, window.fits(len(data)), enc, shrunk=shrunk)


# ----------------------------------------------------------------------
def _result(
    data: bytes,
    fmt: FileFormat,
    image: Image.Image,
    quality: int | None,
    hit: bool,
    enc: _Encoder,
    *,
    shrunk: bool = False,
    enlarged: bool = False,
    padded: bool = False,
    message: str = "",
) -> CompressResult:
    width, height = image.size
    if not message and shrunk:
        message = f"Reduced to {width} × {height} px to fit the file-size limit."
    return CompressResult(data, fmt, width, height, quality, hit, shrunk, enlarged, padded, enc.attempts, message)


def _too_big_message(size: int, window: ByteWindow, preset: Preset) -> str:
    achieved = size / 1024
    limit = (window.high or 0) / 1000
    advice = (
        "This preset needs an exact pixel size, so Docly can't make the image smaller. "
        if has_fixed_size(preset)
        else ""
    )
    return (
        f"Best achieved is {achieved:.1f} KB, still over the {limit:g} KB limit. {advice}"
        "A plainer background or a less detailed photo compresses better."
    )
