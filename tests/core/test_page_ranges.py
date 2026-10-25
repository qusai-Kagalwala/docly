"""Tests for page-range parsing."""

from __future__ import annotations

import pytest

from docly.core.errors import InvalidPageRangeError
from docly.core.page_ranges import format_pages, parse_pages, parse_ranges


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", [[0]]),
        ("2-4", [[1, 2, 3]]),
        ("1-3, 5", [[0, 1, 2], [4]]),
        ("8-", [[7, 8, 9]]),
        ("-3", [[0, 1, 2]]),
        (" 1 - 2 ;  4 ", [[0, 1], [3]]),
        ("3–5", [[2, 3, 4]]),  # en dash, as Word and phones type it
        ("1,,2,", [[0], [1]]),
        ("5-5", [[4]]),
    ],
)
def test_parse_ranges(text: str, expected: list[list[int]]) -> None:
    assert parse_ranges(text, 10) == expected


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("", "Type the pages"),
        (" , ", "Type the pages"),
        ("12", "Page 12 doesn't exist; this document has 10 pages"),
        ("0", "numbered from 1"),
        ("5-2", "did you mean 2-5"),
        ("abc", "isn't a page number"),
        ("1-2-3", "isn't a page number"),
        ("-", "isn't a page number"),
    ],
)
def test_parse_errors(text: str, fragment: str) -> None:
    with pytest.raises(InvalidPageRangeError, match=fragment):
        parse_ranges(text, 10)


def test_single_page_wording() -> None:
    with pytest.raises(InvalidPageRangeError, match="has 1 page\\."):
        parse_ranges("2", 1)


def test_parse_pages_flattens_and_dedupes_in_order() -> None:
    assert parse_pages("5, 1-3, 2", 6) == [4, 0, 1, 2]


@pytest.mark.parametrize(
    "indexes,text",
    [([], ""), ([0], "1"), ([0, 1, 2, 4], "1-3, 5"), ([4, 0], "5, 1"), ([2, 3, 7, 8, 9], "3-4, 8-10")],
)
def test_format_pages(indexes: list[int], text: str) -> None:
    assert format_pages(indexes) == text


def test_round_trip() -> None:
    text = "1-3, 7, 9-10"
    assert format_pages(parse_pages(text, 10)) == text
