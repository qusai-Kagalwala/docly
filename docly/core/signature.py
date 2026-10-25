"""Signature cleaner: phone photo of ink on paper → crisp ink on white.

Steps (all on a working copy; the original is never changed):

1. Use only the selected area, scaled down to at most ``WORK_MAX`` px.
2. Flatten the lighting: estimate the paper's brightness everywhere (a
   blurred "upper envelope" of the image) and divide it out. Shadows,
   gradients and tinted paper all become plain white.
3. Turn each pixel into an ink amount (0 = paper, 1 = solid ink) with a
   soft ramp, so stroke edges stay smooth. ``strength`` moves the ramp:
   low keeps faint pencil, high wipes out stubborn shadows.
4. Remove specks: blobs much smaller than a pen stroke.
5. Trim to the ink plus an even white margin.
6. Paint the ink back on white, keeping its colour or making it black.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, NoInkFoundError
from docly.core.resize import CropBox, clamp_crop

WORK_MAX = 2000  # longest side of the working copy, in pixels
BG_SCALE = 4  # estimate the paper brightness on a 1/4-size copy (fast)
BG_KERNEL_FRACTION = 0.03  # dilation size relative to the image (must exceed stroke width)
INK_ALPHA = 0.35  # ink amount above which a pixel counts as ink for trimming/specks
HALO_ALPHA = 0.08  # faint edge pixels that belong to a stroke
MARGIN_FRACTION = 0.06  # white margin around trimmed ink, relative to the ink size
MIN_MARGIN = 6
MIN_INK_PIXELS = 40
SMALL_INK_SIDE = 150  # ink smaller than this (original pixels) gets a "closer photo" note
KEEP_COLOUR_DARKEN = 0.55  # coloured ink is deepened by this factor
MIN_OUTPUT_STROKE = 1.6  # strokes thinner than this (output pixels) turn faint grey
MAX_THICKEN_RADIUS = 12

NO_INK_MESSAGE = (
    "Docly couldn't find a signature in this photo. "
    "Try a closer photo on plain white paper, or lower the strength."
)


@dataclass(frozen=True)
class CleanOptions:
    """User-adjustable settings (the Signature page's controls)."""

    strength: int = 50  # 0–100
    remove_specks: bool = True
    trim: bool = True
    black_ink: bool = False


@dataclass
class CleanResult:
    """The cleaned image and what happened."""

    image: Image.Image  # RGB, ink on white
    ink_box: tuple[int, int, int, int]  # x, y, w, h of the ink in ``image``
    scale: float  # working-copy pixels per original pixel (≤ 1)
    stroke_width: float = 2.0  # typical pen stroke in ``image`` pixels
    specks_removed: int = 0
    notes: list[str] = field(default_factory=list)


def clean_signature(
    image: Image.Image,
    options: CleanOptions = CleanOptions(),
    area: CropBox | None = None,
    cancel: CancelCheck | None = None,
) -> CleanResult:
    """Clean ``image`` (RGB). Raises :class:`NoInkFoundError` on a blank page."""
    _check(cancel)
    source = image
    if area is not None:
        box = clamp_crop(area, image.width, image.height)
        source = image.crop(box.as_pil())

    rgb = np.asarray(source.convert("RGB"), dtype=np.uint8)
    rgb, scale = _working_copy(rgb)
    _check(cancel)

    normalised = _flatten_lighting(rgb)
    _check(cancel)

    darkness = normalised.min(axis=2).astype(np.float32)  # coloured ink shows best in its weakest channel
    alpha = ink_alpha(darkness, options.strength)

    if int((alpha > 0.5).sum()) < max(MIN_INK_PIXELS, alpha.size // 5000):
        raise NoInkFoundError(NO_INK_MESSAGE)

    removed = 0
    if options.remove_specks:
        alpha, removed = _remove_specks(alpha)
    _check(cancel)
    stroke = _stroke_width(alpha)

    ink_mask = alpha > INK_ALPHA
    if not ink_mask.any():
        raise NoInkFoundError(NO_INK_MESSAGE)
    ys, xs = np.nonzero(ink_mask)
    height, width = alpha.shape
    # Include the soft edge pixels just outside the solid ink.
    x0, x1 = max(0, int(xs.min()) - 2), min(width, int(xs.max()) + 3)
    y0, y1 = max(0, int(ys.min()) - 2), min(height, int(ys.max()) + 3)

    if options.black_ink:
        ink = np.zeros_like(normalised, dtype=np.float32)
    else:
        ink = normalised.astype(np.float32) * KEEP_COLOUR_DARKEN
    a = alpha[..., None]
    painted = (255.0 * (1.0 - a) + ink * a).clip(0, 255).astype(np.uint8)

    notes: list[str] = []
    if options.trim:
        painted, ink_box = _trim(painted, (x0, y0, x1 - x0, y1 - y0))
    else:
        ink_box = (x0, y0, x1 - x0, y1 - y0)

    longest_original = max(x1 - x0, y1 - y0) / scale
    if longest_original < SMALL_INK_SIDE:
        notes.append("The signature is small in this photo; a closer photo gives a sharper result.")
    if removed:
        notes.append(f"Removed {removed} speck{'s' if removed != 1 else ''} of dust or noise.")

    return CleanResult(Image.fromarray(painted, "RGB"), ink_box, scale, stroke, removed, notes)


def thicken_for_scale(image: Image.Image, stroke_width: float, output_scale: float) -> tuple[Image.Image, bool]:
    """Thicken strokes that would shrink below ~1.6 px in the final file.

    A signature reduced to 140 × 60 px can end up with sub-pixel strokes
    that look pale grey. Spreading the ink a little *before* shrinking keeps
    it dark and readable. Returns ``(image, changed)``.
    """
    if output_scale >= 1 or stroke_width * output_scale >= MIN_OUTPUT_STROKE:
        return image, False
    needed = MIN_OUTPUT_STROKE / output_scale
    radius = min(MAX_THICKEN_RADIUS, int(np.ceil((needed - stroke_width) / 2)))
    if radius < 1:
        return image, False
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    # Erosion takes the darkest neighbour, so dark ink grows into white paper.
    thick = cv2.erode(np.asarray(image.convert("RGB")), kernel)
    return Image.fromarray(thick, "RGB"), True


def ink_alpha(darkness: np.ndarray, strength: int) -> np.ndarray:
    """Map lighting-corrected brightness (0–255) to ink amount (0–1).

    Above the *white point* is paper (0); below the *black point* is solid
    ink (1); in between is a smooth edge, curved upward to strengthen ink.
    """
    s = min(max(strength, 0), 100) / 100.0
    white_point = 245.0 - 70.0 * s  # strength 0 → 245, 50 → 210, 100 → 175
    black_point = max(0.0, white_point - 110.0)
    ramp = ((white_point - darkness) / (white_point - black_point)).clip(0.0, 1.0)
    return np.power(ramp, 0.7, dtype=np.float32)


# ----------------------------------------------------------------------
def _check(cancel: CancelCheck | None) -> None:
    if cancel is not None and cancel():
        raise CancelledError()


def _working_copy(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    longest = max(h, w)
    if longest <= WORK_MAX:
        return rgb, 1.0
    scale = WORK_MAX / longest
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(rgb, size, interpolation=cv2.INTER_AREA), scale


def _flatten_lighting(rgb: np.ndarray) -> np.ndarray:
    """Divide each colour channel by an estimate of the bare paper."""
    h, w = rgb.shape[:2]
    small_size = (max(1, w // BG_SCALE), max(1, h // BG_SCALE))
    k = max(3, int(round(max(small_size) * BG_KERNEL_FRACTION)) | 1)  # odd
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    out = np.empty_like(rgb)
    for c in range(3):
        channel = rgb[..., c]
        small = cv2.resize(channel, small_size, interpolation=cv2.INTER_AREA)
        # Morphological closing (max filter, then min filter): dark strokes
        # thinner than the kernel vanish, leaving the paper's brightness,
        # while the edges of real shadows stay where they are.
        paper = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel)
        paper = cv2.GaussianBlur(paper, (0, 0), sigmaX=max(1.0, k / 4))
        paper = cv2.resize(paper, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        ratio = channel.astype(np.float32) / np.maximum(paper, 1.0) * 255.0
        out[..., c] = ratio.clip(0, 255).astype(np.uint8)
    return out


def _remove_specks(alpha: np.ndarray) -> tuple[np.ndarray, int]:
    """Drop blobs smaller than half a pen-stroke square (dust, grain, noise)."""
    halo = (alpha > HALO_ALPHA).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(halo, connectivity=8)
    if count <= 2:
        return alpha, 0

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    stroke = _stroke_width(alpha)
    # A speck is smaller than half a stroke-square, and tiny next to the
    # main signature (so a stray blob can't make everything look "small").
    min_area = max(6.0, min(0.5 * stroke * stroke, 0.01 * float(areas.max())))
    small = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] < min_area and i != largest]
    if not small:
        return alpha, 0
    remove = np.isin(labels, small)
    cleaned = alpha.copy()
    cleaned[remove] = 0.0
    return cleaned, len(small)


def _stroke_width(alpha: np.ndarray) -> float:
    """Typical pen-stroke width in pixels.

    Uses the distance from each stroke's centre line to its edge (the
    "ridge" of the distance transform), taking the median so a few big
    blobs don't skew it.
    """
    core = (alpha > INK_ALPHA).astype(np.uint8)
    if not core.any():
        return 2.0
    distance = cv2.distanceTransform(core, cv2.DIST_L2, 3)
    ridge = (distance > 0) & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)))
    values = distance[ridge]
    return 2.0 * float(np.median(values)) if values.size else 2.0


def _trim(painted: np.ndarray, ink: tuple[int, int, int, int]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Crop to the ink plus an even white margin (extending past the edge if needed)."""
    x, y, w, h = ink
    margin = max(MIN_MARGIN, int(round(MARGIN_FRACTION * max(w, h))))
    canvas = np.full((h + 2 * margin, w + 2 * margin, 3), 255, dtype=np.uint8)
    canvas[margin : margin + h, margin : margin + w] = painted[y : y + h, x : x + w]
    return canvas, (margin, margin, w, h)
