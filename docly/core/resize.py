"""Crop and resize an image to a preset's size rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image

from docly.presets.models import Preset

RESAMPLE = Image.Resampling.LANCZOS
MIN_SIDE = 50  # never shrink an image below this many pixels on its short side


@dataclass(frozen=True)
class CropBox:
    """A rectangle in image pixels: left, top, width, height."""

    x: int
    y: int
    w: int
    h: int

    def as_pil(self) -> tuple[int, int, int, int]:
        """Pillow's (left, upper, right, lower) form."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


WHITE = (255, 255, 255)


@dataclass
class FitResult:
    """Image after cropping/resizing, plus what was done to it."""

    image: Image.Image
    cropped: bool = False
    padded: bool = False
    upscaled: bool = False
    notes: list[str] = field(default_factory=list)


def has_fixed_size(preset: Preset) -> bool:
    """True when the preset demands one exact pixel size."""
    return preset.width_px is not None and not _has_limits(preset)


def size_bounds(preset: Preset) -> tuple[tuple[int, int], tuple[int | None, int | None]]:
    """Smallest and largest (width, height) the preset allows when resizing.

    The minimum is never below :data:`MIN_SIDE`; ``None`` means no maximum.
    """
    min_w = max(preset.min_width_px or 1, 1)
    min_h = max(preset.min_height_px or 1, 1)
    return (min_w, min_h), (preset.max_width_px, preset.max_height_px)


def centered_crop(width: int, height: int, ratio: float) -> CropBox:
    """Largest box with ``ratio`` (w ÷ h) centred in a width × height image."""
    if width / height > ratio:  # image too wide: trim the sides
        new_w = max(1, round(height * ratio))
        return CropBox((width - new_w) // 2, 0, new_w, height)
    new_h = max(1, round(width / ratio))  # image too tall: trim top and bottom
    return CropBox(0, (height - new_h) // 2, width, new_h)


def clamp_crop(box: CropBox, width: int, height: int) -> CropBox:
    """Keep a user-supplied box inside the image (and at least 1 px)."""
    x = min(max(box.x, 0), width - 1)
    y = min(max(box.y, 0), height - 1)
    w = min(max(box.w, 1), width - x)
    h = min(max(box.h, 1), height - y)
    return CropBox(x, y, w, h)


def fit_crop_to_ratio(box: CropBox, ratio: float) -> CropBox:
    """Shrink ``box`` around its centre until it has the given ratio."""
    if box.w / box.h > ratio:
        new_w = max(1, round(box.h * ratio))
        return CropBox(box.x + (box.w - new_w) // 2, box.y, new_w, box.h)
    new_h = max(1, round(box.w / ratio))
    return CropBox(box.x, box.y + (box.h - new_h) // 2, box.w, new_h)


def pad_to_ratio(image: Image.Image, ratio: float, fill: tuple[int, int, int] = WHITE) -> Image.Image:
    """Extend ``image`` with ``fill`` (centred) until width ÷ height == ratio.

    Nothing is cut off, which matters for signatures. Images with
    transparency (RGBA) are extended with fully transparent pixels instead.
    """
    width, height = image.size
    if abs(width / height - ratio) < 1e-6:
        return image
    if width / height < ratio:  # too tall: add width
        new_w, new_h = max(width, round(height * ratio)), height
    else:  # too wide: add height
        new_w, new_h = width, max(height, round(width / ratio))
    offset = ((new_w - width) // 2, (new_h - height) // 2)
    if image.mode == "RGBA":
        corner = image.getpixel((0, 0))
        canvas = Image.new("RGBA", (new_w, new_h), (*corner[:3], 0))  # keep the colour, no halo
        canvas.paste(image, offset)
        return canvas
    canvas = Image.new("RGB", (new_w, new_h), fill)
    canvas.paste(image.convert("RGB"), offset)
    return canvas


def fit_to_preset(
    image: Image.Image,
    preset: Preset,
    crop: CropBox | None = None,
    mode: str = "crop",
) -> FitResult:
    """Match the preset's ratio, then resize to its pixel rules.

    ``mode="crop"`` (photos) trims the image to the ratio; ``crop`` is the
    user's chosen area, adjusted to the ratio, or a centred box if None.
    ``mode="pad"`` (signatures) adds white space instead, so nothing is lost.
    """
    if mode not in ("crop", "pad"):
        raise ValueError(f"Unknown fit mode: {mode}")
    result = FitResult(image)
    width, height = image.size
    ratio = preset.ratio

    box: CropBox | None = None
    if crop is not None:
        box = clamp_crop(crop, width, height)
    if mode == "crop" and ratio is not None:
        box = fit_crop_to_ratio(box, ratio) if box else centered_crop(width, height, ratio)
    if box is not None and box != CropBox(0, 0, width, height):
        result.image = image.crop(box.as_pil())
        result.cropped = True
    if mode == "pad" and ratio is not None:
        padded = pad_to_ratio(result.image, ratio)
        result.padded = padded is not result.image
        result.image = padded

    current = result.image.size
    target = _target_size(current, preset)
    if target != current:
        if target[0] > current[0] or target[1] > current[1]:
            result.upscaled = True
            result.notes.append(
                f"Enlarged from {current[0]} × {current[1]} px to {target[0]} × {target[1]} px; "
                "a larger original will look sharper."
            )
        result.image = result.image.resize(target, RESAMPLE)
    return result


def resize_by(image: Image.Image, scale: float, preset: Preset) -> Image.Image | None:
    """Scale ``image`` keeping its ratio, respecting the preset's limits.

    Returns ``None`` if the size can't change (fixed-size preset, or it is
    already at a limit in that direction).
    """
    if has_fixed_size(preset):
        return None
    width, height = image.size
    new_w, new_h = _clamp_scaled(width, height, scale, preset)
    if (new_w, new_h) == (width, height):
        return None
    return image.resize((new_w, new_h), RESAMPLE)


# ----------------------------------------------------------------------
def _has_limits(preset: Preset) -> bool:
    return any(
        v is not None for v in (preset.min_width_px, preset.max_width_px, preset.min_height_px, preset.max_height_px)
    )


def _target_size(current: tuple[int, int], preset: Preset) -> tuple[int, int]:
    if has_fixed_size(preset):
        return (preset.width_px, preset.height_px)  # type: ignore[return-value]
    if not _has_limits(preset):
        return current  # ratio-only or KB-only: keep the resolution
    # Pixel range: keep as large as allowed (the compressor can shrink later).
    return _clamp_scaled(current[0], current[1], 1.0, preset)


def _clamp_scaled(width: int, height: int, scale: float, preset: Preset) -> tuple[int, int]:
    """Scale by ``scale`` but stay inside min/max limits and above MIN_SIDE."""
    (min_w, min_h), (max_w, max_h) = size_bounds(preset)
    lo = max(min_w / width, min_h / height, MIN_SIDE / min(width, height))
    hi_candidates = [c for c in ((max_w / width) if max_w else None, (max_h / height) if max_h else None) if c]
    hi = min(hi_candidates) if hi_candidates else float("inf")
    s = min(max(scale, lo), hi) if lo <= hi else hi
    new_w = max(1, round(width * s))
    new_h = max(1, round(height * s))
    # Rounding must never push us back outside a limit.
    if max_w:
        new_w = min(new_w, max_w)
    if max_h:
        new_h = min(new_h, max_h)
    return max(new_w, min(min_w, max_w or min_w)), max(new_h, min(min_h, max_h or min_h))
