"""Tests for compressing into a KB window."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from docly.core.compress import ByteWindow, byte_window, compress_to_target
from docly.core.errors import CancelledError
from docly.core.validate import validate_bytes
from docly.presets.models import FileFormat, PresetKind
from tests.core import images

IBPS = images.preset(width_px=200, height_px=230, kb_min=20, kb_max=50)


def test_byte_window_is_safe_for_both_kb_definitions() -> None:
    assert byte_window(IBPS) == ByteWindow(20 * 1024, 50 * 1000)
    assert byte_window(images.preset(kb_max=240)) == ByteWindow(None, 240_000)
    tight = byte_window(images.preset(kb_min=10, kb_max=10))
    assert tight.relaxed and tight.high == 10 * 1024


def test_hits_window_on_hard_image() -> None:
    # Noise at 300 × 300 is ~97 KB at top quality, so quality must drop.
    preset = images.preset(width_px=300, height_px=300, kb_min=25, kb_max=60)
    result = compress_to_target(images.noisy(300, 300), preset)
    window = byte_window(preset)
    assert result.hit_target
    assert window.low <= result.size_bytes <= window.high
    assert 10 < result.quality < 95
    assert (result.width, result.height) == (300, 300)


def test_uses_highest_quality_that_fits() -> None:
    preset = images.preset(kb_max=200)
    result = compress_to_target(images.photo_like(300, 300), preset)
    assert result.quality == 95  # small image fits easily at top quality


def test_fixed_size_impossible_reports_best_achieved() -> None:
    preset = images.preset(width_px=2000, height_px=2000, kb_max=10)
    result = compress_to_target(images.noisy(2000, 2000), preset)
    assert not result.hit_target
    assert result.data[:2] == b"\xff\xd8"  # still gives a usable file
    assert "exact pixel size" in result.message
    assert "Best achieved" in result.message


def test_shrinks_when_allowed() -> None:
    preset = images.preset(kb_max=30)
    result = compress_to_target(images.noisy(1500, 1500), preset)
    assert result.hit_target and result.shrunk
    assert result.width < 1500
    assert result.width == result.height  # ratio kept


def test_prefers_smaller_image_over_blocky_quality() -> None:
    preset = images.preset(kb_max=60)
    result = compress_to_target(images.photo_like(3000, 2000), preset)
    assert result.hit_target
    assert result.quality >= 70


def test_padding_reaches_minimum_without_changing_pixels() -> None:
    blank = images.flat(200, 230)
    result = compress_to_target(blank, IBPS)
    assert result.padded and result.hit_target
    assert 20 * 1024 <= result.size_bytes <= 50_000
    with Image.open(io.BytesIO(result.data)) as decoded:
        assert decoded.size == (200, 230)
        assert min(decoded.convert("RGB").getpixel((100, 100))) >= 250
    assert validate_bytes(result.data, IBPS).passed


def test_small_file_enlarged_when_size_is_free() -> None:
    preset = images.preset(kb_min=40, kb_max=200)
    result = compress_to_target(images.photo_like(120, 120), preset)
    assert result.hit_target
    assert result.enlarged or result.padded


def test_output_has_no_metadata_and_is_baseline() -> None:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif.get_ifd(0x8825)[1] = "N"  # GPS latitude reference
    data = images.encode(images.photo_like(400, 400), exif=exif)
    with Image.open(io.BytesIO(data)) as original:
        assert len(original.getexif()) > 0  # the input really has metadata
        source = original.convert("RGB")
    result = compress_to_target(source, images.preset(kb_max=100, dpi=200))
    with Image.open(io.BytesIO(result.data)) as out:
        assert len(out.getexif()) == 0
        assert not out.info.get("progressive") and not out.info.get("progression")
        assert round(out.info["dpi"][0]) == 200


def test_png_signature_reduces_colours() -> None:
    preset = images.preset(kind=PresetKind.SIGNATURE, formats=(FileFormat.PNG,), kb_max=15)
    result = compress_to_target(images.signature_like(900, 300), preset)
    assert result.format == FileFormat.PNG
    assert result.hit_target
    assert result.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_png_padding() -> None:
    preset = images.preset(kind=PresetKind.SIGNATURE, formats=(FileFormat.PNG,), kb_min=10, kb_max=40)
    result = compress_to_target(images.flat(300, 100), preset)
    assert result.padded and result.hit_target


def test_cancel_stops_work() -> None:
    with pytest.raises(CancelledError):
        compress_to_target(images.photo_like(300, 300), IBPS, cancel=lambda: True)


def test_format_must_be_allowed() -> None:
    with pytest.raises(ValueError):
        compress_to_target(images.flat(10, 10), IBPS, FileFormat.PNG)
