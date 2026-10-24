"""Test-image factory. Images are generated in code, so no binaries live in the repo."""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from docly.presets.models import FileFormat, Preset, PresetKind


def photo_like(width: int = 1600, height: int = 1200, seed_noise: int = 40) -> Image.Image:
    """Gradient + noise + a 'face' blob: compresses like a real photo."""
    base = Image.radial_gradient("L").resize((width, height)).convert("RGB")
    noise = Image.effect_noise((width, height), seed_noise).convert("RGB")
    image = Image.blend(base, noise, 0.35)
    draw = ImageDraw.Draw(image)
    draw.ellipse((width * 0.3, height * 0.22, width * 0.7, height * 0.62), fill=(200, 160, 130))
    return image.filter(ImageFilter.GaussianBlur(1))


def noisy(width: int, height: int) -> Image.Image:
    """Pure noise: the hardest thing to compress."""
    return Image.effect_noise((width, height), 100).convert("RGB")


def flat(width: int, height: int, colour: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """A single colour: compresses to almost nothing."""
    return Image.new("RGB", (width, height), colour)


def signature_like(width: int = 900, height: int = 300) -> Image.Image:
    """Dark scribble on white paper."""
    image = Image.new("RGB", (width, height), (250, 250, 248))
    draw = ImageDraw.Draw(image)
    for i in range(0, width - 60, 30):
        draw.line((i, height * 0.6 - (i % 90), i + 60, height * 0.4 + (i % 70)), fill=(20, 20, 40), width=6)
    return image


def halves(width: int = 400, height: int = 200) -> Image.Image:
    """Left half red, right half blue (to check crops and rotation)."""
    image = Image.new("RGB", (width, height), (220, 30, 30))
    image.paste((30, 30, 220), (width // 2, 0, width, height))
    return image


def save(image: Image.Image, path: Path, fmt: str = "JPEG", **options) -> Path:
    image.save(path, fmt, **options)
    return path


def encode(image: Image.Image, fmt: str = "JPEG", **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """A tiny PNG that *claims* to be width × height (a decompression bomb)."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")


def preset(**overrides) -> Preset:
    """A photo preset with sensible defaults for tests."""
    values = dict(id="test", name="Test", kind=PresetKind.PHOTO, formats=(FileFormat.JPG,))
    values.update(overrides)
    return Preset(**values)
