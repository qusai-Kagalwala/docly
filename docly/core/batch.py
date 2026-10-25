"""Batch mode: one preset (or size limit) applied to many files.

Each file is handled on its own: a damaged or unsupported file is marked
"Failed" with the reason and the batch carries on. Results go into one new
folder per run, ``Docly_Output/<preset> <date time>/``, never overwriting
anything, together with ``Docly report.csv`` (opens in Excel).

Also a command-line demo::

    python -m docly.core.batch in-ibps-photo photos/*.jpg --background white
    python -m docly.core.batch in-ibps-signature signs/*.jpg --signature
    python -m docly.core.batch --pdf --kb 500 forms/*.pdf
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from docly.core.background import COLOURS, BackgroundOptions, Segmenter
from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, DoclyError, EditsNotAllowedError, InvalidPageRangeError
from docly.core.files import safe_stem, write_new_file
from docly.core.image_io import load_image
from docly.core.pdf_compress import apply_to_result
from docly.core.pdf_ops import all_pages, build_pdf, load_source
from docly.core.person_crop import person_crop
from docly.core.pipeline import process_loaded, process_signature
from docly.core.signature import CleanOptions
from docly.logger import get_logger
from docly.presets.models import FileFormat, Preset

log = get_logger(__name__)

MAX_FILES = 500
REPORT_NAME = "Docly report.csv"
OUTPUT_FOLDER = "Docly_Output"
GENERIC_FAILURE = "Something went wrong with this file. Details were saved to the log."


class BatchKind(str, Enum):
    PHOTO = "photo"
    SIGNATURE = "signature"
    PDF = "pdf"


class Status(str, Enum):
    READY = "ready"  # saved and meets every rule
    CHECK = "check"  # saved, but look at it (missed a rule, crop was a guess, …)
    FAILED = "failed"  # nothing saved; see the message
    NOT_DONE = "not done"  # the batch was cancelled before this file


STATUS_LABELS = {Status.READY: "Ready", Status.CHECK: "Check", Status.FAILED: "Failed", Status.NOT_DONE: "Not done"}


@dataclass(frozen=True)
class BatchSettings:
    """What to do with every file. Exactly one of ``preset`` (photos and
    signatures) or ``target_bytes``/``grayscale`` (PDFs) applies."""

    kind: BatchKind
    preset: Preset | None = None
    background: BackgroundOptions | None = None  # photos: new background colour
    frame_person: bool = True  # photos: crop around the person instead of the middle
    clean: CleanOptions = CleanOptions()  # signatures
    fmt: FileFormat | None = None  # signatures: JPG or PNG when the preset allows both
    target_bytes: int | None = None  # PDFs
    min_bytes: int | None = None
    grayscale: bool = False
    label: str = ""  # used to name the output folder

    def check(self) -> None:
        """Raise :class:`DoclyError` if these settings can't work at all."""
        if self.kind in (BatchKind.PHOTO, BatchKind.SIGNATURE) and self.preset is None:
            raise InvalidPageRangeError("Choose a preset first.")
        if self.kind == BatchKind.PHOTO and self.background is not None and self.preset and self.preset.no_edits:
            raise EditsNotAllowedError(
                f"{self.preset.name}: this authority doesn't accept edited photos, so the background can't be changed."
            )
        if self.kind == BatchKind.PDF and self.target_bytes is None and not self.grayscale:
            raise InvalidPageRangeError("Choose a size limit (or black & white) for the PDFs.")


@dataclass
class ItemResult:
    """What happened to one file."""

    source: Path
    status: Status
    output: Path | None = None
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None
    message: str = ""


@dataclass
class BatchReport:
    folder: Path
    items: list[ItemResult] = field(default_factory=list)
    report_path: Path | None = None
    cancelled: bool = False

    def count(self, status: Status) -> int:
        return sum(1 for item in self.items if item.status == status)

    def summary(self) -> str:
        parts = [f"{self.count(Status.READY)} ready"]
        for status, word in ((Status.CHECK, "to check"), (Status.FAILED, "failed"), (Status.NOT_DONE, "not done")):
            if self.count(status):
                parts.append(f"{self.count(status)} {word}")
        return " · ".join(parts)


