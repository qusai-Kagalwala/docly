"""Phase 13: icons, version info, the PyInstaller recipe and the self-check."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from docly import __version__, config

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_icons  # noqa: E402

import build  # noqa: E402


# ----- icons -----------------------------------------------------------------------
def test_icon_files_are_up_to_date(qapp) -> None:
    assert make_icons.main(["--check"]) == 0, "run: python tools/make_icons.py"


def test_ico_has_every_size() -> None:
    with Image.open(config.APP_ICON_PATH) as ico:
        assert sorted(ico.info["sizes"]) == [(s, s) for s in make_icons.ICO_SIZES]


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("Square44x44Logo.scale-100.png", (44, 44)),
        ("Square44x44Logo.scale-400.png", (176, 176)),
        ("Square44x44Logo.targetsize-16_altform-unplated.png", (16, 16)),
        ("Square150x150Logo.scale-200.png", (300, 300)),
        ("Wide310x150Logo.scale-125.png", (388, 188)),
        ("StoreLogo.scale-100.png", (50, 50)),
    ],
)
def test_store_logo_sizes(name: str, size: tuple[int, int]) -> None:
    with Image.open(make_icons.MSIX_ASSETS / name) as image:
        assert image.size == size and image.mode == "RGBA"


def test_window_uses_the_app_icon(qapp) -> None:
    from docly.ui.main_window import app_icon

    assert not app_icon().isNull()
    assert config.APP_ICON_PNG.exists()


# ----- version info -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("version", "numbers"),
    [("1.0.0", (1, 0, 0, 0)), ("0.1.0", (0, 1, 0, 0)), ("2.3", (2, 3, 0, 0)), ("1.2.3.4", (1, 2, 3, 4)), ("1.0.0-beta", (1, 0, 0, 0))],
)
def test_version_tuple(version: str, numbers: tuple[int, ...]) -> None:
    assert build.version_tuple(version) == numbers


def test_version_info_resource() -> None:
    text = build.version_info_text("1.2.0")
    assert "filevers=(1, 2, 0, 0)" in text and "StringStruct('ProductVersion', '1.2.0')" in text
    assert "StringStruct('OriginalFilename', 'Docly.exe')" in text
    compile(text.split("\n", 1)[1], "version_info", "eval")  # PyInstaller evaluates it as Python


# ----- the PyInstaller recipe ------------------------------------------------------------
def _spec_text() -> str:
    return build.SPEC.read_text(encoding="utf-8")


def test_spec_bundles_every_asset_folder() -> None:
    """A new folder under assets/ must be added to the spec, or the packaged
    app silently runs without it."""
    spec = _spec_text()
    for folder in (ROOT / "assets").iterdir():
        if folder.is_dir():
            assert f'"assets" / "{folder.name}"' in spec, f"packaging/docly.spec doesn't bundle assets/{folder.name}"
    assert '"presets" / "presets.json"' in spec


def test_spec_never_ships_unused_qt_or_upx() -> None:
    spec = _spec_text()
    for module in ("PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtMultimedia", "tkinter", "pytest"):
        assert f'"{module}"' in spec
    assert re.search(r"upx=False", spec) and "console=False" in spec
    assert '"opencv_videoio_ffmpeg"' in spec  # video support Docly never uses


def test_frozen_paths_follow_pyinstaller(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert config._base_dir() == tmp_path
    assert not config.IS_FROZEN  # tests run from source


def test_version_is_single_sourced() -> None:
    assert config.APP_VERSION == __version__


# ----- self-check -------------------------------------------------------------------------
@pytest.mark.slow
def test_self_check_passes_from_source(qapp, tmp_path: Path) -> None:
    from docly.ui.selfcheck import CHECKS, run_self_check

    report = tmp_path / "self-check.txt"
    assert run_self_check(report) == 0
    text = report.read_text(encoding="utf-8")
    assert sum(line.startswith("PASS  ") for line in text.splitlines()) == len(CHECKS)
    assert "ALL PASSED" in text


def test_self_check_reports_failures(qapp, tmp_path: Path, monkeypatch) -> None:
    from docly.ui import selfcheck

    def broken(_folder: Path) -> str:
        raise RuntimeError("model file missing")

    monkeypatch.setattr(selfcheck, "CHECKS", (("presets", selfcheck.check_presets), ("photo", broken)))
    report = tmp_path / "r.txt"
    assert selfcheck.run_self_check(report) == 1
    text = report.read_text(encoding="utf-8")
    assert "PASS  presets" in text and "FAIL  photo" in text and "model file missing" in text and "1 FAILED" in text


@pytest.mark.slow
def test_main_self_check_flag(tmp_path: Path) -> None:
    """``python main.py --self-check`` — exactly what tools/build.py runs on Docly.exe."""
    env = {**os.environ, "DOCLY_DATA_DIR": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--self-check"], env=env, timeout=180, check=False)
    assert result.returncode == 0
    assert "ALL PASSED" in (tmp_path / "self-check.txt").read_text(encoding="utf-8")


def test_icon_check_ignores_antialiasing_but_not_changes(qapp) -> None:
    original = make_icons.png_bytes(make_icons.icon(48))
    image = Image.open(__import__("io").BytesIO(original)).convert("RGBA")
    nudged = image.copy()
    nudged.putpixel((10, 10), tuple(max(0, c - 30) for c in nudged.getpixel((10, 10))))  # one edge pixel
    assert make_icons.same_picture(original, make_icons.png_bytes(nudged))
    recoloured = Image.merge("RGBA", (*reversed(image.split()[:3]), image.split()[3]))  # blue tile → orange
    assert not make_icons.same_picture(original, make_icons.png_bytes(recoloured))
    assert not make_icons.same_picture(original, make_icons.png_bytes(make_icons.icon(32)))  # wrong size
    assert make_icons.same_picture(make_icons.ico_bytes(), config.APP_ICON_PATH.read_bytes())


# ----- licence notices ----------------------------------------------------------------
def test_notices_cover_everything_bundled() -> None:
    import make_notices

    text = config.NOTICES_PATH.read_text(encoding="utf-8")
    for name in ("Python", "Qt and Qt for Python", "opencv-python-headless", "numpy", "pikepdf", "lxml",
                 "Lucide icons", "MODNet", "GNU Lesser General Public License v3.0"):  # fmt: skip
        assert name.lower() in text.lower(), f"{name} missing: run python tools/make_notices.py"
    assert "pillow" in text.lower() and "download.qt.io" in text
    bundled = {d.metadata["Name"].lower() for d in make_notices.dependencies()}
    assert {"numpy", "pikepdf", "pillow"} <= bundled


def test_about_shows_licences(qtbot, theme_manager) -> None:
    from docly.ui.about_dialog import AboutDialog, LicencesDialog

    about = AboutDialog(theme_manager)
    qtbot.addWidget(about)
    dialog = about.show_licences()
    assert isinstance(dialog, LicencesDialog) and dialog.isVisible()
    assert "Lucide" in dialog.text.toPlainText() and dialog.text.isReadOnly()
    dialog.accept()


def test_missing_notices_file_is_explained(monkeypatch, tmp_path) -> None:
    from docly.ui import about_dialog

    monkeypatch.setattr(config, "NOTICES_PATH", tmp_path / "nope.txt")
    assert config.REPO_URL in about_dialog.read_notices()
