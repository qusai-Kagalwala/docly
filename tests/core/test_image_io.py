"""Tests for safe image loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from docly.core import image_io
from docly.core.errors import CorruptImageError, ImageTooLargeError, UnsupportedFormatError
from docly.core.image_io import load_image, load_image_bytes
from tests.core import images


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("BMP", "bmp"), ("TIFF", "tif"), ("GIF", "gif")])
def test_supported_formats_load(tmp_path: Path, fmt: str, ext: str) -> None:
    path = images.save(images.photo_like(120, 80), tmp_path / f"x.{ext}", fmt)
    loaded = load_image(path)
    assert loaded.image.mode == "RGB"
    assert loaded.size == (120, 80)
    assert loaded.source_format == fmt


def test_format_detected_from_content_not_extension(tmp_path: Path) -> None:
    path = images.save(images.flat(30, 20), tmp_path / "actually_png.jpg", "PNG")
    assert load_image(path).source_format == "PNG"


def test_exif_rotation_is_applied(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90° clockwise to view"
    path = images.save(images.halves(400, 200), tmp_path / "phone.jpg", "JPEG", exif=exif)
    loaded = load_image(path)
    assert loaded.rotated
    assert loaded.original_size == (400, 200)
    assert loaded.size == (200, 400)
    top_pixel = loaded.image.getpixel((100, 20))
    assert top_pixel[0] > 150 and top_pixel[2] < 100  # red half is now on top


def test_no_rotation_flag_without_exif(tmp_path: Path) -> None:
    assert not load_image(images.save(images.flat(10, 10), tmp_path / "a.jpg")).rotated


def test_transparent_png_becomes_white(tmp_path: Path) -> None:
    clear = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    loaded = load_image(images.save(clear, tmp_path / "clear.png", "PNG"))
    assert loaded.image.getpixel((5, 5)) == (255, 255, 255)


def test_palette_gif_with_transparency(tmp_path: Path) -> None:
    image = Image.new("P", (10, 10), 0)
    image.putpalette([0, 0, 0] * 256)
    path = images.save(image, tmp_path / "t.gif", "GIF", transparency=0)
    assert load_image(path).image.getpixel((0, 0)) == (255, 255, 255)


def test_animated_gif_uses_first_frame(tmp_path: Path) -> None:
    frames = [images.flat(10, 10, (255, 0, 0)), images.flat(10, 10, (0, 0, 255))]
    path = tmp_path / "anim.gif"
    frames[0].save(path, "GIF", save_all=True, append_images=frames[1:])
    red = load_image(path).image.getpixel((5, 5))
    assert red[0] > 200 and red[2] < 50


def test_cmyk_jpeg(tmp_path: Path) -> None:
    path = images.save(Image.new("CMYK", (10, 10), (0, 0, 0, 0)), tmp_path / "cmyk.jpg")
    loaded = load_image(path)
    assert loaded.image.mode == "RGB"
    assert min(loaded.image.getpixel((5, 5))) > 240  # no ink = white


def test_16_bit_png_is_scaled_not_clipped(tmp_path: Path) -> None:
    grey = Image.new("I;16", (10, 10), 32768)  # mid-grey in 16-bit
    loaded = load_image(images.save(grey, tmp_path / "16bit.png", "PNG"))
    value = loaded.image.getpixel((5, 5))[0]
    assert 120 <= value <= 135


def test_greyscale(tmp_path: Path) -> None:
    loaded = load_image(images.save(Image.new("L", (10, 10), 100), tmp_path / "g.png", "PNG"))
    assert loaded.image.getpixel((1, 1)) == (100, 100, 100)


def test_bad_colour_profile_is_ignored(tmp_path: Path) -> None:
    path = images.save(images.flat(10, 10), tmp_path / "icc.jpg", "JPEG", icc_profile=b"not a real profile")
    assert load_image(path).size == (10, 10)


def test_large_jpeg_is_decoded_reduced(tmp_path: Path) -> None:
    path = images.save(images.flat(6000, 5000, (90, 120, 150)), tmp_path / "big.jpg", "JPEG", quality=50)
    loaded = load_image(path)
    assert loaded.reduced
    assert loaded.size == (3000, 2500)
    assert loaded.original_size == (6000, 5000)


def test_unicode_file_name(tmp_path: Path) -> None:
    path = images.save(images.flat(12, 12), tmp_path / "फ़ोटो ñ résumé.jpg")
    assert load_image(path).name == "फ़ोटो ñ résumé.jpg"


# ----- things that must be refused -----------------------------------
def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jpg"
    path.write_bytes(b"")
    with pytest.raises(CorruptImageError, match="empty"):
        load_image(path)


def test_truncated_jpeg(tmp_path: Path) -> None:
    data = images.encode(images.photo_like(300, 300))
    path = tmp_path / "cut.jpg"
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(CorruptImageError):
        load_image(path)


@pytest.mark.parametrize(
    "content,match",
    [
        (b"just some text pretending to be a photo", "isn't an image"),
        (b"%PDF-1.7\n%stuff", "isn't an image"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00", "HEIC"),
    ],
)
def test_not_an_image(tmp_path: Path, content: bytes, match: str) -> None:
    path = tmp_path / "fake.jpg"
    path.write_bytes(content)
    with pytest.raises(UnsupportedFormatError, match=match):
        load_image(path)


def test_known_but_unsupported_format(tmp_path: Path) -> None:
    path = images.save(images.flat(10, 10), tmp_path / "x.ppm", "PPM")
    with pytest.raises(UnsupportedFormatError, match="PPM"):
        load_image(path)


def test_decompression_bomb_is_refused() -> None:
    with pytest.raises(ImageTooLargeError):
        load_image_bytes(images.png_header_only(50_000, 50_000), "bomb.png")


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_just_over_pixel_limit_is_refused() -> None:
    with pytest.raises(ImageTooLargeError):
        load_image_bytes(images.png_header_only(12_000, 9_000), "big.png")  # 108 MP


def test_file_size_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(image_io, "MAX_FILE_BYTES", 500)
    path = images.save(images.noisy(100, 100), tmp_path / "n.png", "PNG")
    with pytest.raises(ImageTooLargeError):
        load_image(path)
