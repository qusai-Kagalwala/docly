"""Small bridges to the Windows desktop (Explorer, known folders)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices

from docly.logger import get_logger

log = get_logger(__name__)

OUTPUT_FOLDER_NAME = "Docly_Output"


def reveal_in_folder(path: Path) -> bool:
    """Open the file's folder with the file selected (Explorer on Windows)."""
    try:
        if sys.platform == "win32":
            # explorer.exe always exits with code 1, so don't check it.
            subprocess.Popen(["explorer", "/select,", os.path.normpath(str(path))])  # noqa: S603, S607
            return True
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
    except OSError:
        log.warning("Could not open folder for %s", path, exc_info=True)
        return False


ERROR_INSUFFICIENT_BUFFER = 122


def package_family_name() -> str | None:
    """The MSIX package's family name when Docly runs from the Store
    package (e.g. ``QusaiKagalwala.Docly_abc123``); None when run any other way."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        length = ctypes.c_uint32(0)
        get_name = ctypes.windll.kernel32.GetCurrentPackageFamilyName
        if get_name(ctypes.byref(length), None) != ERROR_INSUFFICIENT_BUFFER:
            return None  # APPMODEL_ERROR_NO_PACKAGE: not packaged
        buffer = ctypes.create_unicode_buffer(length.value)
        if get_name(ctypes.byref(length), buffer) != 0:
            return None
        return buffer.value or None
    except Exception:  # never let this probe break the app
        log.debug("Could not read the package name", exc_info=True)
        return None


def explorer_path(path: Path) -> Path:
    """Where File Explorer can find a file Docly wrote under %LOCALAPPDATA%.

    Desktop note: inside an MSIX package, Windows quietly redirects what the
    app writes to AppData into ``%LOCALAPPDATA%\\Packages\\<family>\\LocalCache\\Local``
    (so uninstalling removes it cleanly). Docly itself still sees the normal
    path, but Explorer runs outside the package and needs the real one —
    otherwise "Open log folder" would open an empty or missing folder.
    """
    family = package_family_name()
    local = os.environ.get("LOCALAPPDATA")
    if not family or not local:
        return path
    try:
        relative = path.relative_to(local)
    except ValueError:
        return path  # not under AppData: not redirected
    real = Path(local) / "Packages" / family / "LocalCache" / "Local" / relative
    return real if real.exists() else path


def pictures_output_folder() -> Path:
    """``Pictures\\Docly_Output``, used when the original's folder is read-only."""
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    base = Path(pictures) if pictures else Path.home()
    return base / OUTPUT_FOLDER_NAME


#: Set from Settings: save everything into this folder instead of next to the original.
_custom_folder: Path | None = None


def set_custom_output_folder(folder: Path | None) -> None:
    global _custom_folder
    _custom_folder = folder


def custom_output_folder() -> Path | None:
    return _custom_folder


def output_folder_for(source: Path) -> Path:
    """Where Save puts results: the folder chosen in Settings, otherwise
    ``Docly_Output`` next to the original file."""
    if _custom_folder is not None:
        return _custom_folder
    return source.parent / OUTPUT_FOLDER_NAME
