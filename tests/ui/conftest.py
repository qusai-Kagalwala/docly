"""Fixtures for UI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool

from docly import config
from docly.presets import PresetLoadResult, load_presets
from tests.core import images


@pytest.fixture(autouse=True)
def _finish_background_jobs():
    """Let worker threads finish before the next test starts."""
    yield
    QThreadPool.globalInstance().waitForDone(10_000)


@pytest.fixture(scope="session")
def bundled_presets() -> PresetLoadResult:
    return load_presets(config.BUNDLED_PRESETS_PATH)


@pytest.fixture
def photo_file(tmp_path: Path) -> Path:
    return images.save(images.photo_like(1200, 1600), tmp_path / "my photo.jpg", "JPEG", quality=90)
