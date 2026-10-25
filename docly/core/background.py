"""Replace the background behind a person with a plain colour.

How it works:

1. **Find the person.** A small neural network (MODNet, Apache-2.0,
   bundled in ``assets/models``) looks at a 512 × 512 copy of the photo and
   returns a *matte*: for every pixel, how much of it is person (1.0),
   background (0.0) or a mix (hair, soft edges). It runs fully offline in
   OpenCV.
2. **Clean the edges.** A strand of hair over a blue wall is part hair,
   part blue. Docly estimates the old background colour around the person
   and takes it back out of those mixed pixels, so you don't get a blue or
   cream halo on the new background.
3. **Fill the colour.** ``new = person × matte + colour × (1 − matte)``.

The matte depends only on the photo, so it is worked out once and reused
while the user changes the crop, colour or softness.
"""

from __future__ import annotations

import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from docly import config
from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, ModelMissingError
from docly.core.resize import CropBox
from docly.logger import get_logger

log = get_logger(__name__)

MODEL_SIZE = 512
MODEL_PATH = config.ASSETS_DIR / "models" / "modnet_512.onnx"
MAX_WORK_PIXELS = 6_000_000  # composite at most this many pixels (memory)
FIELD_SIDE = 640  # smooth colour fields are worked out at this size, then enlarged
CACHE_SIZE = 4

RGB = tuple[int, int, int]

#: Named colours offered in the UI. Light blue is common on Indian forms.
COLOURS: dict[str, RGB] = {
    "white": (255, 255, 255),
    "off_white": (245, 244, 238),
    "light_blue": (173, 216, 230),
}


@dataclass(frozen=True)
class BackgroundOptions:
    """What to put behind the person."""

    colour: RGB = COLOURS["white"]
    softness: int = 60  # 0 = crisp edges (tidies flyaway hair) … 100 = the model's own soft edges

    def __post_init__(self) -> None:
        if len(self.colour) != 3 or not all(0 <= c <= 255 for c in self.colour):
            raise ValueError(f"Not an RGB colour: {self.colour!r}")
        if not 0 <= self.softness <= 100:
            raise ValueError("softness must be 0–100")


class Segmenter(Protocol):
    """Anything that turns an RGB array into a person matte (float32, 0–1)."""

    def matte(self, rgb: np.ndarray) -> np.ndarray: ...


