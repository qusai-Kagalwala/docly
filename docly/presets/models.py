"""Preset data model.

A preset describes one upload rule: what a portal accepts for a photo,
signature, other image or document. Pure Python, no Qt, so ``core/`` and
tests can use it without a GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

#: Docly treats 1 KB as 1024 bytes, which is how Windows Explorer shows sizes.
BYTES_PER_KB = 1024

INTL_REGION = "INTL"  # universal presets, not tied to one country

#: Friendly names for region codes used in the bundled presets.
REGION_NAMES: dict[str, str] = {
    "INTL": "Universal",
    "EU": "European Union",
    "IN": "India",
    "US": "United States",
    "GB": "United Kingdom",
}


class PresetKind(str, Enum):
    """What is being uploaded. Decides which page uses the preset."""

    PHOTO = "photo"
    SIGNATURE = "signature"
    IMAGE = "image"  # other image uploads: thumb impression, declaration, ID
    DOCUMENT = "document"  # PDF uploads


class Category(str, Enum):
    """Used to group presets in the dropdown."""

    EXAM = "exam"
    GOVERNMENT = "government"
    VISA = "visa"
    PASSPORT = "passport"
    GENERAL = "general"


class FileFormat(str, Enum):
    """Output formats a preset can accept."""

    JPG = "jpg"
    PNG = "png"
    PDF = "pdf"

    @classmethod
    def parse(cls, value: str) -> FileFormat:
        """Accept ``jpg``, ``JPEG``, ``.png`` etc. Raises ``ValueError``."""
        cleaned = value.strip().lower().lstrip(".")
        if cleaned == "jpeg":
            cleaned = "jpg"
        return cls(cleaned)


def format_kb(kb: float) -> str:
    """``50`` -> ``"50 KB"``, ``10240`` -> ``"10 MB"``, ``1.5`` -> ``"1.5 KB"``."""
    if kb >= 1024:
        mb = kb / 1024
        return f"{mb:g} MB"
    return f"{kb:g} KB"


def region_name(code: str) -> str:
    """Human name for a region code (falls back to the code itself)."""
    return REGION_NAMES.get(code, code)


@dataclass(frozen=True)
class Preset:
    """One validated upload rule. Create these through the loader.

    Size fields are all optional because portals state rules differently:
    exact pixels, a pixel range, only a ratio, or only a file-size limit.
    ``width_px``/``height_px`` is the size Docly outputs; the ``min_``/``max_``
    fields are what the portal will accept.
    """

    id: str
    name: str
    kind: PresetKind
    formats: tuple[FileFormat, ...]
    region: str = INTL_REGION
    category: Category = Category.GENERAL
    portal: str = ""
    width_px: int | None = None
    height_px: int | None = None
    min_width_px: int | None = None
    max_width_px: int | None = None
    min_height_px: int | None = None
    max_height_px: int | None = None
    aspect_ratio: str | None = None  # "w:h", e.g. "35:45"
    dpi: int | None = None
    kb_min: float | None = None
    kb_max: float | None = None
    notes: str = ""
    source: str = ""
    last_verified: date | None = None
    verified: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
    origin: str = "bundled"  # "bundled" or "user"

    # ----- derived values ---------------------------------------------
    @property
    def ratio(self) -> float | None:
        """Width ÷ height, from ``aspect_ratio`` or the target pixels."""
        if self.aspect_ratio:
            w, h = (float(part) for part in self.aspect_ratio.split(":"))
            return w / h
        if self.width_px and self.height_px:
            return self.width_px / self.height_px
        return None

    @property
    def is_image(self) -> bool:
        return self.kind != PresetKind.DOCUMENT

    @property
    def region_label(self) -> str:
        return region_name(self.region)

    @property
    def max_bytes(self) -> int | None:
        """Upper size limit in bytes, if the preset has one."""
        return None if self.kb_max is None else int(self.kb_max * BYTES_PER_KB)

    @property
    def min_bytes(self) -> int | None:
        """Lower size limit in bytes, if the preset has one."""
        return None if self.kb_min is None else int(self.kb_min * BYTES_PER_KB)

    def accepts(self, fmt: str | FileFormat) -> bool:
        """True if the preset allows this output format."""
        try:
            parsed = fmt if isinstance(fmt, FileFormat) else FileFormat.parse(fmt)
        except ValueError:
            return False
        return parsed in self.formats

    # ----- display text -----------------------------------------------
    @property
    def kb_range_text(self) -> str:
        """e.g. ``"20–50 KB"``, ``"up to 240 KB"``, ``"50 KB – 10 MB"``."""
        lo, hi = self.kb_min, self.kb_max
        if lo is not None and hi is not None:
            if hi < 1024:
                return f"{lo:g}–{hi:g} KB"
            return f"{format_kb(lo)} – {format_kb(hi)}"
        if hi is not None:
            return f"up to {format_kb(hi)}"
        if lo is not None:
            return f"at least {format_kb(lo)}"
        return ""

    @property
    def pixel_text(self) -> str:
        """e.g. ``"200 × 230 px"`` or ``"600–1200 × 600–1200 px"``."""
        if self.width_px and self.height_px and not self._has_limits():
            return f"{self.width_px} × {self.height_px} px"
        if self._has_limits():
            width = _range_text(self.min_width_px, self.max_width_px)
            height = _range_text(self.min_height_px, self.max_height_px)
            return f"{width} × {height} px"
        if self.aspect_ratio:
            return f"ratio {self.aspect_ratio}"
        return ""

    def _has_limits(self) -> bool:
        return any(
            v is not None for v in (self.min_width_px, self.max_width_px, self.min_height_px, self.max_height_px)
        )


def _range_text(lo: int | None, hi: int | None) -> str:
    if lo is not None and hi is not None:
        return str(lo) if lo == hi else f"{lo}–{hi}"
    if lo is not None:
        return f"≥{lo}"
    if hi is not None:
        return f"≤{hi}"
    return "any"