# ----------------------------------------------------------------------
# Running a batch
# ----------------------------------------------------------------------
def batch_folder(first_file: Path, label: str, now: datetime | None = None) -> Path:
    """``<first file's folder>/Docly_Output/<label> <YYYY-MM-DD HH-MM>``."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H-%M")
    name = f"{safe_stem(label, fallback='Batch')} {stamp}"
    return Path(first_file).parent / OUTPUT_FOLDER / name


def run_batch(
    files: Sequence[Path],
    settings: BatchSettings,
    folder: Path,
    cancel: CancelCheck | None = None,
    on_item: Callable[[int, ItemResult], None] | None = None,
    segmenter: Segmenter | None = None,
) -> BatchReport:
    """Process ``files`` one by one into ``folder``; returns the report.

    ``on_item(index, result)`` is called after each file. Cancelling stops
    after the current file; finished files stay saved and the rest are
    marked "not done". Raises :class:`DoclyError` only for unusable settings.
    """
    settings.check()
    if not files:
        raise InvalidPageRangeError("Add some files first.")
    if len(files) > MAX_FILES:
        raise InvalidPageRangeError(f"A batch can hold up to {MAX_FILES} files. Split it into smaller batches.")
    report = BatchReport(folder)
    for index, path in enumerate(files):
        if cancel is not None and cancel():
            report.cancelled = True
            for rest in files[index:]:
                report.items.append(ItemResult(Path(rest), Status.NOT_DONE, message="Cancelled before this file."))
            break
        result = process_file(Path(path), settings, folder, cancel, segmenter)
        if result.status == Status.NOT_DONE:  # cancelled while working on it
            report.cancelled = True
        report.items.append(result)
        if on_item is not None:
            on_item(index, result)
    report.report_path = write_report(report)
    log.info("Batch finished in %s: %s", folder, report.summary())
    return report


def process_file(
    path: Path,
    settings: BatchSettings,
    folder: Path,
    cancel: CancelCheck | None = None,
    segmenter: Segmenter | None = None,
) -> ItemResult:
    """One file. Never raises for a bad file; the result says what happened."""
    try:
        if settings.kind == BatchKind.PDF:
            return _process_pdf(path, settings, folder, cancel)
        return _process_image(path, settings, folder, cancel, segmenter)
    except CancelledError:
        return ItemResult(path, Status.NOT_DONE, message="Cancelled while working on this file.")
    except DoclyError as exc:
        return ItemResult(path, Status.FAILED, message=str(exc))
    except Exception:
        log.exception("Batch: unexpected error on %s", path.name)
        return ItemResult(path, Status.FAILED, message=GENERIC_FAILURE)


def _process_image(
    path: Path, settings: BatchSettings, folder: Path, cancel: CancelCheck | None, segmenter: Segmenter | None
) -> ItemResult:
    preset = settings.preset
    assert preset is not None
    loaded = load_image(path)
    notes: list[str] = []
    if settings.kind == BatchKind.SIGNATURE:
        result = process_signature(loaded, preset, settings.clean, None, settings.fmt, cancel)
        guessed = False
    else:
        crop = None
        guessed = False
        if settings.frame_person and preset.ratio is not None:
            framed = person_crop(loaded, preset, segmenter, cancel)
            crop, guessed = framed.box, (not framed.found) or bool(framed.note)
            if framed.note:
                notes.append(framed.note)
        result = process_loaded(
            loaded, preset, crop, cancel=cancel, background=settings.background, segmenter=segmenter
        )
    saved = write_new_file(folder, result.suggested_name, result.data)
    failing = [check.name for check in result.report.checks if check.blocking and not check.passed]
    if failing:
        notes.insert(0, "Doesn't meet: " + ", ".join(failing) + ".")
    notes.extend(n for n in result.notes if "Background replaced" not in n)
    enlarged = any(note.startswith("Enlarged") for note in result.notes)  # small originals look soft
    status = Status.READY if result.passed and not guessed and not enlarged else Status.CHECK
    c = result.compression
    return ItemResult(path, status, saved, result.size_bytes, c.width, c.height, " ".join(notes))


def _process_pdf(path: Path, settings: BatchSettings, folder: Path, cancel: CancelCheck | None) -> ItemResult:
    try:
        source = load_source(path)
    except DoclyError as exc:
        if "password" in str(exc).lower():
            raise DoclyError(f"{path.name} needs a password. Open it on the PDF page instead.") from None
        raise
    try:
        if not source.is_pdf:
            raise DoclyError(f"{path.name} isn't a PDF. Use the Photo or PDF page for images.")
        built = build_pdf([source], all_pages([source]), f"{path.stem}.pdf", cancel=cancel)
        result = apply_to_result(built, settings.target_bytes, settings.min_bytes, settings.grayscale, cancel)
    finally:
        source.close()
    saved = write_new_file(folder, result.suggested_name, result.data)
    status = Status.READY if result.met_target is not False else Status.CHECK
    message = " ".join(result.warnings)
    if result.met_target is False and settings.target_bytes:
        message = f"Over the {settings.target_bytes / 1000:g} KB limit. " + message
    return ItemResult(path, status, saved, len(result.data), message=message.strip())


def write_report(report: BatchReport) -> Path | None:
    """``Docly report.csv`` in the batch folder (UTF-8 with BOM so Excel shows names correctly)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["File", "Status", "Saved as", "Size (KB)", "Width (px)", "Height (px)", "Notes"])
    for item in report.items:
        writer.writerow(
            [
                str(item.source),
                STATUS_LABELS[item.status],
                item.output.name if item.output else "",
                f"{item.size_bytes / 1024:.1f}" if item.size_bytes else "",
                item.width or "",
                item.height or "",
                item.message,
            ]
        )
    try:
        return write_new_file(report.folder, REPORT_NAME, buffer.getvalue().encode("utf-8-sig"))
    except DoclyError:
        log.warning("Could not write the batch report in %s", report.folder, exc_info=True)
        return None


