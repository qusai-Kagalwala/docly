"""Shrink a PDF to fit a size limit, without Ghostscript.

What makes a typical upload big is the **pictures inside it**: scanned
pages and phone photos. So Docly works in two steps:

1. **Lossless tidy-up** — drop unused objects, compress anything stored
   uncompressed, pack small objects together. Nothing visible changes.
   If that already fits, we stop.
2. **Re-save the images** at a "level": a resolution cap plus a JPEG
   quality. Levels run from gentle (300 DPI, quality 85) down to a
   *readability floor* (100 DPI, quality 40). A binary search finds the
   gentlest level that fits.

If even the floor doesn't fit, the result is the smallest readable
version with an honest explanation (usually: most of the file is fonts
and text, which can't be shrunk without changing how the pages look).

Images Docly never re-saves (they're left exactly as they were): images
with transparency masks or decode tricks, stencil masks, black-and-white
fax-style scans (JBIG2/CCITT), JPEG 2000, CMYK/indexed colour, anything
not 8 bits per channel, and images too small to matter.
"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pikepdf
from pikepdf import Name
from PIL import Image

from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, CorruptPdfError
from docly.core.image_io import MAX_PIXELS
from docly.core.pdf_io import save_pdf
from docly.core.pdf_ops import PdfResult
from docly.logger import get_logger

log = get_logger(__name__)

ProgressCallback = Callable[[int, int], None]  # (steps done, total steps)


@dataclass(frozen=True)
class Level:
    """How hard to squeeze the images."""

    dpi: int  # longest image side is capped at this many pixels per inch of page
    quality: int  # JPEG quality


#: Gentlest first. The last one is the readability floor.
LEVELS: tuple[Level, ...] = (
    Level(300, 85),
    Level(250, 80),
    Level(200, 75),
    Level(170, 70),
    Level(150, 62),
    Level(130, 55),
    Level(115, 48),
    Level(100, 40),
)

MIN_IMAGE_SIDE = 48  # smaller images aren't worth touching
MIN_IMAGE_BYTES = 8 * 1024
_SKIP_FILTERS = {Name.JBIG2Decode, Name.CCITTFaxDecode, Name.JPXDecode}
_PAD_KEY = Name("/DoclyPadding")  # private catalog key; viewers ignore it

NOT_IMAGES_REASON = (
    "Most of this file is text, fonts and drawings. Docly can't shrink those "
    "without changing how the pages look."
)
FLOOR_REASON = (
    "Its pictures are already as small as Docly makes them while staying "
    "readable. Try splitting the file, or scanning at a lower resolution."
)


@dataclass(frozen=True)
class SizeBreakdown:
    """Roughly where the bytes go (stored stream sizes)."""

    total: int
    images: int
    fonts: int

    @property
    def other(self) -> int:
        return max(0, self.total - self.images - self.fonts)

    @property
    def image_share(self) -> float:
        return self.images / self.total if self.total else 0.0


@dataclass
class CompressResult:
    """The smaller PDF and how it was made."""

    data: bytes
    original_bytes: int
    target_bytes: int | None  # None: no size limit was asked for
    met_target: bool
    level: Level | None  # None: only the lossless tidy-up was needed
    images_changed: int = 0
    padded: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.data)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def size_breakdown(data: bytes) -> SizeBreakdown:
    """How many bytes of ``data`` are images, fonts and everything else."""
    with _open(data) as pdf:
        images = fonts = 0
        font_files: set[tuple[int, int]] = set()
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Dictionary) and obj.get(Name.Type) == Name.FontDescriptor:
                for key in (Name.FontFile, Name.FontFile2, Name.FontFile3):
                    stream = obj.get(key)
                    if isinstance(stream, pikepdf.Stream) and stream.objgen not in font_files:
                        font_files.add(stream.objgen)
                        fonts += _stored_size(stream)
            elif isinstance(obj, pikepdf.Stream) and obj.get(Name.Subtype) == Name.Image:
                images += _stored_size(obj)
    return SizeBreakdown(len(data), images, fonts)


def optimise(data: bytes) -> bytes:
    """Lossless tidy-up. Never returns something larger than ``data``."""
    with _open(data) as pdf:
        _tidy(pdf)
        out = save_pdf(pdf)
    return out if len(out) < len(data) else data


def compress_to_target(
    data: bytes,
    target_bytes: int | None,
    min_bytes: int | None = None,
    grayscale: bool = False,
    cancel: CancelCheck | None = None,
    progress: ProgressCallback | None = None,
) -> CompressResult:
    """Make ``data`` (a PDF) at most ``target_bytes`` long, as gently as possible.

    ``target_bytes=None`` means no limit: just the lossless tidy-up (and
    greyscale pictures, if asked). ``min_bytes`` pads the result up to a portal's minimum size. ``grayscale``
    turns pictures grey (text and drawings keep their colour). Raises
    :class:`CancelledError` or :class:`CorruptPdfError`.
    """
    if target_bytes is not None and target_bytes <= 0:
        raise ValueError("target_bytes must be positive")
    original = len(data)
    report = _Progress(progress)

    # 1. Lossless.
    _check(cancel)
    tidy = optimise(data)
    report.trial_done()
    if not grayscale and (target_bytes is None or len(tidy) <= target_bytes):
        return _finish(CompressResult(tidy, original, target_bytes, True, None), min_bytes, report)

    # 2. Images. Try the floor first: if even that doesn't fit, stop there.
    page_inches = _longest_page_inches(tidy)
    report.images = _count_images(tidy)

    def attempt(level: Level) -> tuple[bytes, int]:
        result = _recompress(tidy, level, page_inches, grayscale, cancel, report.image_done)
        report.trial_done()
        return result

    if target_bytes is None:  # greyscale only, at the gentlest level
        grey, changed = attempt(LEVELS[0])
        best = grey if len(grey) < len(tidy) or changed else tidy
        return _finish(CompressResult(best, original, None, True, LEVELS[0], changed), min_bytes, report)

    floor_data, floor_changed = attempt(LEVELS[-1])
    if len(floor_data) > target_bytes:
        best, changed = (floor_data, floor_changed) if len(floor_data) < len(tidy) else (tidy, 0)
        breakdown = size_breakdown(best)
        reason = FLOOR_REASON if breakdown.image_share >= 0.5 else NOT_IMAGES_REASON
        result = CompressResult(best, original, target_bytes, False, LEVELS[-1] if changed else None, changed)
        result.notes.append(reason)
        log.info(
            "PDF compress: best %d bytes for target %d (images %.0f%%)",
            len(best), target_bytes, breakdown.image_share * 100,
        )  # fmt: skip
        report.finish()
        return result

    # 3. Binary search for the gentlest level that fits.
    best_level, best_data, best_changed = LEVELS[-1], floor_data, floor_changed
    low, high = 0, len(LEVELS) - 2
    while low <= high:
        mid = (low + high) // 2
        candidate, changed = attempt(LEVELS[mid])
        if len(candidate) <= target_bytes:
            best_level, best_data, best_changed = LEVELS[mid], candidate, changed
            high = mid - 1
        else:
            low = mid + 1

    # 4. Fine-tune between the level that fits and the one above it that
    #    didn't: first keep the sharper resolution, then a middle quality.
    index = LEVELS.index(best_level)
    if index > 0:
        above = LEVELS[index - 1]
        for level in (Level(above.dpi, best_level.quality), Level(best_level.dpi, (above.quality + best_level.quality) // 2)):
            if level == best_level or level == above:
                continue
            candidate, changed = attempt(level)
            if len(candidate) <= target_bytes:
                best_level, best_data, best_changed = level, candidate, changed
                break
    result = CompressResult(best_data, original, target_bytes, True, best_level, best_changed)
    return _finish(result, min_bytes, report)


class _Progress:
    """Turns "image n of trial m" into a steadily rising (done, total)."""

    TRIALS = 1 + 1 + math.ceil(math.log2(len(LEVELS))) + 2  # tidy, floor, search, fine-tune

    def __init__(self, callback: ProgressCallback | None) -> None:
        self.callback = callback
        self.images = 0
        self.trials = 0
        self.in_trial = 0

    @property
    def total(self) -> int:
        return self.TRIALS * (self.images + 1)

    def image_done(self) -> None:
        self.in_trial += 1
        self._emit()

    def trial_done(self) -> None:
        self.trials += 1
        self.in_trial = 0
        self._emit()

    def finish(self) -> None:
        if self.callback is not None:
            self.callback(self.total, self.total)

    def _emit(self) -> None:
        if self.callback is not None:
            done = self.trials * (self.images + 1) + self.in_trial
            self.callback(min(done, self.total - 1), self.total)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _open(data: bytes) -> pikepdf.Pdf:
    try:
        return pikepdf.open(io.BytesIO(data))
    except (pikepdf.PdfError, ValueError, RuntimeError):
        raise CorruptPdfError("The PDF couldn't be read for compressing.") from None


def _check(cancel: CancelCheck | None) -> None:
    if cancel is not None and cancel():
        raise CancelledError()


def _stored_size(stream: pikepdf.Stream) -> int:
    try:
        return len(stream.read_raw_bytes())
    except pikepdf.PdfError:
        return 0


def _tidy(pdf: pikepdf.Pdf) -> None:
    try:
        pdf.remove_unreferenced_resources()
    except pikepdf.PdfError:
        log.debug("remove_unreferenced_resources failed", exc_info=True)
    for page in pdf.pages:  # embedded page thumbnails are never needed
        if Name.Thumb in page.obj:
            del page.obj[Name.Thumb]


def _longest_page_inches(data: bytes) -> float:
    with _open(data) as pdf:
        longest = 0.0
        for page in pdf.pages:
            try:
                box = page.mediabox
                longest = max(longest, abs(float(box[2]) - float(box[0])), abs(float(box[3]) - float(box[1])))
            except (TypeError, ValueError, IndexError, pikepdf.PdfError):
                continue
    return (longest or 842.0) / 72.0


def _count_images(data: bytes) -> int:
    with _open(data) as pdf:
        return sum(1 for obj in pdf.objects if isinstance(obj, pikepdf.Stream) and obj.get(Name.Subtype) == Name.Image)


def _recompress(
    data: bytes,
    level: Level,
    page_inches: float,
    grayscale: bool,
    cancel: CancelCheck | None,
    on_image: Callable[[], None] | None = None,
) -> tuple[bytes, int]:
    """Re-save every suitable image at ``level``. Returns (pdf bytes, images changed)."""
    max_side = max(MIN_IMAGE_SIDE, round(level.dpi * page_inches))
    changed = 0
    with _open(data) as pdf:
        for obj in list(pdf.objects):
            _check(cancel)
            if not isinstance(obj, pikepdf.Stream) or obj.get(Name.Subtype) != Name.Image:
                continue
            try:
                if _recompress_image(obj, level.quality, max_side, grayscale):
                    changed += 1
            except Exception:  # one odd image must never stop the rest
                log.info("Left an image unchanged (could not re-save it)", exc_info=True)
            if on_image is not None:
                on_image()
        _tidy(pdf)
        return save_pdf(pdf), changed


def _recompress_image(obj: pikepdf.Stream, quality: int, max_side: int, grayscale: bool) -> bool:
    """Re-save one image XObject as JPEG if that makes it smaller. True if changed."""
    if not _suitable(obj):
        return False
    image = pikepdf.PdfImage(obj).as_pil_image()
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if grayscale and image.mode != "L":
        image = image.convert("L")
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True, subsampling=2 if quality < 80 else 0)
    encoded = buffer.getvalue()
    made_grey = grayscale and _colour_channels(obj.get(Name.ColorSpace)) == 3
    if len(encoded) >= _stored_size(obj) and not made_grey:
        return False  # not smaller: keep the original
    obj.write(encoded, filter=Name.DCTDecode)
    obj.Width = image.width
    obj.Height = image.height
    obj.BitsPerComponent = 8
    obj.ColorSpace = Name.DeviceGray if image.mode == "L" else Name.DeviceRGB
    for key in (Name.DecodeParms, Name.Decode):
        if key in obj:
            del obj[key]
    return True


def _suitable(obj: pikepdf.Stream) -> bool:
    if obj.get(Name.ImageMask, False) or Name.SMask in obj or Name.Mask in obj or Name.Decode in obj:
        return False
    if int(obj.get(Name.BitsPerComponent, 0)) != 8:
        return False
    filters = obj.get(Name.Filter)
    names = list(filters) if isinstance(filters, pikepdf.Array) else ([filters] if filters is not None else [])
    if any(f in _SKIP_FILTERS for f in names):
        return False
    width, height = int(obj.get(Name.Width, 0)), int(obj.get(Name.Height, 0))
    if min(width, height) < MIN_IMAGE_SIDE or width * height > MAX_PIXELS:
        return False
    if _stored_size(obj) < MIN_IMAGE_BYTES:
        return False
    return _colour_channels(obj.get(Name.ColorSpace)) in (1, 3)


def _colour_channels(space: object) -> int | None:
    """1 or 3 for grey/RGB colour spaces Docly can safely re-save, else None."""
    if space == Name.DeviceGray:
        return 1
    if space == Name.DeviceRGB:
        return 3
    if isinstance(space, pikepdf.Array) and len(space) == 2 and space[0] == Name.ICCBased:
        try:
            n = int(space[1].get(Name.N, 0))
        except (AttributeError, TypeError, ValueError):
            return None
        return n if n in (1, 3) else None
    return None


def _finish(result: CompressResult, min_bytes: int | None, report: _Progress) -> CompressResult:
    if min_bytes is not None and result.size_bytes < min_bytes:
        result.data = _pad(result.data, min_bytes)
        result.padded = True
        result.notes.append("Added padding so the file meets the portal's minimum size.")
        if result.target_bytes is not None and result.size_bytes > result.target_bytes:
            result.met_target = False  # the size window was too narrow to pad into
    report.finish()
    return result


def _pad(data: bytes, min_bytes: int) -> bytes:
    """Grow ``data`` to at least ``min_bytes`` with an ignored, incompressible stream."""
    rng = random.Random(len(data))  # deterministic: same input, same output
    extra = min_bytes - len(data) + 256
    for _ in range(4):
        with _open(data) as pdf:
            filler = pdf.make_stream(rng.randbytes(max(1, extra)))
            pdf.Root[_PAD_KEY] = filler
            padded = save_pdf(pdf)
        if len(padded) >= min_bytes:
            return padded
        extra += min_bytes - len(padded) + 256
    return padded


def apply_to_result(
    result: PdfResult,
    target_bytes: int | None,
    min_bytes: int | None = None,
    grayscale: bool = False,
    cancel: CancelCheck | None = None,
    progress: ProgressCallback | None = None,
) -> PdfResult:
    """Shrink a built PDF in place of its data; adds the size check and notes."""
    compressed = compress_to_target(result.data, target_bytes, min_bytes, grayscale, cancel, progress)
    return replace(
        result,
        data=compressed.data,
        target_bytes=target_bytes,
        met_target=compressed.met_target,
        warnings=list(result.warnings) + compressed.notes,
    )
