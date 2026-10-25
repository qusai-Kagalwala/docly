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


class FileTooLargeError(DoclyError):
    """A file (or the result of combining files) is over Docly's size limits."""


class ImageTooLargeError(FileTooLargeError):
    """An image file or its pixel count is over Docly's safety limits."""


class CorruptImageError(DoclyError):
    """The file looks like an image but is damaged, truncated or empty."""


class CorruptPdfError(DoclyError):
    """The PDF is damaged beyond repair, or isn't really a PDF."""


class PasswordRequiredError(DoclyError):
    """The PDF needs a password to open. ``name`` is the file's name."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is password-protected. Enter its password to open it.")
        self.name = name


class WrongPasswordError(DoclyError):
    """The password given for a PDF is not correct."""

    def __init__(self, name: str) -> None:
        super().__init__(f"That password doesn't open {name}. Check it and try again.")
        self.name = name


class InvalidPageRangeError(DoclyError):
    """Typed page numbers can't be understood or don't exist."""


class NoInkFoundError(DoclyError):
    """The signature cleaner found nothing that looks like ink."""


class CancelledError(DoclyError):
    """The user cancelled the operation."""

    def __init__(self, message: str = "Cancelled.") -> None:
        super().__init__(message)
