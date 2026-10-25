"""PDF operations built on one idea: the **page plan**.

A plan is a list of :class:`PageRef` — "page 3 of source A, turned 90°",
"the photo in source B", and so on. :func:`build_pdf` writes any plan to a
new PDF. Merging, extracting, deleting, reordering, rotating and
images → PDF are all just different plans.

Sources are opened once (:func:`load_source`) and can be PDFs or images.
Originals are never modified; results come back as bytes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from docly.core.compress import CancelCheck
from docly.core.errors import CancelledError, InvalidPageRangeError
from docly.core.files import read_bytes, safe_stem
from docly.core.image_io import MAX_FILE_BYTES, load_image_bytes
from docly.core.image_pdf import PageSize, add_image_page
from docly.core.page_ranges import format_pages, parse_pages, parse_ranges
from docly.core.pdf_io import OpenedPdf, is_pdf, open_pdf_bytes, sanitize_page, save_pdf
from docly.logger import get_logger

log = get_logger(__name__)

ProgressCallback = Callable[[int, int], None]  # (pages done, total pages)
VALID_ANGLES = (0, 90, 180, 270)


@dataclass
class Source:
    """One input file, opened and checked. Close with :meth:`close`."""

    path: Path
    name: str
    pdf: OpenedPdf | None = None  # set for PDF sources
    image_data: bytes | None = None  # set for image sources

    @property
    def is_pdf(self) -> bool:
        return self.pdf is not None

    @property
    def page_count(self) -> int:
        return self.pdf.page_count if self.pdf is not None else 1

    @property
    def warnings(self) -> list[str]:
        return list(self.pdf.warnings) if self.pdf is not None else []

    def close(self) -> None:
        if self.pdf is not None:
            self.pdf.close()


@dataclass(frozen=True)
class PageRef:
    """One page of the output: which source, which page, extra rotation."""

    source: int  # index into the sources list
    page: int = 0  # 0-based page within that source
    rotate: int = 0  # clockwise degrees added to the page's own rotation


@dataclass
class PdfResult:
    """A finished PDF and what went into it."""

    data: bytes
    page_count: int
    suggested_name: str
    warnings: list[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.data)


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------
def load_source(path: Path, password: str | None = None) -> Source:
    """Open a PDF or image for use in a plan. Raises :class:`DoclyError`."""
    path = Path(path)
    data = read_bytes(path, max(MAX_FILE_BYTES, 200 * 1024 * 1024))
    if is_pdf(data):
        return Source(path, path.name, pdf=open_pdf_bytes(data, path.name, password))
    load_image_bytes(data, path.name)  # validate now so errors appear when adding the file
    return Source(path, path.name, image_data=data)


def close_all(sources: Sequence[Source]) -> None:
    for source in sources:
        source.close()


# ----------------------------------------------------------------------
# Plans
# ----------------------------------------------------------------------
def all_pages(sources: Sequence[Source]) -> list[PageRef]:
    """Every page of every source, in order (a merge)."""
    return [PageRef(i, p) for i, s in enumerate(sources) for p in range(s.page_count)]


def build_pdf(
    sources: Sequence[Source],
    plan: Sequence[PageRef],
    suggested_name: str = "document.pdf",
    page_size: PageSize = PageSize.A4,
    cancel: CancelCheck | None = None,
    progress: ProgressCallback | None = None,
) -> PdfResult:
    """Write ``plan`` as a new PDF. Raises :class:`DoclyError` on bad input."""
    if not plan:
        raise InvalidPageRangeError("There are no pages to save.")
    for ref in plan:
        _check_ref(sources, ref)

    out = pikepdf.Pdf.new()
    total = len(plan)
    removed = 0
    for done, ref in enumerate(plan, start=1):
        if cancel is not None and cancel():
            raise CancelledError()
        source = sources[ref.source]
        if source.pdf is not None:
            out.pages.append(source.pdf.pdf.pages[ref.page])
        else:
            add_image_page(out, source.image_data or b"", source.name, page_size)
        removed += sanitize_page(out.pages[-1])
        if progress is not None:
            progress(done, total)

    # Rotate only after every page is in place: when the plan uses the same
    # page twice, the second copy is made from the first, so rotating as we
    # go would turn both copies.
    for index, ref in enumerate(plan):
        if ref.rotate:
            out.pages[index].rotate(ref.rotate, relative=True)

    warnings: list[str] = []
    for index in sorted({ref.source for ref in plan}):
        warnings.extend(sources[index].warnings)
    if removed:
        warnings.append("Removed links or attachments that could run programs or scripts.")
        log.info("Removed %d risky actions/attachments", removed)

    data = save_pdf(out)
    out.close()
    return PdfResult(data, total, suggested_name, warnings)


# ----------------------------------------------------------------------
# Everyday operations (each is just a plan)
# ----------------------------------------------------------------------
def merge(sources: Sequence[Source], page_size: PageSize = PageSize.A4, **kwargs) -> PdfResult:
    """All pages of all sources, in order. Images become one page each."""
    name = f"{_stem(sources[0])}_merged.pdf" if len(sources) > 1 else f"{_stem(sources[0])}.pdf"
    return build_pdf(sources, all_pages(sources), name, page_size, **kwargs)


def images_to_pdf(sources: Sequence[Source], page_size: PageSize = PageSize.A4, **kwargs) -> PdfResult:
    """Same as :func:`merge`; named for clarity when every source is a photo."""
    return merge(sources, page_size, **kwargs)


def extract(source: Source, pages: str, **kwargs) -> PdfResult:
    """The pages listed in ``pages`` (e.g. ``"1, 3-4"``), in that order."""
    indexes = parse_pages(pages, source.page_count)
    name = f"{_stem(source)}_pages-{_label(indexes)}.pdf"
    return build_pdf([source], [PageRef(0, i) for i in indexes], name, **kwargs)


def delete_pages(source: Source, pages: str, **kwargs) -> PdfResult:
    """Everything except the pages listed."""
    drop = set(parse_pages(pages, source.page_count))
    keep = [i for i in range(source.page_count) if i not in drop]
    if not keep:
        raise InvalidPageRangeError("That would delete every page. Keep at least one.")
    return build_pdf([source], [PageRef(0, i) for i in keep], f"{_stem(source)}_edited.pdf", **kwargs)


def rotate(source: Source, pages: str, angle: int, **kwargs) -> PdfResult:
    """Turn the listed pages clockwise by ``angle`` (90, 180 or 270)."""
    angle = _valid_angle(angle)
    chosen = set(parse_pages(pages, source.page_count))
    plan = [PageRef(0, i, angle if i in chosen else 0) for i in range(source.page_count)]
    return build_pdf([source], plan, f"{_stem(source)}_rotated.pdf", **kwargs)


def split_by_ranges(source: Source, ranges: str, **kwargs) -> list[PdfResult]:
    """One PDF per comma-separated range, e.g. ``"1-2, 3-5, 6-"`` → 3 files."""
    groups = parse_ranges(ranges, source.page_count)
    return [
        build_pdf([source], [PageRef(0, i) for i in group], f"{_stem(source)}_pages-{_label(group)}.pdf", **kwargs)
        for group in groups
    ]


def split_every(source: Source, n: int, **kwargs) -> list[PdfResult]:
    """One PDF per ``n`` pages; ``n = 1`` gives single pages."""
    if n < 1:
        raise InvalidPageRangeError("Split into groups of at least 1 page.")
    count = source.page_count
    groups = [list(range(start, min(start + n, count))) for start in range(0, count, n)]
    return [
        build_pdf([source], [PageRef(0, i) for i in group], f"{_stem(source)}_pages-{_label(group)}.pdf", **kwargs)
        for group in groups
    ]


# ----------------------------------------------------------------------
def _check_ref(sources: Sequence[Source], ref: PageRef) -> None:
    if not 0 <= ref.source < len(sources):
        raise InvalidPageRangeError("A page in the plan refers to a file that isn't open.")
    if not 0 <= ref.page < sources[ref.source].page_count:
        raise InvalidPageRangeError(
            f"Page {ref.page + 1} doesn't exist in {sources[ref.source].name}."
        )
    _valid_angle(ref.rotate)


def _valid_angle(angle: int) -> int:
    normalised = angle % 360
    if normalised not in VALID_ANGLES:
        raise InvalidPageRangeError("Pages can only be turned by 90, 180 or 270 degrees.")
    return normalised


def _stem(source: Source) -> str:
    base = source.name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base[1:] else base
    return safe_stem(stem, fallback="document")


def _label(indexes: Sequence[int]) -> str:
    """``[0, 1, 2]`` → ``"1-3"``; ``[0, 2]`` → ``"1_3"`` (safe in file names)."""
    return format_pages(list(indexes)).replace(", ", "_")
