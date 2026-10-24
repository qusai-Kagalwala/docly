"""End-to-end tests: every bundled image preset must produce a passing file."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docly import config
from docly.core.pipeline import main, process_image, suggested_filename
from docly.presets import FileFormat, load_presets
from tests.core import images

BUNDLED = load_presets(config.BUNDLED_PRESETS_PATH).presets
IMAGE_PRESETS = [p for p in BUNDLED if p.is_image]


@pytest.fixture(scope="module")
def phone_photo(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("photos")
    return images.save(images.photo_like(2400, 3200), folder / "my photo.jpg", "JPEG", quality=92)


@pytest.mark.parametrize("preset", IMAGE_PRESETS, ids=lambda p: p.id)
def test_every_bundled_preset_passes(phone_photo: Path, preset) -> None:
    result = process_image(phone_photo, preset)
    assert result.passed, f"{preset.id}\n{result.report.summary()}\n{result.notes}"
    assert result.suggested_name == f"my photo_{preset.id}.{preset.formats[0].value}"


@pytest.mark.parametrize("preset", [p for p in IMAGE_PRESETS if FileFormat.PNG in p.formats], ids=lambda p: p.id)
def test_png_output_also_passes(preset) -> None:
    folder_image = images.signature_like(1200, 400)
    import io

    from docly.core.image_io import load_image_bytes
    from docly.core.pipeline import process_loaded

    buffer = io.BytesIO()
    folder_image.save(buffer, "PNG")
    loaded = load_image_bytes(buffer.getvalue(), "sig.png")
    result = process_loaded(loaded, preset, fmt=FileFormat.PNG)
    assert result.passed, result.report.summary()


def test_original_is_never_modified(phone_photo: Path) -> None:
    before = hashlib.sha256(phone_photo.read_bytes()).hexdigest()
    process_image(phone_photo, IMAGE_PRESETS[0])
    assert hashlib.sha256(phone_photo.read_bytes()).hexdigest() == before


def test_document_preset_is_rejected(phone_photo: Path) -> None:
    document = next(p for p in BUNDLED if not p.is_image)
    with pytest.raises(ValueError):
        process_image(phone_photo, document)


@pytest.mark.parametrize(
    "source,stem",
    [
        ("a:b*c?.png", "a_b_c_"),  # "a:" must not be mistaken for a drive letter
        ("photo.final.jpeg", "photo.final"),
        (".hidden", ".hidden"),
        ("no extension", "no extension"),
        ("C:\\Users\\me\\फ़ोटो.jpg", "फ़ोटो"),
        ("", "image"),
    ],
)
def test_suggested_filename_is_windows_safe(source: str, stem: str) -> None:
    preset = IMAGE_PRESETS[0]
    assert suggested_filename(source, preset, FileFormat.JPG) == f"{stem}_{preset.id}.jpg"


# ----- command-line demo ---------------------------------------------
def test_cli_saves_a_new_copy(phone_photo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    assert main([str(phone_photo), "in-ibps-photo", "--out", str(out)]) == 0
    assert main([str(phone_photo), "in-ibps-photo", "--out", str(out)]) == 0
    saved = sorted(p.name for p in out.iterdir())
    assert saved == ["my photo_in-ibps-photo (2).jpg", "my photo_in-ibps-photo.jpg"]
    assert "Ready to upload" in capsys.readouterr().out


def test_cli_unknown_preset_lists_options(phone_photo: Path, capsys) -> None:
    assert main([str(phone_photo), "no-such-preset"]) == 2
    output = capsys.readouterr().out
    assert "Unknown image preset" in output and "in-ibps-photo" in output


def test_cli_bad_file(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"nope")
    assert main([str(bad), "in-ibps-photo"]) == 2
    assert "Error:" in capsys.readouterr().out