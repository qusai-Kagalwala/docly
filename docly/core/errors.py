"""Errors raised by the core engine.

Every message is written for the person using Docly, so the UI can show
``str(error)`` directly without translating technical jargon.
"""

from __future__ import annotations


class DoclyError(Exception):
    """Base class for all expected, user-facing problems."""


class FileAccessError(DoclyError):
    """The file could not be read (missing, locked, no permission)."""


class UnsupportedFormatError(DoclyError):
    """The file is not an image type Docly can open."""


class ImageTooLargeError(DoclyError):
    """The file or its pixel count is over Docly's safety limits."""


class CorruptImageError(DoclyError):
    """The file looks like an image but is damaged, truncated or empty."""


class NoInkFoundError(DoclyError):
    """The signature cleaner found nothing that looks like ink."""


class CancelledError(DoclyError):
    """The user cancelled the operation."""

    def __init__(self, message: str = "Cancelled.") -> None:
        super().__init__(message)
