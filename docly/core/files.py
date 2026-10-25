"""Small, careful file helpers shared by the engine and batch mode.

Rules: never overwrite anything, handle Unicode and long Windows paths,
and turn OS errors into readable :class:`FileAccessError` messages.
"""

from __future__ import annotations

import errno
import os
import re
import sys
from pathlib import Path

from docly.core.errors import FileAccessError, FileTooLargeError

#: Characters Windows does not allow in file names.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip
MAX_STEM = 80
_WINDOWS_PATH_LIMIT = 248  # stay clear of the classic 260-character limit


def os_path(path: Path) -> str:
    """Path string that also works beyond 260 characters on Windows.

    Windows refuses long paths unless they start with ``\\\\?\\``. On other
    systems the path is returned unchanged.
    """
    text = os.fspath(path)
    if sys.platform != "win32" or len(text) < _WINDOWS_PATH_LIMIT or text.startswith("\\\\?\\"):
        return text
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):  # network share: \\server\share\...
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


#: Windows "cloud file" errors (OneDrive / iCloud files that are online-only).
_CLOUD_ERRORS = range(358, 405)
_DISK_FULL_WINERRORS = {39, 112}  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
EMPTY_HINT = "If it's in OneDrive or still downloading, wait for it to finish and try again."


def os_problem(exc: OSError) -> str:
    """A plain-words reason for an OS error (disk full, OneDrive, too long…)."""
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.ENOSPC or winerror in _DISK_FULL_WINERRORS:
        return "the disk is full. Free some space or choose another folder"
    if winerror in _CLOUD_ERRORS:
        return (
            "it's stored online only (OneDrive) and couldn't be downloaded. "
            "Check your internet, or right-click it in File Explorer and choose \"Always keep on this device\""
        )
    if exc.errno == errno.ENAMETOOLONG or winerror == 206:
        return "the path is too long. Move it to a shorter folder path"
    if exc.errno == errno.EROFS:
        return "the drive is read-only"
    return str(exc.strerror or exc)


#: First bytes → what the file really is, for "this .jpg is actually a PDF".
_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"%PDF-", 0, "a PDF"),
    (b"\xff\xd8\xff", 0, "a JPEG photo"),
    (b"\x89PNG\r\n\x1a\n", 0, "a PNG image"),
    (b"GIF8", 0, "a GIF image"),
    (b"BM", 0, "a BMP image"),
    (b"II*\x00", 0, "a TIFF image"),
    (b"MM\x00*", 0, "a TIFF image"),
    (b"WEBP", 8, "a WebP image"),
    (b"ftyp", 4, "a HEIC photo or video"),
    (b"PK\x03\x04", 0, "a ZIP file (or a Word/Excel document)"),
    (b"Rar!", 0, "a RAR archive"),
    (b"7z\xbc\xaf", 0, "a 7-Zip archive"),
    (b"\xd0\xcf\x11\xe0", 0, "an old Office document"),
)


def describe_content(data: bytes) -> str | None:
    """What ``data`` looks like from its first bytes, e.g. ``"a PDF"``; None if unknown."""
    for magic, offset, label in _SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            if label == "a ZIP file (or a Word/Excel document)":
                head = data[:2000]
                if b"word/" in head:
                    return "a Word document"
                if b"xl/" in head:
                    return "an Excel file"
            return label
    head = data[:512].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html")):
        return "a web page (HTML) — it may be a download that failed"
    return None


