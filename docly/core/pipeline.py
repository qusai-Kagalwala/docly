"""Pipelines: load → (clean) → crop/resize → compress → validate.

Also runnable as a small command-line demo, so the engine can be tried on
real photos before the UI exists::

    python -m docly.core.pipeline photo.jpg in-ibps-photo
    python -m docly.core.pipeline sign.jpg in-ibps-signature --signature

The processed copy is saved next to the original (never over it).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from docly.core.compress import CancelCheck, CompressResult, compress_to_target
from docly.core.errors import DoclyError
from docly.core.files import safe_stem, write_new_file
from docly.core.image_io import LoadedImage, load_image
from docly.core.resize import CropBox, FitResult, fit_to_preset, pad_to_ratio
from docly.core.signature import CleanOptions, clean_signature, thicken_for_scale
from docly.core.validate import ValidationReport, validate_bytes
from docly.presets.models import FileFormat, Preset, PresetKind


@dataclass
class ProcessResult:
    """Everything the UI needs to show the result card."""

    data: bytes
    format: FileFormat
    report: ValidationReport
    compression: CompressResult
    source: LoadedImage
    suggested_name: str
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.report.passed

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def suggested_filename(source_name: str, preset: Preset, fmt: FileFormat) -> str:
    """e.g. ``"passport photo_in-ibps-photo.jpg"`` (safe for Windows).

    The name is split by hand rather than with ``Path``, because on Windows
    ``Path("a:b.png")`` treats ``a:`` as a drive letter and loses it.
    """
    base = source_name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
    stem = safe_stem(stem, fallback="image")
    return f"{stem}_{preset.id}.{fmt.value}"


def process_image(
    path: Path,
    preset: Preset,
    crop: CropBox | None = None,
    fmt: FileFormat | None = None,
    cancel: CancelCheck | None = None,
) -> ProcessResult:
    """Run the whole pipeline on one file. The original is never modified.

    Raises a :class:`~docly.core.errors.DoclyError` subclass if the file
    can't be loaded or the user cancels. A missed size target is *not* an
    error: check :attr:`ProcessResult.passed` and the report.
    """
    _require_image_preset(preset)
    loaded = load_image(path)
    return process_loaded(loaded, preset, crop, fmt, cancel)


def process_loaded(
    loaded: LoadedImage,
    preset: Preset,
    crop: CropBox | None = None,
    fmt: FileFormat | None = None,
    cancel: CancelCheck | None = None,
) -> ProcessResult:
    """Same as :func:`process_image` for an image that is already loaded
    (the Photo page loads once and re-runs this when the crop changes)."""
    _require_image_preset(preset)
    notes = _load_notes(loaded)
    fitted = fit_to_preset(loaded.image, preset, crop)
    return _finish(loaded, preset, fitted, fmt, cancel, notes)


def process_signature(
    loaded: LoadedImage,
    preset: Preset,
    options: CleanOptions = CleanOptions(),
    area: CropBox | None = None,
    fmt: FileFormat | None = None,
    cancel: CancelCheck | None = None,
) -> ProcessResult:
    """Clean a signature (or other ink on paper), then fit and compress it.

    ``area`` limits cleaning to part of the photo. The preset's ratio is
    reached by adding white space, never by cutting the signature.
    Raises :class:`~docly.core.errors.NoInkFoundError` on a blank page.
    """
    _require_image_preset(preset)
    notes = _load_notes(loaded)
    cleaned = clean_signature(loaded.image, options, area, cancel)
    notes.extend(cleaned.notes)
    fitted = fit_to_preset(cleaned.image, preset, mode="pad")

    # If the preset shrinks the signature a lot, thicken the strokes first so
    # they stay dark instead of turning pale grey.
    base = pad_to_ratio(cleaned.image, preset.ratio) if preset.ratio else cleaned.image
    output_scale = fitted.image.width / base.width
    thick, changed = thicken_for_scale(cleaned.image, cleaned.stroke_width, output_scale)
    if changed:
        fitted = fit_to_preset(thick, preset, mode="pad")
        notes.append("Strokes were thickened slightly so they stay clear at this small size.")
    return _finish(loaded, preset, fitted, fmt, cancel, notes)


def _require_image_preset(preset: Preset) -> None:
    if preset.kind == PresetKind.DOCUMENT:
        raise ValueError(f"{preset.id} is a document preset; use the PDF tools.")


def _load_notes(loaded: LoadedImage) -> list[str]:
    notes: list[str] = []
    if loaded.reduced:
        notes.append("Very large photo: opened at reduced resolution to save memory.")
    if loaded.rotated:
        notes.append("Rotated upright using the camera's orientation tag.")
    return notes


def _finish(
    loaded: LoadedImage,
    preset: Preset,
    fitted: FitResult,
    fmt: FileFormat | None,
    cancel: CancelCheck | None,
    notes: list[str],
) -> ProcessResult:
    """Compress, validate and package the result (shared by all pipelines)."""
    chosen = fmt or preset.formats[0]
    notes.extend(fitted.notes)
    compressed = compress_to_target(fitted.image, preset, chosen, cancel)
    if compressed.message:
        notes.append(compressed.message)

    report = validate_bytes(compressed.data, preset)
    return ProcessResult(
        data=compressed.data,
        format=chosen,
        report=report,
        compression=compressed,
        source=loaded,
        suggested_name=suggested_filename(loaded.name, preset, chosen),
        notes=notes,
    )


# ----------------------------------------------------------------------
# Command-line demo
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """``python -m docly.core.pipeline IMAGE PRESET_ID [--out FOLDER]``.

    Exit codes: 0 passed, 1 saved but doesn't pass, 2 error.
    """
    from docly.presets import default_presets

    parser = argparse.ArgumentParser(
        prog="python -m docly.core.pipeline",
        description="Prepare one image for a Docly preset and save a copy.",
    )
    parser.add_argument("image", type=Path, help="photo or scan to process")
    parser.add_argument("preset", nargs="?", help="preset id, e.g. in-ibps-photo (omit to list them)")
    parser.add_argument("--out", type=Path, help="folder for the result (default: next to the image)")
    cleaning = parser.add_argument_group("signature cleaning")
    cleaning.add_argument("--signature", action="store_true", help="clean ink on paper before fitting")
    cleaning.add_argument("--strength", type=int, default=50, help="0–100 (default 50)")
    cleaning.add_argument("--black-ink", action="store_true", help="make the ink black")
    cleaning.add_argument("--no-trim", action="store_true", help="keep the margins")
    cleaning.add_argument("--keep-specks", action="store_true", help="don't remove small specks")
    args = parser.parse_args(argv)

    presets = default_presets()
    image_presets = [p for p in presets.presets if p.is_image]
    preset = presets.by_id(args.preset) if args.preset else None
    if preset is None or not preset.is_image:
        if args.preset:
            print(f"Unknown image preset: {args.preset}\n")
        print("Available image presets:")
        for p in image_presets:
            print(f"  {p.id:28} {p.name}")
        return 2

    try:
        if args.signature:
            options = CleanOptions(
                strength=max(0, min(100, args.strength)),
                remove_specks=not args.keep_specks,
                trim=not args.no_trim,
                black_ink=args.black_ink,
            )
            result = process_signature(load_image(args.image), preset, options)
        else:
            result = process_image(args.image, preset)
        folder = args.out or args.image.resolve().parent
        saved = write_new_file(folder, result.suggested_name, result.data)
    except DoclyError as exc:
        print(f"Error: {exc}")
        return 2

    c = result.compression
    print(f"{preset.name}")
    print(f"Saved: {saved}")
    print(f"Output: {c.width} × {c.height} px, {result.size_bytes / 1024:.1f} KB, quality {c.quality or '—'}, {c.attempts} encodes")
    for note in result.notes:
        print(f"Note: {note}")
    print(result.report.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
