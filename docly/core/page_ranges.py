"""Turn page numbers people type ("1-3, 5, 8-") into page indexes.

Users count pages from 1; the code counts from 0. Everything here takes and
gives 1-based text and returns **0-based indexes**.
"""

from __future__ import annotations

import re

from docly.core.errors import InvalidPageRangeError

_PART = re.compile(r"^(?P<start>\d*)\s*(?P<dash>-)?\s*(?P<end>\d*)$")
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})  # en/em dash, minus sign


def parse_ranges(text: str, page_count: int) -> list[list[int]]:
    """Parse ``text`` into groups of 0-based page indexes.

    Each comma-separated part is one group, so ``"1-3, 5"`` gives
    ``[[0, 1, 2], [4]]``. Splitting uses the groups; extracting just joins
    them. Accepted forms: ``5``, ``2-4``, ``8-`` (8 to the end), ``-3`` (start
    to 3). Commas or semicolons separate parts; spaces are ignored.

    Raises :class:`InvalidPageRangeError` with a message for the user.
    """
    if page_count < 1:
        raise InvalidPageRangeError("This document has no pages.")
    cleaned = text.translate(_DASHES).replace(";", ",").strip()
    if not cleaned:
        raise InvalidPageRangeError("Type the pages you want, for example 1-3, 5.")

    groups: list[list[int]] = []
    for raw in cleaned.split(","):
        part = raw.strip()
        if not part:
            continue
        match = _PART.match(part.replace(" ", ""))
        if not match or (not match["start"] and not match["end"]):
            raise InvalidPageRangeError(f"'{part}' isn't a page number or range. Use forms like 3, 2-5 or 8-.")
        start = int(match["start"]) if match["start"] else 1
        if match["dash"]:
            end = int(match["end"]) if match["end"] else page_count
        else:
            end = start
        for number in (start, end):
            if number < 1:
                raise InvalidPageRangeError("Pages are numbered from 1.")
            if number > page_count:
                pages = "page" if page_count == 1 else "pages"
                raise InvalidPageRangeError(
                    f"Page {number} doesn't exist; this document has {page_count} {pages}."
                )
        if start > end:
            raise InvalidPageRangeError(f"'{part}' goes backwards; did you mean {end}-{start}?")
        groups.append(list(range(start - 1, end)))

    if not groups:
        raise InvalidPageRangeError("Type the pages you want, for example 1-3, 5.")
    return groups


def parse_pages(text: str, page_count: int) -> list[int]:
    """All pages in ``text`` as one ordered list without repeats (0-based)."""
    seen: dict[int, None] = {}
    for group in parse_ranges(text, page_count):
        for index in group:
            seen.setdefault(index, None)
    return list(seen)


def format_pages(indexes: list[int]) -> str:
    """0-based indexes → compact 1-based text, e.g. ``[0, 1, 2, 4]`` → ``"1-3, 5"``."""
    if not indexes:
        return ""
    parts: list[str] = []
    run_start = previous = indexes[0]
    for index in indexes[1:] + [None]:  # type: ignore[list-item]
        if index is not None and index == previous + 1:
            previous = index
            continue
        parts.append(str(run_start + 1) if run_start == previous else f"{run_start + 1}-{previous + 1}")
        if index is not None:
            run_start = previous = index
    return ", ".join(parts)
