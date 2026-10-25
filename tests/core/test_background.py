"""Tests for background replacement (fake segmenter, plus a smoke test of the real model)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from docly.core import background as bg
from docly.core.background import (
    COLOURS,
    BackgroundOptions,
    ModnetSegmenter,
    estimate_foreground,
    matte_for,
    replace_background,
)
from docly.core.errors import CancelledError, EditsNotAllowedError, ModelMissingError
from docly.core.image_io import LoadedImage
from docly.core.pipeline import process_loaded
from docly.core.resize import CropBox
from tests.core import images

BLUE = (20, 80, 220)
SKIN = (200, 150, 120)


class DiscSegmenter:
    """A "person" is a centred disc; works at a low resolution like the real model."""

    def __init__(self, size: int = 128, radius: float = 0.3, edge: float = 0.04) -> None:
        self.size, self.radius, self.edge = size, radius, edge
        self.calls = 0

    def matte(self, rgb: np.ndarray) -> np.ndarray:
        self.calls += 1
        h, w = rgb.shape[:2]
        scale = self.size / max(h, w)
        mh, mw = max(1, round(h * scale)), max(1, round(w * scale))
        yy, xx = np.mgrid[0:mh, 0:mw]
        d = np.hypot((xx + 0.5) / mw - 0.5, (yy + 0.5) / mh - 0.5)
        return np.clip((self.radius - d) / self.edge + 0.5, 0, 1).astype(np.float32)


def portrait(width: int = 600, height: int = 800) -> Image.Image:
    """A skin-coloured disc on a strong blue wall, with a soft blended edge."""
    seg = DiscSegmenter(size=max(width, height), radius=0.3, edge=0.04)
    a = seg.matte(np.zeros((height, width, 3), np.uint8))[..., None]
    pixels = np.array(SKIN, np.float32) * a + np.array(BLUE, np.float32) * (1 - a)
    return Image.fromarray(pixels.astype(np.uint8), "RGB")


def loaded(image: Image.Image) -> LoadedImage:
    return LoadedImage(image=image, source_format="JPEG", original_size=image.size, rotated=False, reduced=False, name="me.jpg")


@pytest.fixture(autouse=True)
def _fresh_cache():
    bg.clear_cache()
    yield
    bg.clear_cache()


# ----------------------------------------------------------------------
def test_options_validation() -> None:
    assert BackgroundOptions().colour == COLOURS["white"]
    with pytest.raises(ValueError):
        BackgroundOptions((300, 0, 0))
    with pytest.raises(ValueError):
        BackgroundOptions(softness=101)


def test_background_replaced_and_person_kept() -> None:
    image = portrait()
    matte = DiscSegmenter().matte(np.asarray(image))
    out = np.asarray(replace_background(image, matte, BackgroundOptions(COLOURS["light_blue"])))
    assert tuple(out[5, 5]) == COLOURS["light_blue"]  # corner: new colour
    assert np.abs(out[400, 300].astype(int) - SKIN).max() <= 3  # centre: the person, unchanged


def test_edges_lose_the_old_background_tint() -> None:
    image = portrait()
    matte = DiscSegmenter().matte(np.asarray(image))
    clean = np.asarray(replace_background(image, matte, BackgroundOptions(COLOURS["white"], softness=100))).astype(int)
    a = bg._crop_resize(matte, (0, 0, matte.shape[1], matte.shape[0]), (600, 800))
    edge = (a > 0.2) & (a < 0.8)
    # What a perfect cut-out would give: the person's colour mixed with white.
    ideal = np.array(SKIN, float) * a[..., None] + 255 * (1 - a[..., None])
    naive = np.asarray(image).astype(float) * a[..., None] + 255 * (1 - a[..., None])  # keeps the blue wall
    naive_error = np.abs(naive - ideal)[edge].mean()
    clean_error = np.abs(clean - ideal)[edge].mean()
    assert naive_error > 20
    assert clean_error < naive_error / 3  # most of the blue fringe is gone


def test_estimate_foreground_on_flat_regions() -> None:
    rgb = np.zeros((50, 50, 3), np.float32)
    rgb[:] = SKIN
    alpha = np.ones((50, 50), np.float32)
    assert np.allclose(estimate_foreground(rgb, alpha), SKIN, atol=0.5)


def test_softness_controls_edge_width() -> None:
    image = portrait()
    matte = DiscSegmenter(edge=0.08).matte(np.asarray(image))
    mixed = []
    for softness in (0, 100):
        out = np.asarray(replace_background(image, matte, BackgroundOptions((255, 255, 255), softness))).astype(int)
        not_white = (out != 255).any(axis=2)
        not_skin = np.abs(out - SKIN).max(axis=2) > 6
        mixed.append(int((not_white & not_skin).sum()))
    assert mixed[0] < mixed[1] / 2  # crisp edges have far fewer in-between pixels


def test_crop_box_lines_up_with_the_matte() -> None:
    image = portrait(600, 800)
    matte = DiscSegmenter().matte(np.asarray(image))
    box = CropBox(0, 100, 600, 600)  # its centre is the disc centre (300, 400)
    out = np.asarray(replace_background(image, matte, BackgroundOptions((0, 255, 0)), box))
    assert out.shape[:2] == (600, 600)
    assert np.abs(out[300, 300].astype(int) - SKIN).max() <= 3
    assert tuple(out[2, 2]) == (0, 255, 0)


def test_large_areas_are_worked_on_smaller() -> None:
    image = portrait(600, 800)
    matte = DiscSegmenter().matte(np.asarray(image))
    out = replace_background(image, matte, BackgroundOptions(), max_pixels=120_000)
    assert out.width * out.height <= 121_000 and abs(out.width / out.height - 0.75) < 0.01


def test_matte_is_cached_per_image_and_cancel() -> None:
    seg = DiscSegmenter()
    image = portrait()
    first = matte_for(image, seg)
    assert matte_for(image, seg) is first and seg.calls == 1
    other = portrait()
    matte_for(other, seg)
    assert seg.calls == 2
    with pytest.raises(CancelledError):
        matte_for(portrait(), seg, cancel=lambda: True)


# ----------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------
def test_pipeline_with_background() -> None:
    preset = images.preset(width_px=300, height_px=400, aspect_ratio="3:4", kb_max=100)
    result = process_loaded(
        loaded(portrait()), preset, background=BackgroundOptions(COLOURS["white"]), segmenter=DiscSegmenter(), want_preview=True
    )
    assert result.passed
    assert (result.compression.width, result.compression.height) == (300, 400)
    out = Image.open(io.BytesIO(result.data)).convert("RGB")
    assert all(c > 240 for c in out.getpixel((3, 3)))  # white corner
    assert result.preview is not None and result.preview.size == (600, 800)
    assert any("Background replaced" in n for n in result.notes)


def test_pipeline_without_background_is_unchanged() -> None:
    preset = images.preset(width_px=300, height_px=400, aspect_ratio="3:4", kb_max=100)
    photo = loaded(portrait())
    plain = process_loaded(photo, preset)
    again = process_loaded(photo, preset, background=None, segmenter=DiscSegmenter())
    assert plain.data == again.data and plain.preview is None


def test_no_edits_preset_refuses() -> None:
    preset = images.preset(width_px=300, height_px=400, no_edits=True)
    with pytest.raises(EditsNotAllowedError, match="edited photos"):
        process_loaded(loaded(portrait()), preset, background=BackgroundOptions(), segmenter=DiscSegmenter())
    assert process_loaded(loaded(portrait()), preset).passed  # without a background change it's fine


# ----------------------------------------------------------------------
# The real bundled model
# ----------------------------------------------------------------------
def test_bundled_model_runs() -> None:
    assert bg.model_available()
    seg = ModnetSegmenter()
    rgb = np.asarray(images.photo_like(640, 480))
    matte = seg.matte(rgb)
    assert matte.dtype == np.float32
    assert matte.shape == (384, 512)  # letterboxed: longest side 512, aspect kept
    assert 0.0 <= float(matte.min()) and float(matte.max()) <= 1.0


def test_missing_or_damaged_model(tmp_path: Path) -> None:
    rgb = np.zeros((64, 64, 3), np.uint8)
    with pytest.raises(ModelMissingError, match="missing"):
        ModnetSegmenter(tmp_path / "nope.onnx").matte(rgb)
    broken = tmp_path / "broken.onnx"
    broken.write_bytes(b"not a model")
    with pytest.raises(ModelMissingError, match="damaged"):
        ModnetSegmenter(broken).matte(rgb)


def test_model_licence_and_notice_are_bundled() -> None:
    folder = bg.MODEL_PATH.parent
    assert "Apache License" in (folder / "LICENSE-modnet.txt").read_text(encoding="utf-8")
    assert "Changes made for Docly" in (folder / "NOTICE-modnet.txt").read_text(encoding="utf-8")
