"""Architecture rules from the project brief."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
QT_FREE_PACKAGES = ["docly/core", "docly/presets"]


def test_qt_free_packages_do_not_mention_qt() -> None:
    offenders = []
    for package in QT_FREE_PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "PySide6" in text or "PyQt" in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_importing_core_does_not_load_qt() -> None:
    code = (
        "import sys, docly.core.pipeline, docly.presets; "
        "print(any(m.startswith('PySide6') for m in sys.modules))"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert output == "False"


@pytest.mark.parametrize("library", ["cv2", "pikepdf"])
def test_engine_libraries_only_in_core(library: str) -> None:
    """OpenCV and pikepdf are engine details; the UI and presets must not use them."""
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "docly").rglob("*.py")
        if f"import {library}" in path.read_text(encoding="utf-8") and "docly/core" not in path.as_posix()
    ]
    assert offenders == []


def test_pypdf_is_not_used() -> None:
    """Docly uses pikepdf only (one PDF library: consistent, better at repairs)."""
    for path in list((ROOT / "docly").rglob("*.py")) + [ROOT / "requirements.txt", ROOT / "pyproject.toml"]:
        assert "pypdf" not in path.read_text(encoding="utf-8"), path


def test_signature_page_loads_opencv_on_startup_thread() -> None:
    """Importing the UI must load cv2 up front (never first on a worker thread)."""
    code = "import sys, docly.ui.main_window; print('cv2' in sys.modules)"
    output = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
        env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
    ).stdout.strip()
    assert output == "True"
