"""Tests for batch mode and framing the person."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from docly.core import background as bg
from docly.core.background import COLOURS, BackgroundOptions
from docly.core.batch import (
    REPORT_NAME,
    BatchKind,
    BatchSettings,
    Status,
    batch_folder,
    main,
    process_file,
    run_batch,
)
from docly.core.errors import EditsNotAllowedError, InvalidPageRangeError
from docly.core.image_io import load_image
from docly.core.person_crop import person_crop
from docly.presets import default_presets
from tests.core import images, pdfs

PRESETS = default_presets()


class TopSegmenter:
    """A "person" whose head is near the top-left third of the photo."""

    def matte(self, rgb: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        scale = 128 / max(h, w)
        mh, mw = round(h * scale), round(w * scale)
        yy, xx = np.mgrid[0:mh, 0:mw]
        head = np.hypot(xx - mw * 0.3, yy - mh * 0.25) < mh * 0.08
        body = (abs(xx - mw * 0.3) < mw * 0.15) & (yy > mh * 0.3)
        return (head | body).astype(np.float32)


class EmptySegmenter:
    def matte(self, rgb: np.ndarray) -> np.ndarray:
        return np.zeros((64, 64), np.float32)


@pytest.fixture(autouse=True)
def _fresh_cache():
    bg.clear_cache()
    yield
    bg.clear_cache()


@pytest.fixture
def photos(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "in"
    folder.mkdir()
    good = [images.save(images.photo_like(900, 1400), folder / f"student {i}.jpg", quality=90) for i in (1, 2)]
    broken = folder / "broken.jpg"
    broken.write_bytes(b"not an image")
    tiny = images.save(images.photo_like(40, 50), folder / "tiny.jpg")
    return [*good, broken, tiny]


def read_report(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


# ----------------------------------------------------------------------
def test_person_crop_frames_the_head(tmp_path: Path) -> None:
    loaded = load_image(images.save(images.photo_like(1000, 2000), tmp_path / "tall.jpg"))
    preset = PRESETS.by_id("intl-photo-35x45")
    framed = person_crop(loaded, preset, TopSegmenter())
    assert framed.found and framed.box is not None
    box = framed.box
    assert abs(box.w / box.h - 35 / 45) < 0.01
    head_top = 2000 * (0.25 - 0.08)
    assert box.y < head_top < box.y + 0.2 * box.h  # a little space above the head
    assert box.y < (2000 - box.h) / 2  # higher than a centred crop


def test_person_crop_falls_back_when_nobody_found(tmp_path: Path) -> None:
    loaded = load_image(images.save(images.photo_like(800, 600), tmp_path / "wall.jpg"))
    framed = person_crop(loaded, PRESETS.by_id("intl-photo-35x45"), EmptySegmenter())
    assert not framed.found and "No person" in framed.note
    assert person_crop(loaded, images.preset(kb_max=50), EmptySegmenter()).box is None  # no fixed shape: keep all


def test_mixed_photo_batch(photos: list[Path], tmp_path: Path) -> None:
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in photos}
    settings = BatchSettings(BatchKind.PHOTO, PRESETS.by_id("in-ibps-photo"), frame_person=True, label="IBPS")
    folder = tmp_path / "out"
    seen: list[int] = []
    report = run_batch(photos, settings, folder, on_item=lambda i, r: seen.append(i), segmenter=TopSegmenter())
    assert seen == [0, 1, 2, 3]
    statuses = [item.status for item in report.items]
    assert statuses[0] in (Status.READY, Status.CHECK) and statuses[2] == Status.FAILED
    assert "isn't an image" in report.items[2].message
    assert report.items[3].status == Status.CHECK and "Enlarged" in report.items[3].message  # too small: saved, but check
    saved = sorted(p.name for p in folder.iterdir())
    assert REPORT_NAME in saved and "student 1_in-ibps-photo.jpg" in saved
    rows = read_report(report.report_path)
    assert [r["Status"] for r in rows][2] == "Failed"
    assert rows[0]["Width (px)"] == "200" and rows[0]["Saved as"] == "student 1_in-ibps-photo.jpg"
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items())  # originals untouched
    assert "failed" in report.summary()


def test_same_names_from_different_folders_never_overwrite(tmp_path: Path) -> None:
    files = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        files.append(images.save(images.photo_like(600, 800), tmp_path / sub / "photo.jpg"))
    settings = BatchSettings(BatchKind.PHOTO, PRESETS.by_id("in-ibps-photo"), frame_person=False)
    report = run_batch(files, settings, tmp_path / "out")
    names = sorted(item.output.name for item in report.items)
    assert names == ["photo_in-ibps-photo (2).jpg", "photo_in-ibps-photo.jpg"]


def test_background_in_batch(tmp_path: Path) -> None:
    from tests.core.test_background import DiscSegmenter, portrait

    path = tmp_path / "me.jpg"
    portrait(600, 800).save(path, "JPEG", quality=95)
    settings = BatchSettings(
        BatchKind.PHOTO, PRESETS.by_id("intl-photo-35x45"), BackgroundOptions(COLOURS["white"]), frame_person=False
    )
    item = process_file(path, settings, tmp_path / "out", segmenter=DiscSegmenter())
    assert item.status in (Status.READY, Status.CHECK) and item.output is not None
    from PIL import Image

    corner = Image.open(item.output).convert("RGB").getpixel((2, 2))
    assert all(c > 235 for c in corner)


def test_settings_are_checked_before_anything_runs(tmp_path: Path, photos: list[Path]) -> None:
    strict = BatchSettings(BatchKind.PHOTO, PRESETS.by_id("us-visa-photo"), BackgroundOptions())
    with pytest.raises(EditsNotAllowedError):
        run_batch(photos, strict, tmp_path / "out")
    with pytest.raises(InvalidPageRangeError, match="preset"):
        run_batch(photos, BatchSettings(BatchKind.PHOTO), tmp_path / "out")
    with pytest.raises(InvalidPageRangeError, match="size limit"):
        run_batch(photos, BatchSettings(BatchKind.PDF), tmp_path / "out")
    with pytest.raises(InvalidPageRangeError, match="Add some files"):
        run_batch([], BatchSettings(BatchKind.PHOTO, PRESETS.by_id("in-ibps-photo")), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cancel_keeps_finished_files(photos: list[Path], tmp_path: Path) -> None:
    stop = {"now": False}

    def after_first(index: int, _result) -> None:  # noqa: ANN001
        stop["now"] = True  # the user clicks Cancel while the first file finishes

    settings = BatchSettings(BatchKind.PHOTO, PRESETS.by_id("in-ibps-photo"), frame_person=False)
    report = run_batch(photos, settings, tmp_path / "out", cancel=lambda: stop["now"], on_item=after_first)
    assert report.cancelled
    assert report.items[0].status in (Status.READY, Status.CHECK) and report.items[0].output.exists()
    assert [i.status for i in report.items[1:]] == [Status.NOT_DONE] * 3
    assert report.report_path is not None and "not done" in report.summary()


def test_signature_batch(tmp_path: Path) -> None:
    files = [images.save(images.signature_photo(), tmp_path / f"sign {i}.jpg") for i in (1, 2)]
    blank = images.save(images.blank_paper(), tmp_path / "blank.jpg")
    settings = BatchSettings(BatchKind.SIGNATURE, PRESETS.by_id("in-ibps-signature"))
    report = run_batch([*files, blank], settings, tmp_path / "out")
    assert [i.status for i in report.items][:2] == [Status.READY, Status.READY]
    assert report.items[2].status == Status.FAILED  # no ink found


def test_pdf_batch(tmp_path: Path) -> None:
    from docly.core.pdf_ops import load_source, merge

    scan = merge([load_source(images.save(images.photo_like(1240, 1754), tmp_path / "s.jpg", quality=92))]).data
    (tmp_path / "scan.pdf").write_bytes(scan)
    locked = pdfs.write_pdf(tmp_path / "locked.pdf", ["a"], password="pw")
    text = pdfs.write_pdf(tmp_path / "text.pdf", ["a"] * 3)
    settings = BatchSettings(BatchKind.PDF, target_bytes=len(scan) // 4, label="PDFs")
    report = run_batch([tmp_path / "scan.pdf", locked, text], settings, tmp_path / "out")
    assert report.items[0].status == Status.READY and report.items[0].size_bytes <= len(scan) // 4
    assert report.items[1].status == Status.FAILED and "password" in report.items[1].message
    assert report.items[2].status == Status.READY  # already small enough


def test_batch_folder_name(tmp_path: Path) -> None:
    folder = batch_folder(tmp_path / "x.jpg", "IBPS — Photograph", datetime(2026, 10, 25, 14, 5))
    assert folder == tmp_path / "Docly_Output" / "IBPS — Photograph 2026-10-25 14-05"
    assert batch_folder(tmp_path / "x.jpg", "a/b:c?", datetime(2026, 1, 1)).name.endswith("2026-01-01 00-00")


def test_cli(photos: list[Path], tmp_path: Path, capsys) -> None:
    code = main(["in-ibps-photo", *map(str, photos[:2]), "--no-frame", "--out", str(tmp_path / "cli")])
    assert code == 0
    out = capsys.readouterr().out
    assert "[1/2]" in out and "2 ready" in out
    assert main(["no-such-preset", str(photos[0])]) == 2
