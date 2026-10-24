"""Tests for docly.config and project metadata."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import docly
from docly import config


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", docly.__version__)
    assert config.APP_VERSION == docly.__version__


def test_pyproject_reads_version_from_package() -> None:
    pyproject = tomllib.loads((config.BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "docly.__version__"
    assert pyproject["project"]["requires-python"] == ">=3.11"


def test_assets_exist() -> None:
    assert config.ASSETS_DIR.is_dir()
    assert config.ICONS_DIR.is_dir()


def test_window_sizes_meet_design_guide() -> None:
    min_w, min_h = config.WINDOW_MIN_SIZE
    assert min_w >= 1000 and min_h >= 650
    default_w, default_h = config.WINDOW_DEFAULT_SIZE
    assert default_w >= min_w and default_h >= min_h


def test_app_data_dir_uses_override(app_data: Path) -> None:
    assert config.app_data_dir() == app_data
    assert config.log_dir() == app_data / "logs"
    assert config.settings_path() == app_data / "settings.ini"


def test_app_data_dir_uses_localappdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(config.DATA_DIR_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert config.app_data_dir() == tmp_path / "Docly"


def test_app_data_dir_fallback_without_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(config.DATA_DIR_ENV, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert config.app_data_dir() == Path.home() / ".docly"


def test_config_does_not_import_qt() -> None:
    source = Path(config.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in source
