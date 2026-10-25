"""Tests for shrinking PDFs to a size limit."""

from __future__ import annotations

import io
import zlib
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name

from docly.core.errors import CancelledError, CorruptPdfError
from docly.core.pdf_compress import (
    FLOOR_REASON,
    LEVELS,
    NOT_IMAGES_REASON,
    apply_to_result,
    compress_to_target,
    optimise,
    size_breakdown,
)
from docly.core.pdf_ops import PdfResult, load_source, merge
from tests.core import images, pdfs


# ----------------------------------------------------------------------
# Test PDFs
# ----------------------------------------------------------------------
def scan_pdf(tmp_path: Path, pages: int = 2, size: tuple[int, int] = (1240, 1754), quality: int = 92) -> bytes:
    """Like a phone-scanned document: one big JPEG per A4 page."""
    sources = [
        load_source(images.save(images.photo_like(*size), tmp_path / f"scan{i}.jpg", quality=quality))
        for i in range(pages)
    ]
    return merge(sources).data


def pdf_with_image(image_dict_extras: dict | None = None, mode: str = "RGB", size=(600, 800), raw=None) -> bytes:
    """One page showing one Flate-compressed image XObject with optional odd settings."""
    pdf = pikepdf.Pdf.new()
    picture = images.noisy(*size).convert(mode)
    data = raw if raw is not None else zlib.compress(picture.tobytes())
    spaces = {"RGB": Name.DeviceRGB, "L": Name.DeviceGray, "CMYK": Name.DeviceCMYK}
    image = pdf.make_stream(data)
    image.Type = Name.XObject
    image.Subtype = Name.Image
    image.Width, image.Height = picture.size
    image.BitsPerComponent = 8
    image.ColorSpace = spaces.get(mode, Name.DeviceRGB)
    image.Filter = Name.FlateDecode
    for key, value in (image_dict_extras or {}).items():
        image[key] = value
    content = pdf.make_stream(b"q 400 0 0 533 100 150 cm /Im0 Do Q")
    page = Dictionary(
        Type=Name.Page,
        MediaBox=Array([0, 0, 595, 842]),
        Contents=content,
        Resources=Dictionary(XObject=Dictionary(Im0=image)),
    )
    pdf.pages.append(pikepdf.Page(page))
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def first_image(pdf: pikepdf.Pdf) -> pikepdf.Stream:
    xobjects = pdf.pages[0].obj.Resources.XObject
    return xobjects[next(iter(xobjects.keys()))]


def image_info(data: bytes) -> list[dict]:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = []
        for obj in pdf.objects:
            if isinstance(obj, pikepdf.Stream) and obj.get(Name.Subtype) == Name.Image:
                out.append(
                    {
                        "width": int(obj.Width),
                        "filter": obj.get(Name.Filter),
                        "space": obj.get(Name.ColorSpace),
                        "bytes": len(obj.read_raw_bytes()),
                    }
                )
        return out


# ----------------------------------------------------------------------
# Hitting the target
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def scan(tmp_path_factory) -> bytes:
    return scan_pdf(tmp_path_factory.mktemp("scan"))


def test_already_small_enough_is_only_tidied(scan: bytes) -> None:
    result = compress_to_target(scan, len(scan) + 10_000)
    assert result.met_target and result.level is None and result.images_changed == 0
    assert image_info(result.data)[0]["bytes"] == image_info(scan)[0]["bytes"]  # pictures untouched


@pytest.mark.parametrize("share", [0.6, 0.3, 0.12])
def test_shrinks_to_target_gently(scan: bytes, share: float) -> None:
    target = int(len(scan) * share)
    result = compress_to_target(scan, target)
    assert result.met_target
    assert result.size_bytes <= target
    assert result.images_changed == 2
    assert result.level is not None and result.level.quality >= LEVELS[-1].quality


def test_bigger_target_keeps_more_quality(scan: bytes) -> None:
    loose = compress_to_target(scan, int(len(scan) * 0.6))
    tight = compress_to_target(scan, int(len(scan) * 0.12))
    assert (loose.level.dpi, loose.level.quality) >= (tight.level.dpi, tight.level.quality)
    assert loose.size_bytes > tight.size_bytes


def test_pages_survive(scan: bytes) -> None:
    result = compress_to_target(scan, int(len(scan) * 0.2))
    with pikepdf.open(io.BytesIO(result.data)) as pdf:
        assert len(pdf.pages) == 2
        assert not pdf.is_encrypted
        image = pikepdf.PdfImage(first_image(pdf)).as_pil_image()
        assert image.mode == "RGB" and image.width > 300


def test_impossible_target_gives_best_readable_with_reason(scan: bytes) -> None:
    result = compress_to_target(scan, 5_000)
    assert not result.met_target
    assert result.level == LEVELS[-1]
    assert result.size_bytes < len(scan) / 4
    assert result.notes == [FLOOR_REASON]


def test_text_only_pdf_explains_why(tmp_path: Path) -> None:
    text = pdfs.make_pdf([f"page {i}" for i in range(30)])
    result = compress_to_target(text, 300)
    assert not result.met_target and result.images_changed == 0
    assert result.notes == [NOT_IMAGES_REASON]
    assert pdfs.labels_of(result.data) == [f"page {i}" for i in range(30)]
    assert result.size_bytes <= len(text)  # lossless step still helps


