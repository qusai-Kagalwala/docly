"""Tests for docly.core.files."""

from __future__ import annotations

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
