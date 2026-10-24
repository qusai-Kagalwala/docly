"""Tests for the Preset dataclass and its helpers."""

from __future__ import annotations

import dataclasses

import pytest

from docly.presets.models import (
    BYTES_PER_KB,
    Category,
    FileFormat,
    Preset,
    PresetKind,
    format_kb,
    region_name,
)


def make(**overrides) -> Preset:
    values = dict(id="test", name="Test", kind=PresetKind.PHOTO, formats=(FileFormat.JPG,))
    values.update(overrides)
    return Preset(**values)


def test_ratio_from_string_wins_over_pixels() -> None:
    assert make(aspect_ratio="35:45", width_px=413, height_px=531).ratio == pytest.approx(35 / 45)


def test_ratio_from_pixels() -> None:
    assert make(width_px=200, height_px=230).ratio == pytest.approx(200 / 230)


def test_ratio_none_when_unknown() -> None:
    assert make(kb_max=50).ratio is None


def test_decimal_ratio() -> None:
    assert make(aspect_ratio="3.5:4.5").ratio == pytest.approx(3.5 / 4.5)


@pytest.mark.parametrize(
    "kb_min,kb_max,expected",
    [
        (20, 50, "20–50 KB"),
        (None, 240, "up to 240 KB"),
        (50, None, "at least 50 KB"),
        (50, 10240, "50 KB – 10 MB"),
        (None, 1024, "up to 1 MB"),
        (None, None, ""),
    ],
)
def test_kb_range_text(kb_min, kb_max, expected) -> None:
    assert make(kb_min=kb_min, kb_max=kb_max).kb_range_text == expected


def test_pixel_text_variants() -> None:
    assert make(width_px=200, height_px=230).pixel_text == "200 × 230 px"
    assert (
        make(width_px=600, height_px=600, min_width_px=600, max_width_px=1200, min_height_px=600, max_height_px=1200).pixel_text
        == "600–1200 × 600–1200 px"
    )
    assert make(min_width_px=600, min_height_px=750).pixel_text == "≥600 × ≥750 px"
    assert make(aspect_ratio="3:1").pixel_text == "ratio 3:1"
    assert make(kb_max=10).pixel_text == ""


def test_bytes_use_1024() -> None:
    preset = make(kb_min=20, kb_max=50)
    assert BYTES_PER_KB == 1024
    assert preset.min_bytes == 20 * 1024
    assert preset.max_bytes == 50 * 1024
    assert make().max_bytes is None


@pytest.mark.parametrize("fmt", ["jpg", "JPG", "jpeg", ".jpeg", FileFormat.JPG])
def test_accepts_normalises_format(fmt) -> None:
    assert make().accepts(fmt)


def test_accepts_rejects_other_formats() -> None:
    assert not make().accepts("png")
    assert not make().accepts("gif")  # unknown format, no exception


def test_is_image() -> None:
    assert make().is_image
    assert not make(kind=PresetKind.DOCUMENT, formats=(FileFormat.PDF,)).is_image


def test_region_labels() -> None:
    assert make(region="IN").region_label == "India"
    assert make().region_label == "Universal"
    assert region_name("DE") == "DE"  # unknown codes fall back to the code


def test_defaults() -> None:
    preset = make()
    assert preset.category == Category.GENERAL
    assert preset.origin == "bundled"
    assert preset.verified is False


def test_preset_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        make().name = "changed"  # type: ignore[misc]


def test_format_kb() -> None:
    assert format_kb(50) == "50 KB"
    assert format_kb(1.5) == "1.5 KB"
    assert format_kb(10240) == "10 MB"