# ----------------------------------------------------------------------
# The bundled model
# ----------------------------------------------------------------------
class ModnetSegmenter:
    """MODNet portrait matting through OpenCV's DNN module.

    The bundled copy has a fixed 512 × 512 input (OpenCV 4.10 can't run the
    any-size original), so photos are shrunk to fit, padded to a square,
    and the padding is cut off the result again ("letterboxing").
    """

    def __init__(self, path: Path = MODEL_PATH) -> None:
        self.path = Path(path)
        self._net: cv2.dnn.Net | None = None
        self._lock = threading.Lock()  # an OpenCV network isn't safe to share between threads

    def _load(self) -> cv2.dnn.Net:
        if self._net is None:
            if not self.path.is_file():
                raise ModelMissingError(
                    "The background tool's model file is missing. Reinstalling Docly will fix this."
                )
            try:
                self._net = cv2.dnn.readNetFromONNX(str(self.path))
            except cv2.error:
                log.exception("Could not load %s", self.path)
                raise ModelMissingError(
                    "The background tool's model file is damaged. Reinstalling Docly will fix this."
                ) from None
            log.info("Loaded background model %s", self.path.name)
        return self._net

    def matte(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        scale = MODEL_SIZE / max(h, w)
        nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
        small = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        top, left = (MODEL_SIZE - nh) // 2, (MODEL_SIZE - nw) // 2
        square = cv2.copyMakeBorder(
            small, top, MODEL_SIZE - nh - top, left, MODEL_SIZE - nw - left, cv2.BORDER_REPLICATE
        )
        blob = ((square.astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
        with self._lock:
            net = self._load()
            net.setInput(blob)
            out = net.forward()
        return np.clip(out[0, 0, top : top + nh, left : left + nw], 0.0, 1.0).astype(np.float32)


_default: ModnetSegmenter | None = None
_default_lock = threading.Lock()


def default_segmenter() -> ModnetSegmenter:
    """The shared bundled model (loaded on first use)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = ModnetSegmenter()
        return _default


def model_available() -> bool:
    return MODEL_PATH.is_file()


# ----------------------------------------------------------------------
# Matte cache: one matte per photo, reused while settings change
# ----------------------------------------------------------------------
_cache: OrderedDict[int, tuple[weakref.ref, np.ndarray]] = OrderedDict()
_cache_lock = threading.Lock()


def matte_for(image: Image.Image, segmenter: Segmenter, cancel: CancelCheck | None = None) -> np.ndarray:
    """The person matte for ``image`` at model resolution (cached per image)."""
    key = id(image)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0]() is image:
            _cache.move_to_end(key)
            return hit[1]
    if cancel is not None and cancel():
        raise CancelledError()
    matte = segmenter.matte(np.asarray(image.convert("RGB")))
    with _cache_lock:
        _cache[key] = (weakref.ref(image), matte)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return matte


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ----------------------------------------------------------------------
# Compositing
# ----------------------------------------------------------------------
def replace_background(
    image: Image.Image,
    matte: np.ndarray,
    options: BackgroundOptions,
    box: CropBox | None = None,
    max_pixels: int = MAX_WORK_PIXELS,
) -> Image.Image:
    """``image`` (or its ``box`` area) with the background replaced.

    ``matte`` covers the whole image at any resolution (usually the model's).
    Very large areas are shrunk to ``max_pixels`` first; the pipeline
    resizes to the preset's pixels afterwards anyway.
    """
    width, height = image.size
    region = box or CropBox(0, 0, width, height)
    part = image.crop((region.x, region.y, region.x + region.w, region.y + region.h)).convert("RGB")
    if part.width * part.height > max_pixels:
        scale = (max_pixels / (part.width * part.height)) ** 0.5
        part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))), Image.Resampling.LANCZOS)

    # The matte's matching area, enlarged to the working size.
    mh, mw = matte.shape
    sx, sy = mw / width, mh / height
    x0, y0 = region.x * sx, region.y * sy
    x1, y1 = (region.x + region.w) * sx, (region.y + region.h) * sy
    alpha = _crop_resize(matte, (x0, y0, x1, y1), (part.width, part.height))
    alpha = _apply_softness(alpha, options.softness)

    rgb = np.asarray(part).astype(np.float32)
    foreground = estimate_foreground(rgb, alpha)
    a = alpha[..., None]
    colour = np.array(options.colour, dtype=np.float32)
    out = foreground * a + colour * (1.0 - a)
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def estimate_foreground(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """The person's own colours, with the old background taken out of soft edges.

    For a mixed pixel ``I = F·a + B·(1 − a)``. ``B`` (the old background
    near that pixel) and a fallback ``F`` (the person's colour nearby) are
    smooth, so they are worked out on a small copy and enlarged — fast even
    for large photos.
    """
    h, w = alpha.shape
    scale = min(1.0, FIELD_SIDE / max(h, w))
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    small_rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    small_a = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
    sigma = max(2.0, 0.02 * max(size))
    background = _weighted_blur(small_rgb, (1.0 - small_a) ** 2, sigma)
    person = _weighted_blur(small_rgb, small_a**2, sigma)
    background = cv2.resize(background, (w, h), interpolation=cv2.INTER_LINEAR)
    person = cv2.resize(person, (w, h), interpolation=cv2.INTER_LINEAR)

    a = alpha[..., None]
    solved = (rgb - (1.0 - a) * background) / np.maximum(a, 1e-3)
    # Where the person is barely there the solve is noisy: lean on the nearby person colour.
    trust = np.clip((a - 0.05) / 0.45, 0.0, 1.0)
    return np.clip(trust * solved + (1.0 - trust) * person, 0.0, 255.0)


def _weighted_blur(rgb: np.ndarray, weight: np.ndarray, sigma: float) -> np.ndarray:
    num = cv2.GaussianBlur(rgb * weight[..., None], (0, 0), sigma)
    den = cv2.GaussianBlur(weight, (0, 0), sigma)[..., None]
    return num / np.maximum(den, 1e-4)


def _apply_softness(alpha: np.ndarray, softness: int) -> np.ndarray:
    """Drop faint haze, then steepen the edge for lower softness values."""
    a = np.where(alpha < 0.04, 0.0, alpha)
    steep = 1.0 + (100 - softness) / 25.0  # 100 → 1 (unchanged), 0 → 5 (crisp)
    return np.clip((a - 0.5) * steep + 0.5, 0.0, 1.0).astype(np.float32)


def _crop_resize(matte: np.ndarray, box: tuple[float, float, float, float], size: tuple[int, int]) -> np.ndarray:
    """Sub-pixel crop of ``matte`` resized to ``size`` (w, h), via an affine warp."""
    x0, y0, x1, y1 = box
    out_w, out_h = size
    sx = (x1 - x0) / out_w
    sy = (y1 - y0) / out_h
    # Map output pixel centres to matte coordinates.
    transform = np.array([[sx, 0, x0 + 0.5 * sx - 0.5], [0, sy, y0 + 0.5 * sy - 0.5]], dtype=np.float64)
    return cv2.warpAffine(
        matte,
        transform,
        (out_w, out_h),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )


def preview(
    image: Image.Image,
    matte: np.ndarray,
    options: BackgroundOptions,
    max_side: int = 1600,
) -> Image.Image:
    """A screen-sized copy of the whole photo with the new background."""
    small = image.copy()
    small.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return replace_background(small, matte, options)

