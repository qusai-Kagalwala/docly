"""Tests for docly.logger."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from docly import logger as docly_logger


def _flush() -> None:
    for handler in logging.getLogger(docly_logger.LOGGER_NAME).handlers:
        handler.flush()


def test_creates_log_file_in_app_data(app_data: Path) -> None:
    path = docly_logger.setup_logging(console=False)
    assert path == app_data / "logs" / "docly.log"
    docly_logger.get_logger("test").info("hello")
    _flush()
    assert "hello" in path.read_text(encoding="utf-8")


def test_rotation_settings(tmp_path: Path) -> None:
    docly_logger.setup_logging(tmp_path, console=False)
    handlers = [h for h in logging.getLogger("docly").handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == docly_logger.MAX_BYTES
    assert handlers[0].backupCount == docly_logger.BACKUP_COUNT


def test_unicode_messages_and_paths(tmp_path: Path) -> None:
    folder = tmp_path / "दस्तावेज़ logs ñ"
    path = docly_logger.setup_logging(folder, console=False)
    assert path is not None
    docly_logger.get_logger("test").info("फ़ोटो.jpg – résumé €")
    _flush()
    assert "फ़ोटो.jpg – résumé €" in path.read_text(encoding="utf-8")


def test_unwritable_location_falls_back_without_crashing(tmp_path: Path) -> None:
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("a file where the log folder should be", encoding="utf-8")
    path = docly_logger.setup_logging(blocker / "logs", console=False)
    assert path is None
    docly_logger.get_logger("test").error("still fine")  # must not raise
    assert docly_logger.current_log_file() is None


def test_setup_is_idempotent(tmp_path: Path) -> None:
    docly_logger.setup_logging(tmp_path, console=False)
    docly_logger.setup_logging(tmp_path, console=False)
    file_handlers = [h for h in logging.getLogger("docly").handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1


def test_get_logger_namespaces() -> None:
    assert docly_logger.get_logger("ui.theme").name == "docly.ui.theme"
    assert docly_logger.get_logger("docly.core").name == "docly.core"
    assert docly_logger.get_logger("docly").name == "docly"
