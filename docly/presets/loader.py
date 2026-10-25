"""Load and validate ``presets.json`` files.

The rule for this module: **never raise**. Preset files are edited by hand
(and by users), so anything can be wrong with them. Every problem becomes a
:class:`PresetIssue`; bad presets are skipped and good ones still load.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from docly import config
from docly.logger import get_logger
from docly.presets.models import Category, FileFormat, Preset, PresetKind

log = get_logger(__name__)

SUPPORTED_SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1_000_000  # a presets file has no reason to be bigger
MAX_PIXELS = 10_000
MAX_KB = 10_240  # 10 MB
DPI_RANGE = (72, 1200)
RATIO_TOLERANCE = 0.02  # pixels may differ from the stated ratio by 2 %

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RATIO_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$")
_REGION_RE = re.compile(r"^(?:[A-Z]{2}|INTL|EU)$")

KNOWN_FIELDS = frozenset(
    {
        "id", "name", "portal", "region", "category", "kind", "formats",
        "width_px", "height_px", "min_width_px", "max_width_px",
        "min_height_px", "max_height_px", "aspect_ratio", "dpi",
        "kb_min", "kb_max", "notes", "source", "last_verified", "verified", "tags",
        "no_edits",
    }
)  # fmt: skip


@dataclass(frozen=True)
class PresetIssue:
    """One problem (or note) found while loading presets."""

    file: str
    message: str
    level: str = "error"  # "error" (preset skipped), "warning" or "info"
    preset_id: str | None = None
    field: str | None = None

    def __str__(self) -> str:
        where = self.file
        if self.preset_id:
            where += f" › {self.preset_id}"
        if self.field:
            where += f" › {self.field}"
        return f"{where}: {self.message}"


@dataclass
class PresetLoadResult:
    """Valid presets plus everything that went wrong."""

    presets: list[Preset] = field(default_factory=list)
    issues: list[PresetIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[PresetIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[PresetIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def skipped_count(self) -> int:
        """How many presets were skipped (one preset can have several errors)."""
        return len({(i.file, i.preset_id) for i in self.errors if i.preset_id is not None})

    @property
    def ok(self) -> bool:
        """True when there were no errors (warnings are allowed)."""
        return not self.errors

    def by_id(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def load_presets(path: Path, origin: str = "bundled") -> PresetLoadResult:
    """Read and validate a presets file. Never raises."""
    name = path.name
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return _fail(name, f"File not found: {path}")
    except OSError as exc:
        return _fail(name, f"Cannot read file: {exc}")
    if size > MAX_FILE_BYTES:
        return _fail(name, f"File is too large ({size:,} bytes; limit {MAX_FILE_BYTES:,}).")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _fail(name, f"Cannot read file: {exc}")
    try:
        # utf-8-sig also accepts the BOM that Windows Notepad sometimes adds.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _fail(name, "File is not valid UTF-8 text.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return _fail(name, f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
    except RecursionError:
        return _fail(name, "JSON is nested too deeply.")
    return parse_presets(data, name, origin)


def parse_presets(data: Any, file_name: str = "<data>", origin: str = "bundled") -> PresetLoadResult:
    """Validate already-parsed JSON (``dict``) into presets. Never raises."""
    result = PresetLoadResult()
    if not isinstance(data, dict):
        return _fail(file_name, "Top level must be an object with 'schema_version' and 'presets'.")

    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION or isinstance(version, bool):
        return _fail(
            file_name,
            f"Unsupported schema_version {version!r}; this version of Docly reads {SUPPORTED_SCHEMA_VERSION}.",
        )
    entries = data.get("presets")
    if not isinstance(entries, list):
        return _fail(file_name, "'presets' must be a list.")

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        preset, issues = _parse_entry(entry, index, file_name, origin)
        result.issues.extend(issues)
        if preset is None:
            continue
        if preset.id in seen:
            result.issues.append(
                PresetIssue(file_name, "Duplicate id; this entry was skipped.", preset_id=preset.id, field="id")
            )
            continue
        seen.add(preset.id)
        result.presets.append(preset)
    return result


def merge_presets(base: PresetLoadResult, override: PresetLoadResult) -> PresetLoadResult:
    """Combine two results; presets in ``override`` replace same-id ones in ``base``."""
    merged = {p.id: p for p in base.presets}
    issues = list(base.issues) + list(override.issues)
    for preset in override.presets:
        if preset.id in merged:
            issues.append(
                PresetIssue("user presets.json", "Replaces the built-in preset with the same id.", "info", preset.id)
            )
        merged[preset.id] = preset
    return PresetLoadResult(list(merged.values()), issues)


def default_presets(bundled_path: Path | None = None, user_path: Path | None = None) -> PresetLoadResult:
    """Built-in presets plus the user's own file (if it exists). Never raises.

    The user file lives in AppData because the install folder (Program Files)
    is read-only. A broken user file is reported, and the built-in presets
    are still returned.
    """
    bundled = load_presets(bundled_path or config.BUNDLED_PRESETS_PATH, origin="bundled")
    user_file = user_path if user_path is not None else config.user_presets_path()
    if not user_file.exists():
        return bundled
    user = load_presets(user_file, origin="user")
    user.issues[:] = [_relabel(issue, f"user {issue.file}") for issue in user.issues]
    return merge_presets(bundled, user)


# ----------------------------------------------------------------------
# Validation of one entry
# ----------------------------------------------------------------------
class _Entry:
    """Collects errors and warnings while reading one preset dict."""

    def __init__(self, data: dict[str, Any], file_name: str, preset_id: str | None) -> None:
        self.data = data
        self.file = file_name
        self.id = preset_id
        self.issues: list[PresetIssue] = []

    def error(self, field_name: str, message: str) -> None:
        self.issues.append(PresetIssue(self.file, message, "error", self.id, field_name))

    def warn(self, field_name: str, message: str) -> None:
        self.issues.append(PresetIssue(self.file, message, "warning", self.id, field_name))

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    # --- typed getters (return None and record an error when invalid) ---
    def text(self, key: str, required: bool = False, max_len: int = 200) -> str | None:
        value = self.data.get(key)
        if value is None:
            if required:
                self.error(key, "Required field is missing.")
            return None
        if not isinstance(value, str):
            self.error(key, "Must be text.")
            return None
        value = value.strip()
        if required and not value:
            self.error(key, "Must not be empty.")
            return None
        if len(value) > max_len:
            self.error(key, f"Too long (max {max_len} characters).")
            return None
        return value

    def integer(self, key: str, lo: int, hi: int) -> int | None:
        value = self.data.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self.error(key, "Must be a whole number.")
            return None
        if not lo <= value <= hi:
            self.error(key, f"Must be between {lo} and {hi}.")
            return None
        return value

    def number(self, key: str, lo: float, hi: float) -> float | None:
        value = self.data.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.error(key, "Must be a number.")
            return None
        if not lo <= value <= hi:
            self.error(key, f"Must be between {lo:g} and {hi:g}.")
            return None
        return float(value)


def _parse_entry(
    entry: Any, index: int, file_name: str, origin: str
) -> tuple[Preset | None, list[PresetIssue]]:
    if not isinstance(entry, dict):
        return None, [PresetIssue(file_name, f"Entry #{index + 1} is not an object; skipped.")]

    raw_id = entry.get("id")
    label = raw_id if isinstance(raw_id, str) and raw_id else f"entry #{index + 1}"
    e = _Entry(entry, file_name, label)

    # --- identity -----------------------------------------------------
    preset_id = e.text("id", required=True, max_len=64)
    if preset_id is not None and not _ID_RE.match(preset_id):
        e.error("id", "Use lowercase letters, digits and single hyphens, e.g. 'in-ibps-photo'.")
    name = e.text("name", required=True, max_len=80)
    portal = e.text("portal") or ""
    notes = e.text("notes", max_len=2000) or ""

    region = (e.text("region", max_len=4) or "INTL").upper()
    if not _REGION_RE.match(region):
        e.error("region", "Use a 2-letter country code (e.g. 'IN', 'US'), 'EU' or 'INTL'.")

    category = _enum(e, "category", Category, default=Category.GENERAL)
    kind = _enum(e, "kind", PresetKind, required=True)
    formats = _formats(e)
    tags = _tags(e)

    # --- size ---------------------------------------------------------
    width = e.integer("width_px", 1, MAX_PIXELS)
    height = e.integer("height_px", 1, MAX_PIXELS)
    if (entry.get("width_px") is None) != (entry.get("height_px") is None):
        e.error("width_px" if width is None else "height_px", "Give both width_px and height_px, or neither.")
    limits = {key: e.integer(key, 1, MAX_PIXELS) for key in ("min_width_px", "max_width_px", "min_height_px", "max_height_px")}
    _check_limits(e, width, height, limits)

    aspect_ratio = _ratio(e, width, height)
    dpi = e.integer("dpi", *DPI_RANGE)
    kb_min = e.number("kb_min", 0, MAX_KB)
    kb_max = e.number("kb_max", 0, MAX_KB)
    if kb_max is not None and kb_max <= 0:
        e.error("kb_max", "Must be greater than 0.")
    if kb_min is not None and kb_max is not None and kb_min > kb_max:
        e.error("kb_min", "kb_min is larger than kb_max.")

    # --- provenance ---------------------------------------------------
    source = e.text("source", max_len=500) or ""
    if source:
        parsed = urlparse(source)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            e.error("source", "Must be an http(s) link or empty.")
    last_verified = _date(e, "last_verified")
    verified = entry.get("verified", False)
    if not isinstance(verified, bool):
        e.error("verified", "Must be true or false.")
        verified = False
    no_edits = entry.get("no_edits", False)
    if not isinstance(no_edits, bool):
        e.error("no_edits", "Must be true or false.")
        no_edits = False

    # --- cross-field rules ----------------------------------------------
    if kind is not None and formats:
        if kind == PresetKind.DOCUMENT and FileFormat.PDF not in formats:
            e.error("formats", "Document presets must accept 'pdf'.")
        if kind != PresetKind.DOCUMENT and FileFormat.PDF in formats:
            e.error("formats", "Image presets cannot output 'pdf'; use kind 'document'.")
    if kind == PresetKind.DOCUMENT and kb_max is None:
        e.error("kb_max", "Document presets need a kb_max.")
    has_rule = any(v is not None for v in (width, aspect_ratio, kb_min, kb_max, *limits.values()))
    if not has_rule and not e.has_errors:
        e.error("kb_max", "Preset has no size, ratio or file-size rule, so there is nothing to check.")

    for key in sorted(set(entry) - KNOWN_FIELDS):
        e.warn(key, "Unknown field ignored (typo?).")

    if e.has_errors or preset_id is None or name is None or kind is None or not formats:
        return None, e.issues

    preset = Preset(
        id=preset_id,
        name=name,
        kind=kind,
        formats=tuple(formats),
        region=region,
        category=category or Category.GENERAL,
        portal=portal,
        width_px=width,
        height_px=height,
        aspect_ratio=aspect_ratio,
        dpi=dpi,
        kb_min=kb_min,
        kb_max=kb_max,
        notes=notes,
        source=source,
        last_verified=last_verified,
        verified=verified,
        no_edits=no_edits,
        tags=tags,
        origin=origin,
        **limits,
    )
    return preset, e.issues


def _enum(e: _Entry, key: str, enum_type: type, required: bool = False, default: Any = None) -> Any:
    value = e.text(key, required=required, max_len=32)
    if value is None:
        return default
    try:
        return enum_type(value.lower())
    except ValueError:
        allowed = ", ".join(m.value for m in enum_type)
        e.error(key, f"Unknown value {value!r}; use one of: {allowed}.")
        return None


def _formats(e: _Entry) -> list[FileFormat]:
    value = e.data.get("formats")
    if value is None:
        e.error("formats", "Required field is missing.")
        return []
    if not isinstance(value, list) or not value:
        e.error("formats", "Must be a non-empty list, e.g. [\"jpg\"].")
        return []
    formats: list[FileFormat] = []
    for item in value:
        try:
            fmt = FileFormat.parse(item) if isinstance(item, str) else None
        except ValueError:
            fmt = None
        if fmt is None:
            allowed = ", ".join(f.value for f in FileFormat)
            e.error("formats", f"Unknown format {item!r}; use: {allowed}.")
            return []
        if fmt not in formats:
            formats.append(fmt)
    return formats


def _tags(e: _Entry) -> tuple[str, ...]:
    value = e.data.get("tags")
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        e.warn("tags", "Must be a list of words; ignored.")
        return ()
    return tuple(dict.fromkeys(t.strip().lower() for t in value if t.strip()))


def _check_limits(e: _Entry, width: int | None, height: int | None, limits: dict[str, int | None]) -> None:
    for axis, target in (("width", width), ("height", height)):
        lo, hi = limits[f"min_{axis}_px"], limits[f"max_{axis}_px"]
        if lo is not None and hi is not None and lo > hi:
            e.error(f"min_{axis}_px", f"min_{axis}_px is larger than max_{axis}_px.")
        elif target is not None:
            if lo is not None and target < lo:
                e.error(f"{axis}_px", f"{axis}_px is below min_{axis}_px.")
            if hi is not None and target > hi:
                e.error(f"{axis}_px", f"{axis}_px is above max_{axis}_px.")


def _ratio(e: _Entry, width: int | None, height: int | None) -> str | None:
    value = e.text("aspect_ratio", max_len=20)
    if value is None:
        return None
    match = _RATIO_RE.match(value)
    if not match or float(match.group(1)) <= 0 or float(match.group(2)) <= 0:
        e.error("aspect_ratio", "Use the form 'width:height', e.g. '35:45' or '1:1'.")
        return None
    ratio = float(match.group(1)) / float(match.group(2))
    if width and height:
        actual = width / height
        if abs(actual - ratio) / ratio > RATIO_TOLERANCE:
            e.error("aspect_ratio", f"{width}×{height} px does not match ratio {value}.")
    return f"{match.group(1)}:{match.group(2)}"


def _date(e: _Entry, key: str) -> date | None:
    value = e.data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        e.error(key, "Must be a date like '2026-10-24', or null.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        e.error(key, "Must be a date like '2026-10-24', or null.")
        return None


def _fail(file_name: str, message: str) -> PresetLoadResult:
    return PresetLoadResult([], [PresetIssue(file_name, message)])


def _relabel(issue: PresetIssue, file_label: str) -> PresetIssue:
    return PresetIssue(file_label, issue.message, issue.level, issue.preset_id, issue.field)
