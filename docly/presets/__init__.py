"""Portal presets: the upload rules Docly prepares files for.

Usage::

    from docly.presets import default_presets

    result = default_presets()
    for preset in result.presets:
        print(preset.name, preset.kb_range_text)
"""

from docly.presets.loader import (
    PresetIssue,
    PresetLoadResult,
    default_presets,
    load_presets,
    merge_presets,
    parse_presets,
)
from docly.presets.models import (
    BYTES_PER_KB,
    Category,
    FileFormat,
    Preset,
    PresetKind,
    region_name,
)

__all__ = [
    "BYTES_PER_KB",
    "Category",
    "FileFormat",
    "Preset",
    "PresetIssue",
    "PresetKind",
    "PresetLoadResult",
    "default_presets",
    "load_presets",
    "merge_presets",
    "parse_presets",
    "region_name",
]
