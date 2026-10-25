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


def signature_photo(
    width: int = 2400,
    height: int = 1600,
    ink: tuple[int, int, int] = (25, 45, 150),
    paper: tuple[int, int, int] = (236, 228, 205),
    shadow: float = 0.45,
    specks: int = 60,
    stroke: int = 9,
    dot: bool = True,
) -> Image.Image:
    """A phone photo of a signature: tinted paper, a shadow across one side,
    sensor noise, dust specks and a looping stroke in (blue) ink.

    The ink spans the middle of the photo; ``dot`` adds an "i"-dot that the
    speck remover must keep.
    """
    import math
    import random

    rng = random.Random(7)
    image = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(image)

    # Looping cursive stroke across the middle 60 % of the width.
    x0, x1 = int(width * 0.2), int(width * 0.8)
    mid = height / 2
    points = []
    for i in range(400):
        t = i / 399
        x = x0 + (x1 - x0) * t + math.sin(t * 22) * width * 0.02
        y = mid + math.sin(t * 9) * height * 0.12 + math.cos(t * 31) * height * 0.05
        points.append((x, y))
    draw.line(points, fill=ink, width=stroke, joint="curve")
    # Underline flourish.
    draw.line([(x0, mid + height * 0.2), (x1, mid + height * 0.17)], fill=ink, width=max(2, stroke - 3))
    if dot:
        cx, cy = x0 + (x1 - x0) * 0.55, mid - height * 0.22
        r = stroke * 0.9
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink)

    image = image.filter(ImageFilter.GaussianBlur(1.2))  # soft camera focus

    # Shadow: a soft-edged shadow (like the phone's) over the lower left.
    if shadow > 0:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(
            [(0, height * 0.35), (width * 0.75, height), (0, height)], fill=int(255 * shadow)
        )
        mask = mask.filter(ImageFilter.GaussianBlur(max(width, height) * 0.02))
        gradient = Image.linear_gradient("L").resize((width, height)).point(lambda v: int(v * shadow * 0.5))
        dark = Image.new("RGB", (width, height), (0, 0, 0))
        image = Image.composite(dark, image, mask)
        image = Image.composite(dark, image, gradient)  # light falls off top to bottom

    noise = Image.effect_noise((width, height), 18).convert("RGB")
    image = Image.blend(image, noise, 0.06)

    draw = ImageDraw.Draw(image)
    for _ in range(specks):
        sx, sy = rng.randrange(width), rng.randrange(height)
        draw.point((sx, sy), fill=(60, 60, 60))
    return image


def blank_paper(width: int = 1600, height: int = 1000) -> Image.Image:
    """Tinted paper with a shadow and noise, but no ink."""
    return signature_photo(width, height, specks=0, shadow=0.35, stroke=0, dot=False).point(lambda v: v)


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