def read_bytes(path: Path, max_bytes: int) -> bytes:
    """Read a whole file, refusing anything bigger than ``max_bytes``."""
    try:
        size = os.stat(os_path(path)).st_size
    except FileNotFoundError:
        raise FileAccessError(f"File not found: {path.name}") from None
    except PermissionError:
        raise FileAccessError(f"Docly doesn't have permission to open {path.name}.") from None
    except OSError as exc:
        raise FileAccessError(f"Couldn't open {path.name}: {os_problem(exc)}.") from None
    if os.path.isdir(os_path(path)):
        raise FileAccessError(f"{path.name} is a folder, not a file.")
    if size > max_bytes:
        raise FileTooLargeError(
            f"{path.name} is {size / 1_048_576:.1f} MB; the limit is {max_bytes / 1_048_576:.0f} MB."
        )
    try:
        with open(os_path(path), "rb") as handle:
            data = handle.read(max_bytes + 1)
    except PermissionError:
        raise FileAccessError(
            f"Docly doesn't have permission to open {path.name}. It may be open in another program."
        ) from None
    except OSError as exc:
        raise FileAccessError(f"Couldn't read {path.name}: {os_problem(exc)}.") from None
    if len(data) > max_bytes:  # the file grew after we checked its size
        raise FileTooLargeError(f"{path.name} is larger than {max_bytes / 1_048_576:.0f} MB.")
    return data


def safe_stem(name: str, fallback: str = "file") -> str:
    """Make ``name`` usable as a Windows file name (keeps Unicode)."""
    cleaned = _FORBIDDEN.sub("_", name).strip().rstrip(". ")
    cleaned = re.sub(r"\s+", " ", cleaned)[:MAX_STEM].rstrip(". ")
    if not cleaned or cleaned.upper() in _RESERVED:
        cleaned = fallback if not cleaned else f"{cleaned}_"
    return cleaned


def unique_path(folder: Path, file_name: str) -> Path:
    """``folder/file_name``, or ``name (2).ext``, ``name (3).ext`` … if taken."""
    candidate = folder / file_name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while os.path.exists(os_path(candidate)):
        candidate = folder / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def write_file(path: Path, data: bytes) -> Path:
    """Write ``data`` to exactly ``path`` (used after a "Save as" dialog,
    where the user has already confirmed replacing an existing file).

    Writes to a temporary file first and then swaps it in, so a crash or a
    full disk never leaves a half-written file behind.
    """
    temp = path.with_name(f".{path.name}.docly-tmp")
    try:
        os.makedirs(os_path(path.parent), exist_ok=True)
        with open(os_path(temp), "wb") as handle:
            handle.write(data)
        os.replace(os_path(temp), os_path(path))
    except PermissionError:
        _remove_quietly(temp)
        raise FileAccessError(
            f"Docly can't save {path.name} there. The file may be open in another program, "
            "or the folder is read-only."
        ) from None
    except OSError as exc:
        _remove_quietly(temp)
        raise FileAccessError(f"Couldn't save {path.name}: {os_problem(exc)}.") from None
    return path


def _remove_quietly(path: Path) -> None:
    try:
        os.remove(os_path(path))
    except OSError:
        pass


def write_new_file(folder: Path, file_name: str, data: bytes) -> Path:
    """Write ``data`` to a new file in ``folder``; never overwrites.

    Uses exclusive-create mode, so even if another program creates the same
    name at the same moment, the existing file is never replaced.
    """
    try:
        os.makedirs(os_path(folder), exist_ok=True)
    except OSError as exc:
        raise FileAccessError(f"Couldn't create the folder {folder}: {os_problem(exc)}.") from None
    for _attempt in range(100):
        target = unique_path(folder, file_name)
        try:
            handle = open(os_path(target), "xb")  # noqa: SIM115 (closed below)
        except FileExistsError:
            continue  # someone took the name in between; try the next one
        except PermissionError:
            raise FileAccessError(
                f"Docly can't save into {folder}. Choose a folder you can write to."
            ) from None
        except OSError as exc:
            raise FileAccessError(f"Couldn't save {target.name}: {os_problem(exc)}.") from None
        try:
            with handle:
                handle.write(data)
        except OSError as exc:
            _remove_quietly(target)  # never leave a half-written file (e.g. disk full)
            raise FileAccessError(f"Couldn't save {target.name}: {os_problem(exc)}.") from None
        return target
    raise FileAccessError(f"Couldn't find a free file name in {folder}.")
