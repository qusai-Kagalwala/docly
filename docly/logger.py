"""Logging setup: a rotating UTF-8 log file in AppData, plus the console.

Qt-free on purpose, so ``core/`` modules can log too. Logging problems
(e.g. an unwritable folder) are never allowed to crash the app.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from docly import config

LOGGER_NAME = "docly"
LOG_FILE_NAME = "docly.log"
MAX_BYTES = 1_000_000  # ~1 MB per file
BACKUP_COUNT = 5  # docly.log.1 ... docly.log.5

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(
    log_dir: Path | None = None,
    level: int = logging.INFO,
    console: bool | None = None,
) -> Path | None:
    """Configure the ``docly`` logger. Safe to call more than once.

    Args:
        log_dir: Where to write logs. Defaults to ``config.log_dir()``.
        level: Minimum level to record.
        console: Also log to stderr. Defaults to True when running from
            source and False in a packaged build.

    Returns:
        The path of the log file, or ``None`` if file logging could not be
        set up (the app keeps running either way).
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT)

    if console is None:
        console = not getattr(sys, "frozen", False)
    # A windowed .exe has no console, so sys.stderr can be None.
    if console and sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    target_dir = log_dir if log_dir is not None else config.log_dir()
    log_path: Path | None = None
    error: OSError | None = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            target_dir / LOG_FILE_NAME,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        log_path = target_dir / LOG_FILE_NAME
    except OSError as exc:
        error = exc

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    if error is not None:
        logger.warning("File logging disabled (%s): %s", target_dir, error)
    return log_path


def get_logger(name: str) -> logging.Logger:
    """Return a child of the ``docly`` logger, e.g. ``docly.ui.theme``."""
    if name == LOGGER_NAME or name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def current_log_file() -> Path | None:
    """Path of the active log file, if file logging is on."""
    for handler in logging.getLogger(LOGGER_NAME).handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return None
