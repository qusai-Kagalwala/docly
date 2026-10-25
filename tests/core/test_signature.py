"""Tests for the signature cleaner."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from docly.core.errors import CancelledError, NoInkFoundError
from docly.core.resize import CropBox
from docly.core.signature import CleanOptions, clean_signature, ink_alpha, thicken_for_scale
from tests.core import images


@pytest.fixture(scope="module")
def photo() -> Image.Image:
    return images.signature_photo()


@pytest.fixture(scope="module")
def cleaned(photo):
    return clean_signature(photo)


def pixels(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB")).astype(int)


def test_background_becomes_white_including_shadow(cleaned) -> None:
    rgb = pixels(cleaned.image)
    paper = rgb.min(axis=2) >= 250
    assert paper.mean() > 0.9  # almost everything is pure paper
    # The corner was deep in the shadow in the original photo.
    h, w, _ = rgb.shape
    assert rgb[h - 5, 5].min() >= 250
    assert rgb[5, w - 5].min() >= 250


def test_ink_is_dark_and_keeps_blue(cleaned) -> None:
    rgb = pixels(cleaned.image)
    ink = rgb[rgb.min(axis=2) < 100]
    assert len(ink) > 500
    assert np.median(ink.sum(axis=1)) < 250  # solid, not grey
    assert np.median(ink[:, 2] - ink[:, 0]) > 30  # still blue


def test_edges_stay_smooth(cleaned) -> None:
    grey = np.asarray(cleaned.image.convert("L"))
    in_between = ((grey > 40) & (grey < 220)).sum()
    assert in_between > 100  # anti-aliased edges, not a jagged 1-bit image


def test_specks_removed_but_i_dot_kept(cleaned) -> None:
    assert cleaned.specks_removed > 0
    grey = np.asarray(cleaned.image.convert("L"))
    x, y, w, h = cleaned.ink_box
    # The dot sits above the main stroke: the top 8 % of the ink box must contain ink.
    top_band = grey[y : y + max(3, int(h * 0.08)), x : x + w]
    assert (top_band < 128).sum() > 20


def test_specks_kept_when_option_off(photo) -> None:
    result = clean_signature(photo, CleanOptions(remove_specks=False))
    assert result.specks_removed == 0


def test_trim_gives_even_margins(cleaned) -> None:
    x, y, w, h = cleaned.ink_box
    width, height = cleaned.image.size
    assert x == y  # same margin all round
    assert width - (x + w) == x and height - (y + h) == y
    assert x >= 6


def test_no_trim_keeps_full_frame(photo) -> None:
    result = clean_signature(photo, CleanOptions(trim=False))
    assert result.image.size == (2000, round(1600 * 2000 / 2400))  # working size


def test_strength_controls_faint_marks() -> None:
    darkness = np.array([[230.0, 200.0, 150.0, 60.0]], dtype=np.float32)
    low, mid, high = (ink_alpha(darkness, s)[0] for s in (0, 50, 100))
    assert low[0] > 0 and mid[0] == 0  # very faint mark kept only at low strength
    assert low[1] > mid[1] > high[1]  # each step removes more of a faint stroke
    assert mid[3] == pytest.approx(1.0) and high[3] == pytest.approx(1.0)  # real ink stays solid


def test_black_ink_is_neutral(photo) -> None:
    result = clean_signature(photo, CleanOptions(black_ink=True))
    rgb = pixels(result.image)
    ink = rgb[rgb.min(axis=2) < 100]
    spread = ink.max(axis=1) - ink.min(axis=1)
    assert np.median(spread) <= 2


def test_blank_page_is_reported() -> None:
    with pytest.raises(NoInkFoundError, match="couldn't find a signature"):
        clean_signature(images.blank_paper())


def test_white_image_is_reported() -> None:
    with pytest.raises(NoInkFoundError):
        clean_signature(images.flat(800, 400))


def test_selected_area_limits_cleaning(photo) -> None:
    # Left 15 % of the photo has paper and shadow only, no ink.
    with pytest.raises(NoInkFoundError):
        clean_signature(photo, area=CropBox(0, 0, int(photo.width * 0.15), photo.height))
    middle = clean_signature(photo, area=CropBox(400, 300, 1600, 1000))
    assert middle.image.width < 1800


def test_transparent_png_signature() -> None:
    sig = Image.new("RGBA", (900, 300), (0, 0, 0, 0))
    ImageDraw.Draw(sig).line([(50, 200), (300, 60), (600, 220), (850, 80)], fill=(10, 10, 10, 255), width=8)
    flattened = Image.new("RGB", sig.size, (255, 255, 255))
    flattened.paste(sig, mask=sig.getchannel("A"))
    result = clean_signature(flattened)
    assert result.image.size[1] < 300  # trimmed top and bottom
    assert pixels(result.image).min() < 60


def test_huge_photo_is_reduced(photo) -> None:
    big = photo.resize((4800, 3200))
    result = clean_signature(big)
    assert result.scale == pytest.approx(2000 / 4800)


def test_small_signature_gets_a_note() -> None:
    # A small signature in the middle of a big photo (taken from far away).
    page = Image.new("RGB", (1600, 1200), (236, 228, 205))
    page.paste(images.signature_photo(220, 150, stroke=3, specks=0, shadow=0), (700, 500))
    result = clean_signature(page)
    assert any("closer photo" in note for note in result.notes)


def test_cancel(photo) -> None:
    with pytest.raises(CancelledError):
        clean_signature(photo, cancel=lambda: True)


def test_thicken_only_when_needed(cleaned) -> None:
    same, changed = thicken_for_scale(cleaned.image, cleaned.stroke_width, 0.9)
    assert not changed and same is cleaned.image
    thick, changed = thicken_for_scale(cleaned.image, cleaned.stroke_width, 0.1)
    assert changed
    dark_before = (np.asarray(cleaned.image.convert("L")) < 128).sum()
    dark_after = (np.asarray(thick.convert("L")) < 128).sum()
    assert dark_after > dark_before * 1.5
    assert thick.size == cleaned.image.size
