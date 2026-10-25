"""Safe image loading.

Every input is treated as untrusted. Loading checks the file size, sniffs
the real format from the bytes (not the extension), refuses images with
absurd pixel counts before decoding them, fixes phone rotation, and
returns a plain RGB image that the rest of the engine can rely on.
"""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from docly.core.errors import CorruptImageError, FileTooLargeError, ImageTooLargeError, UnsupportedFormatError
from docly.core.files import read_bytes
from docly.logger import get_logger

log = get_logger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_PIXELS = 100_000_000  # 100 megapixels
#: Above this many pixels, big JPEGs are decoded at reduced size (fast, low memory).
DRAFT_PIXELS = 24_000_000

#: Pillow format names Docly accepts. MPO is the JPEG variant some cameras write.
SUPPORTED_FORMATS = frozenset({"JPEG", "MPO", "PNG", "WEBP", "BMP", "TIFF", "GIF"})
FRIENDLY_FORMATS = "JPG, PNG, WebP, BMP, TIFF or GIF"

# Let Pillow itself refuse decompression bombs well above our own limit.
# Between 1x and 2x the limit Pillow only warns; our own size check refuses
# those, so the warning is noise. (Filtering it once here is thread-safe;
# ``warnings.catch_warnings()`` inside worker threads is not.)
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)

# Pillow imports its format plugins lazily, the first time it meets a file
# it doesn't recognise. Doing that import on a worker thread can crash, so
# load them all now, on whichever thread imports this module (the UI thread).
Image.init()

_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif")
WHITE = (255, 255, 255)


@dataclass(frozen=True)
class LoadedImage:
    """A decoded image ready for processing, plus facts about the original."""

    image: Image.Image  # always mode "RGB"
    source_format: str  # Pillow name, e.g. "JPEG"
    original_size: tuple[int, int]  # as stored in the file, before rotation
    rotated: bool  # EXIF orientation was applied
    reduced: bool  # decoded at reduced size because it was very large
    name: str = "image"

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def load_image(path: Path) -> LoadedImage:
    """Open an image file safely. Raises a :class:`DoclyError` subclass."""
    try:
        data = read_bytes(path, MAX_FILE_BYTES)
    except ImageTooLargeError:
        raise
    except FileTooLargeError as exc:
        raise ImageTooLargeError(str(exc)) from None
    return load_image_bytes(data, path.name)


def load_image_bytes(data: bytes, name: str = "image") -> LoadedImage:
    """Open image bytes safely (same rules as :func:`load_image`)."""
    if not data:
        raise CorruptImageError(f"{name} is empty (0 bytes).")
    if len(data) > MAX_FILE_BYTES:
        raise ImageTooLargeError(f"{name} is over the {MAX_FILE_BYTES // 1_048_576} MB limit.")
    if _looks_like_heic(data):
        raise UnsupportedFormatError(
            f"{name} is a HEIC/HEIF photo (the iPhone format), which Docly doesn't open yet. "
            "Export it as JPEG first; sharing it through WhatsApp or email usually does this."
        )

    fmt, width, height = _probe(data, name)
    if width * height > MAX_PIXELS:
        raise ImageTooLargeError(
            f"{name} is {width} × {height} px ({width * height / 1e6:.0f} MP); "
            f"the limit is {MAX_PIXELS / 1e6:.0f} MP."
        )

    image, reduced = _decode(data, fmt, width, height, name)
    image, rotated = _apply_exif_rotation(image, name)
    rgb = _to_srgb(image)
    return LoadedImage(rgb, fmt, (width, height), rotated, reduced, name)


# ----------------------------------------------------------------------
def _looks_like_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS


def _probe(data: bytes, name: str) -> tuple[str, int, int]:
    """Read only the header: real format and pixel size."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format or ""
            width, height = probe.size
    except UnidentifiedImageError:
        raise UnsupportedFormatError(f"{name} isn't an image Docly can open. Use {FRIENDLY_FORMATS}.") from None
    except Image.DecompressionBombError:
        raise ImageTooLargeError(f"{name} has too many pixels to open safely.") from None
    except Exception as exc:  # any decoder crash on a hostile file
        raise CorruptImageError(f"{name} looks damaged and can't be opened ({type(exc).__name__}).") from None
    if fmt not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(f"{name} is a {fmt or 'unknown'} file. Use {FRIENDLY_FORMATS}.")
    if width < 1 or height < 1:
        raise CorruptImageError(f"{name} has no pixels.")
    return fmt, width, height


def _decode(data: bytes, fmt: str, width: int, height: int, name: str) -> tuple[Image.Image, bool]:
    reduced = False
    try:
        image = Image.open(io.BytesIO(data))
        if fmt in ("JPEG", "MPO") and width * height > DRAFT_PIXELS:
            # draft() decodes at 1/2, 1/4 or 1/8 scale. Pick the smallest power
            # of two that brings the image under DRAFT_PIXELS.
            factor = math.sqrt(width * height / DRAFT_PIXELS)
            scale = min(8, 2 ** math.ceil(math.log2(factor)))
            image.draft("RGB", (math.ceil(width / scale), math.ceil(height / scale)))
            reduced = image.size != (width, height)
        image.seek(0)  # first frame of animated GIF / multi-page TIFF
        image.load()
    except MemoryError:
        raise ImageTooLargeError(f"{name} is too large to open with the memory available.") from None
    except Exception as exc:
        message = str(exc).lower()
        if "truncated" in message:
            raise CorruptImageError(f"{name} is incomplete (the file is cut off).") from None
        raise CorruptImageError(f"{name} looks damaged and can't be opened ({type(exc).__name__}).") from None
    return image, reduced


def _apply_exif_rotation(image: Image.Image, name: str) -> tuple[Image.Image, bool]:
    """Phones store photos sideways plus a 'rotate me' tag; apply it."""
    try:
        orientation = image.getexif().get(0x0112, 1)
    except Exception:
        return image, False
    if orientation in (None, 1):
        return image, False
    try:
        rotated = ImageOps.exif_transpose(image)
    except Exception:
        log.warning("Ignoring unreadable EXIF orientation in %s", name)
        return image, False
    return (rotated if rotated is not None else image), True


def _to_srgb(image: Image.Image) -> Image.Image:
    """Convert any mode to plain RGB; transparency becomes white."""
    icc = image.info.get("icc_profile")
    mode = image.mode

    if mode in ("I;16", "I;16B", "I;16L", "I;16N", "I", "F"):
        # 16-bit / 32-bit greyscale: scale down to 8-bit instead of clipping.
        image = image.convert("I") if mode.startswith("I;16") else image
        top = 65535 if mode.startswith("I;16") or (image.getextrema()[1] or 0) > 255 else 255
        image = image.point(lambda v: v * (255 / top)).convert("L")
        mode = "L"

    if mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif mode in ("LA", "La", "PA", "RGBa"):
        image = image.convert("RGBA")

    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, WHITE)
        background.paste(image, mask=image.getchannel("A"))
        image = background

    if icc and image.mode in ("RGB", "CMYK"):
        image = _icc_to_srgb(image, icc)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _icc_to_srgb(image: Image.Image, icc: bytes) -> Image.Image:
    """Photos in wide-gamut profiles (Display P3, Adobe RGB) look washed out
    unless converted; portals expect sRGB."""
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        target = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(image, source, target, outputMode="RGB")
        return converted if converted is not None else image
    except Exception:
        log.debug("Colour profile conversion skipped", exc_info=True)
        return image
