"""Checks on the presets.json that ships with Docly."""

from __future__ import annotations

import pytest

from docly import config
from docly.presets import Category, Preset, load_presets
from docly.presets.models import REGION_NAMES

RESULT = load_presets(config.BUNDLED_PRESETS_PATH)
PRESETS = RESULT.presets


def test_bundled_file_has_no_issues() -> None:
    assert RESULT.issues == [], [str(i) for i in RESULT.issues]
    assert len(PRESETS) >= 15


def test_ids_are_unique() -> None:
    ids = [p.id for p in PRESETS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_id_starts_with_region(preset: Preset) -> None:
    assert preset.id.startswith(preset.region.lower() + "-")


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_region_has_a_friendly_name(preset: Preset) -> None:
    assert preset.region in REGION_NAMES


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_portal_presets_cite_an_official_source(preset: Preset) -> None:
    if preset.category == Category.GENERAL:
        return  # Docly's own general-purpose presets
    assert preset.source.startswith("https://")
    assert preset.notes


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_portal_presets_ship_unverified(preset: Preset) -> None:
    """Every portal spec must be checked against its notification by a person."""
    if preset.category != Category.GENERAL:
        assert preset.verified is False


def test_both_universal_and_india_packs_present() -> None:
    regions = {p.region for p in PRESETS}
    assert {"INTL", "IN"} <= regions
    assert any(p.kind.value == "document" for p in PRESETS if p.region == "INTL")


def test_authorities_that_forbid_edits_are_marked() -> None:
    strict = {p.id for p in PRESETS if p.no_edits}
    assert strict == {"us-visa-photo", "gb-passport-photo-online"}
