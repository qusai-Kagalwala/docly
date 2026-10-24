"""Small, careful file helpers shared by the engine and batch mode.

Rules: never overwrite anything, handle Unicode and long Windows paths,
and turn OS errors into readable :class:`FileAccessError` messages.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from docly.core.errors import FileAccessError, ImageTooLargeError

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


def read_bytes(path: Path, max_bytes: int) -> bytes:
    """Read a whole file, refusing anything bigger than ``max_bytes``."""
    try:
        size = os.stat(os_path(path)).st_size
    except FileNotFoundError:
        raise FileAccessError(f"File not found: {path.name}") from None
    except PermissionError:
        raise FileAccessError(f"Docly doesn't have permission to open {path.name}.") from None
    except OSError as exc:
        raise FileAccessError(f"Couldn't open {path.name}: {exc.strerror or exc}") from None
    if os.path.isdir(os_path(path)):
        raise FileAccessError(f"{path.name} is a folder, not a file.")
    if size > max_bytes:
        raise ImageTooLargeError(
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
        raise FileAccessError(f"Couldn't read {path.name}: {exc.strerror or exc}") from None
    if len(data) > max_bytes:  # the file grew after we checked its size
        raise ImageTooLargeError(f"{path.name} is larger than {max_bytes / 1_048_576:.0f} MB.")
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


def write_new_file(folder: Path, file_name: str, data: bytes) -> Path:
    """Write ``data`` to a new file in ``folder``; never overwrites.

    Uses exclusive-create mode, so even if another program creates the same
    name at the same moment, the existing file is never replaced.
    """
    try:
        os.makedirs(os_path(folder), exist_ok=True)
    except OSError as exc:
        raise FileAccessError(f"Couldn't create the folder {folder}: {exc.strerror or exc}") from None
    for _attempt in range(100):
        target = unique_path(folder, file_name)
        try:
            with open(os_path(target), "xb") as handle:
                handle.write(data)
            return target
        except FileExistsError:
            continue  # someone took the name in between; try the next one
        except PermissionError:
            raise FileAccessError(
                f"Docly can't save into {folder}. Choose a folder you can write to."
            ) from None
        except OSError as exc:
            raise FileAccessError(f"Couldn't save {target.name}: {exc.strerror or exc}") from None
    raise FileAccessError(f"Couldn't find a free file name in {folder}.")