# ----------------------------------------------------------------------
# Command-line demo
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    from docly.presets import default_presets

    parser = argparse.ArgumentParser(prog="python -m docly.core.batch", description="Docly batch mode (demo).")
    parser.add_argument("preset", nargs="?", help="preset id for photos/signatures (omit with --pdf)")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--signature", action="store_true", help="files are signatures (ink on paper)")
    parser.add_argument("--background", choices=sorted(COLOURS), help="photos: new background colour")
    parser.add_argument("--no-frame", action="store_true", help="photos: centred crop instead of framing the person")
    parser.add_argument("--pdf", action="store_true", help="shrink PDFs instead")
    parser.add_argument("--kb", type=float, help="PDFs: size limit in KB")
    parser.add_argument("--out", type=Path, help="output folder (default: a dated Docly_Output folder)")
    args = parser.parse_args(argv)

    files = list(args.files)
    if args.pdf:
        if args.preset:
            files.insert(0, Path(args.preset))
        settings = BatchSettings(
            BatchKind.PDF, target_bytes=math.floor(args.kb * 1000) if args.kb else None, label=f"PDFs {args.kb or ''}KB"
        )
    else:
        preset = default_presets().by_id(args.preset or "")
        if preset is None:
            print(f"Unknown preset: {args.preset}")
            return 2
        kind = BatchKind.SIGNATURE if args.signature else BatchKind.PHOTO
        background = BackgroundOptions(COLOURS[args.background]) if args.background else None
        settings = BatchSettings(kind, preset, background, frame_person=not args.no_frame, label=preset.name)
    folder = args.out or batch_folder(files[0], settings.label)

    def show(index: int, item: ItemResult) -> None:
        print(f"[{index + 1}/{len(files)}] {STATUS_LABELS[item.status]:8} {item.source.name}  {item.message}")

    try:
        report = run_batch(files, settings, folder, on_item=show)
    except DoclyError as exc:
        print(f"Error: {exc}")
        return 2
    print(report.summary())
    print(f"Saved in: {folder}")
    return 0 if report.count(Status.FAILED) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
