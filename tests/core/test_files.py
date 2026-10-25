"""Tests for docly.core.files."""

from __future__ import annotations

import errno
import sys
from pathlib import Path

import pytest

from docly.core import files
from docly.core.errors import FileAccessError, FileTooLargeError


@pytest.mark.parametrize(
    "name,expected",
    [
        ("photo", "photo"),
        ('my:photo?*"<>|', "my_photo______"),
        ("  trailing dots... ", "trailing dots"),
        ("फ़ोटो ñ", "फ़ोटो ñ"),
        ("CON", "CON_"),
        ("", "file"),
        ("...", "file"),
        ("a" * 200, "a" * files.MAX_STEM),
    ],
)
def test_safe_stem(name: str, expected: str) -> None:
    assert files.safe_stem(name) == expected


def test_unique_path_adds_counter(tmp_path: Path) -> None:
    assert files.unique_path(tmp_path, "a.jpg") == tmp_path / "a.jpg"
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "a (2).jpg").write_bytes(b"2")
    assert files.unique_path(tmp_path, "a.jpg") == tmp_path / "a (3).jpg"


def test_write_new_file_never_overwrites(tmp_path: Path) -> None:
    first = files.write_new_file(tmp_path, "out.jpg", b"first")
    second = files.write_new_file(tmp_path, "out.jpg", b"second")
    assert first != second
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_write_new_file_creates_folder(tmp_path: Path) -> None:
    target = files.write_new_file(tmp_path / "Docly_Output" / "नया", "x.jpg", b"data")
    assert target.read_bytes() == b"data"


def test_write_into_a_file_path_fails_cleanly(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    with pytest.raises(FileAccessError):
        files.write_new_file(blocker / "sub", "x.jpg", b"data")


def test_read_bytes_errors(tmp_path: Path) -> None:
    with pytest.raises(FileAccessError, match="not found"):
        files.read_bytes(tmp_path / "missing.jpg", 100)
    with pytest.raises(FileAccessError, match="folder"):
        files.read_bytes(tmp_path, 100)
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 200)
    with pytest.raises(FileTooLargeError):
        files.read_bytes(big, 100)
    assert files.read_bytes(big, 200) == b"x" * 200


def test_long_windows_paths_get_prefix(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    long_path = Path("C:/" + "folder/" * 40 + "photo.jpg")
    result = files.os_path(long_path)
    assert result.startswith("\\\\?\\")
    short = files.os_path(Path("C:/photo.jpg"))
    assert not short.startswith("\\\\?\\")


def test_other_platforms_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    long_path = Path("/" + "folder/" * 40 + "photo.jpg")
    assert files.os_path(long_path) == str(long_path)


# ----- Phase 12b: plain-words OS errors, mislabelled files, no half-written files
def _os_error(errno_value: int = 0, winerror: int | None = None) -> OSError:
    exc = OSError(errno_value, "raw message")
    if winerror is not None:
        exc.winerror = winerror  # type: ignore[attr-defined]
    return exc


@pytest.mark.parametrize(
    ("exc", "words"),
    [
        (_os_error(errno.ENOSPC), "disk is full"),
        (_os_error(winerror=112), "disk is full"),
        (_os_error(winerror=362), "OneDrive"),
        (_os_error(winerror=206), "path is too long"),
        (_os_error(errno.ENAMETOOLONG), "path is too long"),
        (_os_error(errno.EIO), "raw message"),
    ],
)
def test_os_problem_in_plain_words(exc: OSError, words: str) -> None:
    assert words in files.os_problem(exc)


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"%PDF-1.7 ...", "a PDF"),
        (b"\xff\xd8\xff\xe0....", "a JPEG photo"),
        (b"\x89PNG\r\n\x1a\n....", "a PNG image"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "a WebP image"),
        (b"PK\x03\x04....word/document.xml", "a Word document"),
        (b"  <!DOCTYPE html><html>", "a web page (HTML) — it may be a download that failed"),
        (b"just text", None),
        (b"", None),
    ],
)
def test_describe_content(data: bytes, kind: str | None) -> None:
    assert files.describe_content(data) == kind


def test_disk_full_leaves_no_half_written_file(tmp_path: Path, monkeypatch) -> None:
    real_open = open

    class FullDisk:
        def __init__(self, handle) -> None:  # noqa: ANN001
            self.handle = handle

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args) -> None:  # noqa: ANN002
            self.handle.close()

        def write(self, data: bytes) -> int:
            self.handle.write(data[:10])
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("builtins.open", lambda path, mode="r", *a, **k: FullDisk(real_open(path, mode, *a, **k)) if mode == "xb" else real_open(path, mode, *a, **k))
    with pytest.raises(FileAccessError, match="disk is full"):
        files.write_new_file(tmp_path, "photo.jpg", b"x" * 1000)
    assert list(tmp_path.iterdir()) == []


def test_write_file_disk_full_keeps_the_old_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "keep.pdf"
    target.write_bytes(b"old")
    monkeypatch.setattr(files.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")))
    with pytest.raises(FileAccessError, match="disk is full"):
        files.write_file(target, b"new")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["keep.pdf"]
