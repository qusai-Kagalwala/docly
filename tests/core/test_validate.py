"""Tests for the pass/fail validator."""

from __future__ import annotations

from pathlib import Path

from docly.core.validate import validate_bytes, validate_file
from docly.presets.models import FileFormat, PresetKind
from tests.core import images

IBPS = images.preset(width_px=200, height_px=230, kb_min=20, kb_max=50)


def checks_by_name(report) -> dict:
    return {c.name: c for c in report.checks}


def padded_jpeg(width: int, height: int, size: int) -> bytes:
    """A JPEG of exactly ``size`` bytes (padding via a comment segment)."""
    from docly.core.compress import _pad_jpeg

    return _pad_jpeg(images.encode(images.flat(width, height)), size)


def test_passing_file() -> None:
    report = validate_bytes(padded_jpeg(200, 230, 30_000), IBPS)
    assert report.passed
    assert report.failures == [] and report.warnings == []
    assert "Ready to upload" in report.summary()


def test_wrong_dimensions_and_format() -> None:
    data = images.encode(images.flat(300, 300), "PNG")
    report = validate_bytes(data, IBPS)
    checks = checks_by_name(report)
    assert not report.passed
    assert not checks["Format"].passed
    assert not checks["Dimensions"].passed
    assert checks["Dimensions"].actual == "300 × 300 px"
    assert "❌" in str(checks["Dimensions"])


def test_too_small_and_too_big() -> None:
    assert not checks_by_name(validate_bytes(padded_jpeg(200, 230, 5_000), IBPS))["File size"].passed
    assert not checks_by_name(validate_bytes(padded_jpeg(200, 230, 60_000), IBPS))["File size"].passed


def test_safety_margin_is_advice_only() -> None:
    # 50,500 bytes: fine if the portal counts 1 KB = 1024 bytes, not if 1000.
    report = validate_bytes(padded_jpeg(200, 230, 50_500), IBPS)
    assert report.passed
    assert [w.name for w in report.warnings] == ["Safety margin"]
    assert "⚠️" in str(report.warnings[0])


def test_pixel_range_and_ratio() -> None:
    visa = images.preset(
        min_width_px=600, max_width_px=1200, min_height_px=600, max_height_px=1200, aspect_ratio="1:1", kb_max=240
    )
    assert validate_bytes(images.encode(images.flat(900, 900)), visa).passed
    wide = checks_by_name(validate_bytes(images.encode(images.flat(1000, 800)), visa))
    assert wide["Dimensions"].passed and not wide["Ratio"].passed
    assert not checks_by_name(validate_bytes(images.encode(images.flat(500, 500)), visa))["Dimensions"].passed


def test_ratio_allows_one_pixel_rounding() -> None:
    ratio = images.preset(aspect_ratio="3:1", kb_max=50)
    assert validate_bytes(images.encode(images.flat(301, 100)), ratio).passed
    assert not validate_bytes(images.encode(images.flat(330, 100)), ratio).passed


def test_dpi_is_advice_only() -> None:
    preset = images.preset(width_px=100, height_px=100, dpi=200)
    report = validate_bytes(images.encode(images.flat(100, 100), dpi=(72, 72)), preset)
    assert report.passed
    assert checks_by_name(report)["DPI"].actual == "72"


def test_pdf_document() -> None:
    preset = images.preset(kind=PresetKind.DOCUMENT, formats=(FileFormat.PDF,), kb_max=200)
    assert validate_bytes(b"%PDF-1.7\n" + b"0" * 1000, preset).passed
    assert not validate_bytes(b"not a pdf" + b"0" * 1000, preset).passed


def test_garbage_bytes() -> None:
    report = validate_bytes(b"garbage", IBPS)
    assert not report.passed
    assert report.checks[0].name == "File"


def test_validate_missing_file(tmp_path: Path) -> None:
    report = validate_file(tmp_path / "missing.jpg", IBPS)
    assert not report.passed
    assert "not found" in report.checks[0].actual


def test_validate_file_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "ok.jpg"
    path.write_bytes(padded_jpeg(200, 230, 25_000))
    assert validate_file(path, IBPS).passed
