"""Tests for loading and validating presets files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docly.presets import FileFormat, PresetKind, load_presets, parse_presets
from docly.presets.loader import MAX_FILE_BYTES

VALID = {
    "id": "in-test-photo",
    "name": "Test — Photograph",
    "portal": "Test",
    "region": "IN",
    "category": "exam",
    "kind": "photo",
    "width_px": 200,
    "height_px": 230,
    "kb_min": 20,
    "kb_max": 50,
    "formats": ["jpg"],
    "source": "https://example.org/notice.pdf",
    "last_verified": "2026-10-24",
    "verified": True,
    "tags": ["Banking", "test", "test"],
}


def doc(*entries: dict) -> dict:
    return {"schema_version": 1, "presets": list(entries)}


def with_(**changes) -> dict:
    entry = dict(VALID)
    for key, value in changes.items():
        if value is ...:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


def write(tmp_path: Path, content: str | bytes, name: str = "presets.json") -> Path:
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def single_error(result, field: str | None = None) -> str:
    errors = result.errors
    assert len(errors) == 1, [str(e) for e in result.issues]
    if field is not None:
        assert errors[0].field == field, str(errors[0])
    return errors[0].message


# ----- happy path -----------------------------------------------------
def test_valid_file_loads(tmp_path: Path) -> None:
    result = load_presets(write(tmp_path, json.dumps(doc(VALID))))
    assert result.ok and result.issues == []
    preset = result.presets[0]
    assert preset.id == "in-test-photo"
    assert preset.kind == PresetKind.PHOTO
    assert preset.formats == (FileFormat.JPG,)
    assert preset.kb_min == 20.0 and preset.kb_max == 50.0
    assert preset.last_verified.isoformat() == "2026-10-24"
    assert preset.tags == ("banking", "test")  # lowercased, de-duplicated
    assert result.by_id("in-test-photo") is preset
    assert result.by_id("missing") is None


def test_optional_fields_default(tmp_path: Path) -> None:
    minimal = {"id": "doc-tiny", "name": "Tiny doc", "kind": "document", "formats": ["PDF"], "kb_max": 100}
    result = parse_presets(doc(minimal))
    assert result.ok
    preset = result.presets[0]
    assert preset.region == "INTL"
    assert preset.category.value == "general"
    assert preset.formats == (FileFormat.PDF,)


def test_jpeg_alias_and_lowercase_region() -> None:
    result = parse_presets(doc(with_(formats=["JPEG", "jpg"], region="in")))
    assert result.ok
    assert result.presets[0].formats == (FileFormat.JPG,)
    assert result.presets[0].region == "IN"


def test_utf8_bom_is_accepted(tmp_path: Path) -> None:
    path = write(tmp_path, b"\xef\xbb\xbf" + json.dumps(doc(VALID)).encode("utf-8"))
    assert load_presets(path).ok


def test_unicode_text_is_kept() -> None:
    result = parse_presets(doc(with_(name="परीक्षा — फ़ोटो", notes="Ünïcödé ✅")))
    assert result.ok
    assert result.presets[0].name == "परीक्षा — फ़ोटो"


# ----- whole-file problems -------------------------------------------
def test_missing_file(tmp_path: Path) -> None:
    result = load_presets(tmp_path / "nope.json")
    assert result.presets == []
    assert "not found" in single_error(result)


def test_broken_json_reports_line(tmp_path: Path) -> None:
    path = write(tmp_path, '{\n  "schema_version": 1,\n  "presets": [ { "id": "x", }\n]\n}')
    result = load_presets(path)
    assert result.presets == []
    assert "line 3" in single_error(result)


def test_empty_file(tmp_path: Path) -> None:
    result = load_presets(write(tmp_path, ""))
    assert result.presets == []
    assert "Invalid JSON" in single_error(result)


def test_file_too_large(tmp_path: Path) -> None:
    path = write(tmp_path, " " * (MAX_FILE_BYTES + 1))
    assert "too large" in single_error(load_presets(path))


def test_not_utf8(tmp_path: Path) -> None:
    path = write(tmp_path, '{"schema_version": 1, "presets": []} \xff'.encode("latin-1"))
    assert "UTF-8" in single_error(load_presets(path))


@pytest.mark.parametrize(
    "data,fragment",
    [
        ([], "Top level"),
        ({"presets": []}, "schema_version"),
        ({"schema_version": 2, "presets": []}, "schema_version"),
        ({"schema_version": True, "presets": []}, "schema_version"),
        ({"schema_version": 1}, "'presets' must be a list"),
        ({"schema_version": 1, "presets": {}}, "'presets' must be a list"),
    ],
)
def test_bad_top_level(data, fragment) -> None:
    result = parse_presets(data)
    assert result.presets == []
    assert fragment in single_error(result)


def test_deeply_nested_json_does_not_crash(tmp_path: Path) -> None:
    path = write(tmp_path, "[" * 100_000 + "]" * 100_000)
    result = load_presets(path)
    assert result.presets == [] and result.errors


# ----- one bad preset never stops the others --------------------------
def test_bad_entry_is_skipped_others_load() -> None:
    good_two = with_(id="in-test-two")
    result = parse_presets(doc(VALID, with_(id="Bad ID!"), "not an object", good_two))
    assert [p.id for p in result.presets] == ["in-test-photo", "in-test-two"]
    assert len(result.errors) == 2


def test_skipped_count_counts_presets_not_errors() -> None:
    two_problems = {"id": "broken", "kind": "photo"}  # no name, no formats
    result = parse_presets(doc(VALID, two_problems))
    assert len(result.errors) == 2
    assert result.skipped_count == 1


def test_duplicate_ids() -> None:
    result = parse_presets(doc(VALID, with_(name="Second copy")))
    assert len(result.presets) == 1
    assert result.presets[0].name == "Test — Photograph"
    assert "Duplicate" in single_error(result, "id")


# ----- field validation ----------------------------------------------
@pytest.mark.parametrize("missing", ["id", "name", "kind", "formats"])
def test_required_fields(missing: str) -> None:
    result = parse_presets(doc(with_(**{missing: ...})))
    assert result.presets == []
    assert any(e.field == missing for e in result.errors)


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"id": "UPPER-case"}, "id"),
        ({"id": "double--hyphen"}, "id"),
        ({"name": ""}, "name"),
        ({"name": 42}, "name"),
        ({"kind": "selfie"}, "kind"),
        ({"category": "fun"}, "category"),
        ({"region": "India"}, "region"),
        ({"formats": []}, "formats"),
        ({"formats": ["gif"]}, "formats"),
        ({"formats": "jpg"}, "formats"),
        ({"formats": ["pdf"]}, "formats"),
        ({"width_px": 0}, "width_px"),
        ({"width_px": 20_000}, "width_px"),
        ({"width_px": 200.5}, "width_px"),
        ({"width_px": True}, "width_px"),
        ({"height_px": ...}, "height_px"),
        ({"dpi": 30}, "dpi"),
        ({"kb_max": 0}, "kb_max"),
        ({"kb_max": -5}, "kb_max"),
        ({"kb_max": 999_999}, "kb_max"),
        ({"kb_max": "50"}, "kb_max"),
        ({"kb_min": 60}, "kb_min"),
        ({"aspect_ratio": "wide"}, "aspect_ratio"),
        ({"aspect_ratio": "0:1"}, "aspect_ratio"),
        ({"aspect_ratio": "1:1"}, "aspect_ratio"),
        ({"source": "ftp://example.org"}, "source"),
        ({"source": "not a url"}, "source"),
        ({"last_verified": "24/10/2026"}, "last_verified"),
        ({"verified": "yes"}, "verified"),
    ],
)
def test_invalid_values_are_rejected(changes: dict, field: str) -> None:
    result = parse_presets(doc(with_(**changes)))
    assert result.presets == [], f"{changes} should have been rejected"
    assert any(e.field == field for e in result.errors), [str(e) for e in result.issues]


def test_nan_is_rejected() -> None:
    result = parse_presets(json.loads('{"schema_version":1,"presets":[' + json.dumps(VALID)[:-1] + ',"kb_min":NaN}]}'))
    assert result.presets == []


def test_ratio_matching_pixels_is_accepted() -> None:
    assert parse_presets(doc(with_(width_px=413, height_px=531, aspect_ratio="35:45"))).ok


def test_pixel_limits() -> None:
    ok = with_(width_px=600, height_px=600, min_width_px=600, max_width_px=1200, min_height_px=600, max_height_px=1200)
    assert parse_presets(doc(ok)).ok
    bad_order = with_(min_width_px=900, max_width_px=600)
    assert single_error(parse_presets(doc(bad_order)), "min_width_px")
    outside = with_(width_px=200, min_width_px=300)
    assert single_error(parse_presets(doc(outside)), "width_px")


def test_document_rules() -> None:
    no_limit = {"id": "doc", "name": "Doc", "kind": "document", "formats": ["pdf"]}
    assert single_error(parse_presets(doc(no_limit)), "kb_max")
    jpg_doc = dict(no_limit, kb_max=100, formats=["jpg"])
    assert single_error(parse_presets(doc(jpg_doc)), "formats")


def test_preset_without_any_rule_is_rejected() -> None:
    empty = {"id": "nothing", "name": "Nothing", "kind": "photo", "formats": ["jpg"]}
    assert "nothing to check" in single_error(parse_presets(doc(empty)))


def test_unknown_field_is_a_warning_not_an_error() -> None:
    result = parse_presets(doc(with_(kb_mx=50)))
    assert result.ok and len(result.presets) == 1
    assert [w.field for w in result.warnings] == ["kb_mx"]


def test_bad_tags_are_a_warning() -> None:
    result = parse_presets(doc(with_(tags="banking")))
    assert result.ok and result.presets[0].tags == ()
    assert result.warnings


def test_issue_text_is_readable() -> None:
    result = parse_presets(doc(with_(kb_min=60)), file_name="presets.json")
    assert str(result.errors[0]) == "presets.json › in-test-photo › kb_min: kb_min is larger than kb_max."
