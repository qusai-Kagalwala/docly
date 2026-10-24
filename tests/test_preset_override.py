"""Tests for merging the user's AppData presets with the built-in ones."""

from __future__ import annotations

import json
from pathlib import Path

from docly import config
from docly.presets import default_presets

BUILT_IN = {
    "schema_version": 1,
    "presets": [
        {"id": "intl-a", "name": "A", "kind": "photo", "formats": ["jpg"], "kb_max": 50},
        {"id": "intl-b", "name": "B", "kind": "photo", "formats": ["jpg"], "kb_max": 60},
    ],
}


def write(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def test_no_user_file_means_built_in_only(tmp_path: Path) -> None:
    bundled = write(tmp_path / "bundled.json", BUILT_IN)
    result = default_presets(bundled, tmp_path / "missing.json")
    assert [p.id for p in result.presets] == ["intl-a", "intl-b"]
    assert result.issues == []


def test_user_file_adds_and_replaces(tmp_path: Path) -> None:
    bundled = write(tmp_path / "bundled.json", BUILT_IN)
    user = write(
        tmp_path / "user.json",
        {
            "schema_version": 1,
            "presets": [
                {"id": "intl-b", "name": "B (fixed)", "kind": "photo", "formats": ["jpg"], "kb_max": 80},
                {"id": "my-own", "name": "Mine", "kind": "signature", "formats": ["png"], "kb_max": 30},
            ],
        },
    )
    result = default_presets(bundled, user)
    by_id = {p.id: p for p in result.presets}
    assert set(by_id) == {"intl-a", "intl-b", "my-own"}
    assert by_id["intl-b"].name == "B (fixed)" and by_id["intl-b"].origin == "user"
    assert by_id["intl-a"].origin == "bundled"
    assert result.ok
    assert [i.preset_id for i in result.issues if i.level == "info"] == ["intl-b"]


def test_broken_user_file_keeps_built_in(tmp_path: Path) -> None:
    bundled = write(tmp_path / "bundled.json", BUILT_IN)
    user = write(tmp_path / "user.json", "{ this is not json")
    result = default_presets(bundled, user)
    assert [p.id for p in result.presets] == ["intl-a", "intl-b"]
    assert len(result.errors) == 1
    assert result.errors[0].file.startswith("user ")


def test_bad_user_preset_does_not_replace_good_built_in(tmp_path: Path) -> None:
    bundled = write(tmp_path / "bundled.json", BUILT_IN)
    user = write(
        tmp_path / "user.json",
        {"schema_version": 1, "presets": [{"id": "intl-a", "name": "A", "kind": "photo", "formats": ["jpg"], "kb_max": -1}]},
    )
    result = default_presets(bundled, user)
    assert result.by_id("intl-a").kb_max == 50
    assert result.by_id("intl-a").origin == "bundled"


def test_default_paths_use_app_data(app_data: Path) -> None:
    assert config.user_presets_path() == app_data / "presets.json"
    write(
        config.user_presets_path(),
        {"schema_version": 1, "presets": [{"id": "my-only", "name": "Mine", "kind": "photo", "formats": ["jpg"], "kb_max": 9}]},
    )
    result = default_presets()
    assert result.by_id("my-only") is not None
    assert len(result.presets) > 1  # built-in presets still there
