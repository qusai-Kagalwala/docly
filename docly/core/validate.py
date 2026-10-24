"""Pass/fail check of a finished file against a preset.

The validator re-reads the actual bytes, so it checks what will really be
uploaded. It also works on files Docly didn't make ("is my photo OK?").
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from docly.core.compress import ByteWindow, byte_window
from docly.core.errors import DoclyError
from docly.core.files import read_bytes
from docly.core.image_io import MAX_FILE_BYTES
from docly.presets.models import FileFormat, Preset, PresetKind

RATIO_TOLERANCE = 0.02

_PIL_TO_FORMAT = {"JPEG": FileFormat.JPG, "MPO": FileFormat.JPG, "PNG": FileFormat.PNG}


@dataclass(frozen=True)
class Check:
    """One rule, what it expected, and what the file has."""

    name: str
    passed: bool
    expected: str
    actual: str
    blocking: bool = True  # False = advice only, doesn't fail the report

    def __str__(self) -> str:
        mark = "✅" if self.passed else ("❌" if self.blocking else "⚠️")
        return f"{mark} {self.name}: {self.actual} (expected {self.expected})"


@dataclass(frozen=True)
class ValidationReport:
    """All checks for one file."""

    preset_id: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and not c.passed]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.blocking and not c.passed]

    def summary(self) -> str:
        head = "Ready to upload ✅" if self.passed else "Won't pass this preset ❌"
        return "\n".join([head, *(f"  {c}" for c in self.checks)])


def validate_file(path: Path, preset: Preset) -> ValidationReport:
    """Validate a file on disk. Unreadable files give a failing report."""
    try:
        data = read_bytes(path, MAX_FILE_BYTES)
    except DoclyError as exc:
        return ValidationReport(preset.id, (Check("File", False, "a readable file", str(exc)),))
    return validate_bytes(data, preset)


def validate_bytes(data: bytes, preset: Preset) -> ValidationReport:
    """Validate file contents against every rule in ``preset``."""
    if preset.kind == PresetKind.DOCUMENT:
        checks = [_pdf_format_check(data, preset), *_size_checks(len(data), preset)]
        return ValidationReport(preset.id, tuple(checks))

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = _PIL_TO_FORMAT.get(image.format or "")
            width, height = image.size
            dpi = image.info.get("dpi")
    except Exception:
        return ValidationReport(
            preset.id, (Check("File", False, "a valid image", "can't be read as an image"),)
        )

    checks: list[Check] = [_format_check(fmt, preset)]
    checks.extend(_dimension_checks(width, height, preset))
    checks.extend(_size_checks(len(data), preset))
    if preset.dpi:
        actual_dpi = round(dpi[0]) if dpi else None
        checks.append(
            Check(
                "DPI",
                actual_dpi == preset.dpi,
                str(preset.dpi),
                str(actual_dpi) if actual_dpi else "not set",
                blocking=False,  # portals almost never check DPI
            )
        )
    return ValidationReport(preset.id, tuple(checks))


# ----------------------------------------------------------------------
def _format_check(fmt: FileFormat | None, preset: Preset) -> Check:
    expected = " or ".join(f.value.upper() for f in preset.formats)
    actual = fmt.value.upper() if fmt else "another format"
    return Check("Format", fmt is not None and fmt in preset.formats, expected, actual)


def _pdf_format_check(data: bytes, preset: Preset) -> Check:
    is_pdf = data[:1024].lstrip().startswith(b"%PDF-")
    return Check("Format", is_pdf, "PDF", "PDF" if is_pdf else "not a PDF")


def _dimension_checks(width: int, height: int, preset: Preset) -> list[Check]:
    actual = f"{width} × {height} px"
    limits = (preset.min_width_px, preset.max_width_px, preset.min_height_px, preset.max_height_px)
    checks: list[Check] = []

    if preset.width_px is not None and not any(v is not None for v in limits):
        ok = (width, height) == (preset.width_px, preset.height_px)
        checks.append(Check("Dimensions", ok, f"{preset.width_px} × {preset.height_px} px", actual))
        return checks  # an exact size already fixes the ratio

    if any(v is not None for v in limits):
        ok = (
            (preset.min_width_px is None or width >= preset.min_width_px)
            and (preset.max_width_px is None or width <= preset.max_width_px)
            and (preset.min_height_px is None or height >= preset.min_height_px)
            and (preset.max_height_px is None or height <= preset.max_height_px)
        )
        checks.append(Check("Dimensions", ok, preset.pixel_text, actual))

    ratio = preset.ratio
    if ratio is not None:
        actual_ratio = width / height
        # Allow 2 % or one pixel of rounding, whichever is larger.
        tolerance = max(RATIO_TOLERANCE, 1 / min(width, height))
        ok = abs(actual_ratio - ratio) / ratio <= tolerance
        expected = preset.aspect_ratio or _simplest_ratio(preset.width_px or 1, preset.height_px or 1)
        checks.append(Check("Ratio", ok, expected, _simplest_ratio(width, height)))
    return checks


def _simplest_ratio(width: int, height: int) -> str:
    """``3000, 3750`` -> ``"4:5"``; awkward sizes stay as they are."""
    divisor = math.gcd(width, height)
    w, h = width // divisor, height // divisor
    return f"{w}:{h}" if max(w, h) <= 50 else f"{width}:{height} ({width / height:.2f})"


def _size_checks(size: int, preset: Preset) -> list[Check]:
    if preset.kb_min is None and preset.kb_max is None:
        return []
    kb = size / 1024
    actual = f"{kb:.1f} KB ({size:,} bytes)"
    # Blocking check: the portal's limit read generously (1 KB = 1024 bytes)...
    loose_ok = (preset.kb_min is None or size >= preset.kb_min * 1000) and (
        preset.kb_max is None or size <= preset.kb_max * 1024
    )
    checks = [Check("File size", loose_ok, preset.kb_range_text, actual)]
    # ...plus advice when it would only pass under one way of counting KB.
    window = byte_window(preset)
    if loose_ok and not window.fits(size):
        safe = _window_text(window)
        checks.append(Check("Safety margin", False, safe, actual, blocking=False))
    return checks


def _window_text(window: ByteWindow) -> str:
    parts = []
    if window.low is not None:
        parts.append(f"≥ {window.low:,} bytes")
    if window.high is not None:
        parts.append(f"≤ {window.high:,} bytes")
    return " and ".join(parts) + " so it passes however the portal counts KB"