def test_minimum_size_is_padded(tmp_path: Path) -> None:
    small = pdfs.make_pdf(["a"])
    result = compress_to_target(small, 100_000, min_bytes=51_200)
    assert result.met_target and result.padded
    assert 51_200 <= result.size_bytes <= 100_000
    assert pdfs.labels_of(result.data) == ["a"]
    assert compress_to_target(small, 100_000, min_bytes=51_200).data == result.data  # deterministic


def test_grayscale_turns_pictures_grey(scan: bytes) -> None:
    result = compress_to_target(scan, None, grayscale=True)
    assert result.met_target and result.images_changed == 2
    assert all(info["space"] == Name.DeviceGray for info in image_info(result.data))
    assert result.size_bytes < len(scan)


def test_no_target_no_grayscale_is_lossless(scan: bytes) -> None:
    result = compress_to_target(scan, None)
    assert result.level is None and result.target_bytes is None


def test_flate_images_become_jpeg() -> None:
    data = pdf_with_image()
    result = compress_to_target(data, len(data) // 3)
    assert image_info(result.data)[0]["filter"] == Name.DCTDecode
    assert result.met_target


# ----------------------------------------------------------------------
# Images that must be left alone
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("extras", "mode"),
    [
        ({"/Decode": Array([1, 0, 1, 0, 1, 0])}, "RGB"),  # inverted colours
        ({}, "CMYK"),
        ({"/Interpolate": True, "/ImageMask": False, "/Mask": Array([0, 10, 0, 10, 0, 10])}, "RGB"),
    ],
)
def test_odd_images_are_left_unchanged(extras: dict, mode: str) -> None:
    data = pdf_with_image(extras, mode)
    before = image_info(data)[0]
    result = compress_to_target(data, 1_000)
    after = image_info(result.data)[0]
    assert after["filter"] == Name.FlateDecode and after["width"] == before["width"]
    assert not result.met_target


def test_soft_masked_image_is_left_unchanged() -> None:
    pdf = pikepdf.open(io.BytesIO(pdf_with_image()))
    image = first_image(pdf)
    mask = pdf.make_stream(zlib.compress(bytes(600 * 800)))
    mask.Type, mask.Subtype, mask.Width, mask.Height = Name.XObject, Name.Image, 600, 800
    mask.BitsPerComponent, mask.ColorSpace, mask.Filter = 8, Name.DeviceGray, Name.FlateDecode
    image.SMask = mask
    buffer = io.BytesIO()
    pdf.save(buffer)
    result = compress_to_target(buffer.getvalue(), 1_000)
    assert all(info["filter"] == Name.FlateDecode for info in image_info(result.data))


def test_jbig2_and_broken_images_never_crash() -> None:
    fake_jbig2 = pdf_with_image({"/Filter": Name.JBIG2Decode}, raw=b"\x00" * 20_000)
    broken = pdf_with_image(raw=b"this is not flate data" * 1000)
    for data in (fake_jbig2, broken):
        result = compress_to_target(data, 1_000)
        assert result.images_changed == 0
        pikepdf.open(io.BytesIO(result.data)).close()  # still a valid PDF


def test_tiny_images_are_skipped() -> None:
    data = pdf_with_image(size=(40, 40))
    assert compress_to_target(data, 100).images_changed == 0


# ----------------------------------------------------------------------
# Plumbing
# ----------------------------------------------------------------------
def test_breakdown(scan: bytes) -> None:
    breakdown = size_breakdown(scan)
    assert breakdown.total == len(scan)
    assert breakdown.image_share > 0.9
    assert breakdown.fonts == 0 and breakdown.other >= 0
    assert size_breakdown(pdfs.make_pdf(["a"])).images == 0


def test_optimise_never_grows() -> None:
    data = pdfs.make_pdf(["a"] * 5)
    assert len(optimise(data)) <= len(data)


def test_progress_rises_and_ends_full(scan: bytes) -> None:
    seen: list[tuple[int, int]] = []
    compress_to_target(scan, int(len(scan) * 0.3), progress=lambda d, t: seen.append((d, t)))
    done = [d for d, _ in seen]
    assert done == sorted(done)
    assert seen[-1][0] == seen[-1][1]


def test_cancel(scan: bytes) -> None:
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    with pytest.raises(CancelledError):
        compress_to_target(scan, 10_000, cancel=cancel)


def test_bad_input() -> None:
    with pytest.raises(CorruptPdfError):
        compress_to_target(b"%PDF-1.7 nonsense", 1000)
    with pytest.raises(ValueError):
        compress_to_target(pdfs.make_pdf(["a"]), 0)


def test_apply_to_result_adds_size_check(scan: bytes) -> None:
    built = PdfResult(scan, 2, "scan.pdf", ["scan.pdf was damaged and has been repaired."])
    shrunk = apply_to_result(built, int(len(scan) * 0.3))
    assert shrunk.met_target is True and shrunk.target_bytes == int(len(scan) * 0.3)
    assert shrunk.suggested_name == "scan.pdf" and shrunk.page_count == 2
    assert shrunk.warnings == built.warnings
    failed = apply_to_result(built, 2_000)
    assert failed.met_target is False and FLOOR_REASON in failed.warnings
    assert built.met_target is None  # original untouched


def test_photos_page_size_is_kept(tmp_path: Path) -> None:
    data = scan_pdf(tmp_path, pages=1, size=(1754, 1240))
    result = compress_to_target(data, len(data) // 5)
    with pikepdf.open(io.BytesIO(result.data)) as pdf:
        box = [float(v) for v in pdf.pages[0].mediabox]
        assert box[2] > box[3]  # landscape page stays landscape
