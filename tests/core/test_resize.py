"""Tests for crop/resize to preset rules."""

from __future__ import annotations

import pytest

from docly.core.resize import CropBox, centered_crop, clamp_crop, fit_to_preset, has_fixed_size, resize_by
from tests.core import images

IBPS = images.preset(width_px=200, height_px=230, kb_min=20, kb_max=50)
SSC_SIGNATURE = images.preset(aspect_ratio="3:1", kb_max=20)
US_VISA = images.preset(
    width_px=600, height_px=600, min_width_px=600, max_width_px=1200,
    min_height_px=600, max_height_px=1200, aspect_ratio="1:1", kb_max=240,
)  # fmt: skip
UK = images.preset(width_px=600, height_px=750, min_width_px=600, min_height_px=750, kb_min=50, kb_max=10240)
KB_ONLY = images.preset(kb_min=20, kb_max=200)


def test_exact_pixels() -> None:
    result = fit_to_preset(images.photo_like(3000, 4000), IBPS)
    assert result.image.size == (200, 230)
    assert result.cropped and not result.upscaled


def test_ratio_only_keeps_resolution() -> None:
    result = fit_to_preset(images.photo_like(1200, 900), SSC_SIGNATURE)
    assert result.image.size == (1200, 400)


def test_pixel_range_uses_largest_allowed() -> None:
    result = fit_to_preset(images.photo_like(3000, 4000), US_VISA)
    assert result.image.size == (1200, 1200)


def test_small_image_is_enlarged_with_a_note() -> None:
    result = fit_to_preset(images.photo_like(500, 500), US_VISA)
    assert result.image.size == (600, 600)
    assert result.upscaled
    assert "Enlarged" in result.notes[0]


def test_minimum_only() -> None:
    assert fit_to_preset(images.photo_like(2000, 2500), UK).image.size == (2000, 2500)
    assert fit_to_preset(images.photo_like(400, 500), UK).image.size == (600, 750)


def test_kb_only_leaves_image_alone() -> None:
    source = images.photo_like(640, 480)
    result = fit_to_preset(source, KB_ONLY)
    assert result.image.size == (640, 480)
    assert not result.cropped and not result.upscaled


def test_user_crop_is_used_and_fixed_to_ratio() -> None:
    source = images.halves(400, 200)  # red left, blue right
    result = fit_to_preset(source, images.preset(aspect_ratio="1:1", kb_max=50), crop=CropBox(250, 0, 150, 200))
    w, h = result.image.size
    assert w == h == 150
    r, _g, b = result.image.getpixel((75, 75))
    assert b > r  # we got the blue half


def test_crop_outside_image_is_clamped() -> None:
    assert clamp_crop(CropBox(-50, -50, 10_000, 10_000), 400, 300) == CropBox(0, 0, 400, 300)
    assert clamp_crop(CropBox(390, 290, 50, 50), 400, 300) == CropBox(390, 290, 10, 10)


@pytest.mark.parametrize(
    "size,ratio,expected",
    [
        ((400, 200), 1.0, CropBox(100, 0, 200, 200)),
        ((200, 400), 1.0, CropBox(0, 100, 200, 200)),
        ((300, 100), 3.0, CropBox(0, 0, 300, 100)),
    ],
)
def test_centered_crop(size, ratio, expected) -> None:
    assert centered_crop(*size, ratio) == expected


def test_resize_by_respects_rules() -> None:
    assert has_fixed_size(IBPS)
    assert resize_by(images.flat(200, 230), 0.5, IBPS) is None  # fixed size can't change
    smaller = resize_by(images.flat(1200, 1200), 0.1, US_VISA)
    assert smaller is not None and smaller.size == (600, 600)  # stops at the minimum
    assert resize_by(images.flat(600, 600), 0.5, US_VISA) is None  # already at the minimum
    tiny = resize_by(images.flat(400, 400), 0.01, KB_ONLY)
    assert tiny is not None and min(tiny.size) == 50  # never below MIN_SIDE
