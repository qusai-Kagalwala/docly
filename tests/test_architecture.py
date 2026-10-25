"""Architecture rules from the project brief."""

from __future__ import annotations

import os
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


@pytest.mark.parametrize("module", ["cv2", "pikepdf", "PySide6.QtPdf"])
def test_engine_libraries_load_on_startup_thread(module: str) -> None:
    """Importing the UI must load these up front, never first on a worker thread."""
    code = f"import sys, docly.ui.main_window; print({module!r} in sys.modules)"
    output = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
        env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
    ).stdout.strip()
    assert output == "True"


#: Emoji and symbol "icons". Docly draws status with Lucide icons in tinted
#: capsules instead, so text never depends on the emoji font. Plain
#: typographic marks (→ · × —) are fine.
BANNED_SYMBOLS = "✅❌⚠⭐✓✗✔✕✖⏳↗↻★☆❗❓"


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return char in BANNED_SYMBOLS or 0x1F000 <= code <= 0x1FAFF or code == 0xFE0F


def _repo_files(skip: set[str]):  # noqa: ANN202
    """Every file in the repo, without walking into skipped folders (a
    virtual environment alone holds tens of thousands of files)."""
    for folder, subfolders, names in os.walk(ROOT):
        subfolders[:] = [d for d in subfolders if d not in skip and not d.startswith(".")]
        for name in names:
            yield Path(folder) / name


def test_no_emoji_in_the_repository() -> None:
    suffixes = {".py", ".json", ".md", ".txt", ".toml", ".qss", ".iss", ".cfg"}
    skip = {".venv", "venv", ".git", "__pycache__", "build", "dist", ".pytest_cache"}
    found = []
    for path in _repo_files(skip):
        if path.suffix not in suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            if any(_is_emoji(c) for c in line) and "BANNED_SYMBOLS =" not in line:
                found.append(f"{path.relative_to(ROOT)}:{number}")
    assert not found, "Use an icon (StatusBadge, Banner, StatusIcon) instead of emoji:\n" + "\n".join(found)
