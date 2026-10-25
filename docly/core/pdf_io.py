"""Open PDFs safely and save clean copies.

Every PDF is untrusted. Opening checks the size, the real file type and the
page count; damaged files are repaired when possible (with a warning);
password-protected files need their password. Docly never guesses or
bypasses a password.

Saved output is deliberately plain: no password, no document-level scripts
or auto-run actions, no attachments and no author/creator metadata.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from pikepdf import Name

from docly.core.errors import (
    CorruptPdfError,
    FileTooLargeError,
    PasswordRequiredError,
    WrongPasswordError,
)
from docly.core.files import read_bytes
from docly.logger import get_logger

log = get_logger(__name__)

MAX_PDF_BYTES = 200 * 1024 * 1024  # 200 MB per input file
MAX_PAGES = 2000  # per input file
MAX_OUTPUT_BYTES = 500 * 1024 * 1024  # 500 MB per output file
HEADER_WINDOW = 1024  # "%PDF-" must appear in the first KB

REPAIRED_WARNING = "{name} was damaged and has been repaired. Check its pages before uploading."

# Page and annotation keys that can run or launch something.
_ACTION_KEYS = (Name.AA,)
_DANGEROUS_ACTIONS = {Name.JavaScript, Name.Launch, Name.ImportData, Name.SubmitForm, Name.ResetForm}


@dataclass
class OpenedPdf:
    """An open PDF plus facts about it. Close with :meth:`close`."""

    pdf: pikepdf.Pdf
    name: str
    size_bytes: int
    encrypted: bool  # it had a password or restrictions (outputs won't)
    repaired: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pdf.pages)

    def page_size(self, index: int) -> tuple[float, float]:
        """Displayed width × height in points (1/72 inch), rotation applied."""
        page = self.pdf.pages[index]
        box = page.mediabox
        width = float(box[2]) - float(box[0])
        height = float(box[3]) - float(box[1])
        rotate = int(page.obj.get(Name.Rotate, 0)) % 360
        return (height, width) if rotate in (90, 270) else (width, height)

    def close(self) -> None:
        self.pdf.close()


def is_pdf(data: bytes) -> bool:
    """True if ``data`` starts like a PDF (allowing a little junk first)."""
    return b"%PDF-" in data[:HEADER_WINDOW]


def open_pdf(path: Path, password: str | None = None) -> OpenedPdf:
    """Open a PDF file safely. Raises a :class:`DoclyError` subclass."""
    data = read_bytes(path, MAX_PDF_BYTES)
    return open_pdf_bytes(data, path.name, password)


def open_pdf_bytes(data: bytes, name: str = "document.pdf", password: str | None = None) -> OpenedPdf:
    """Open PDF bytes safely (same rules as :func:`open_pdf`)."""
    if not data:
        raise CorruptPdfError(f"{name} is empty (0 bytes).")
    if len(data) > MAX_PDF_BYTES:
        raise FileTooLargeError(f"{name} is larger than {MAX_PDF_BYTES // 1_048_576} MB, Docly's limit for PDFs.")
    if not is_pdf(data):
        raise CorruptPdfError(f"{name} isn't a PDF file.")

    try:
        pdf = pikepdf.open(io.BytesIO(data), password=password or "")
    except pikepdf.PasswordError:
        if password:
            raise WrongPasswordError(name) from None
        raise PasswordRequiredError(name) from None
    except (pikepdf.PdfError, ValueError, RuntimeError):
        raise CorruptPdfError(f"{name} is damaged and can't be repaired.") from None
    except MemoryError:
        raise FileTooLargeError(f"{name} is too large to open with the memory available.") from None

    try:
        count = len(pdf.pages)
    except Exception:
        pdf.close()
        raise CorruptPdfError(f"{name} is damaged and its pages can't be read.") from None
    if count == 0:
        pdf.close()
        raise CorruptPdfError(f"{name} has no pages.")
    if count > MAX_PAGES:
        pdf.close()
        raise FileTooLargeError(f"{name} has {count:,} pages; Docly's limit is {MAX_PAGES:,}.")

    repaired = bool(pdf.get_warnings())
    warnings = [REPAIRED_WARNING.format(name=name)] if repaired else []
    if repaired:
        log.info("Repaired damaged PDF %s: %s", name, pdf.get_warnings()[:3])
    return OpenedPdf(pdf, name, len(data), pdf.is_encrypted, repaired, warnings)


def sanitize_page(page: pikepdf.Page) -> int:
    """Remove things on a page that could run or launch something.

    Drops the page's own automatic actions, JavaScript/launch/form-submit
    actions on links, and file-attachment annotations. Returns how many
    items were removed.
    """
    removed = 0
    obj = page.obj
    for key in _ACTION_KEYS:
        if key in obj:
            del obj[key]
            removed += 1
    annots = obj.get(Name.Annots)
    if annots is None:
        return removed
    kept = pikepdf.Array()
    for annot in annots:
        try:
            if annot.get(Name.Subtype) == Name.FileAttachment:
                removed += 1
                continue
            for key in _ACTION_KEYS:
                if key in annot:
                    del annot[key]
                    removed += 1
            action = annot.get(Name.A)
            if action is not None and action.get(Name.S) in _DANGEROUS_ACTIONS:
                del annot[Name.A]
                removed += 1
        except (AttributeError, TypeError, pikepdf.PdfError):
            removed += 1  # malformed annotation: drop it
            continue
        kept.append(annot)
    obj[Name.Annots] = kept
    return removed


def save_pdf(pdf: pikepdf.Pdf) -> bytes:
    """Serialise a PDF built by Docly: no password, no metadata, compact.

    Raises :class:`FileTooLargeError` if the result is unreasonably big.
    """
    if Name.Info in pdf.trailer:
        del pdf.trailer[Name.Info]
    if Name.Metadata in pdf.Root:
        del pdf.Root[Name.Metadata]
    buffer = io.BytesIO()
    pdf.save(
        buffer,
        encryption=False,  # never carry a password into Docly's output
        object_stream_mode=pikepdf.ObjectStreamMode.generate,  # smaller files
        compress_streams=True,
        deterministic_id=True,
    )
    data = buffer.getvalue()
    if len(data) > MAX_OUTPUT_BYTES:
        raise FileTooLargeError(
            f"The result would be {len(data) / 1_048_576:.0f} MB, over Docly's "
            f"{MAX_OUTPUT_BYTES // 1_048_576} MB limit. Use fewer or smaller files."
        )
    return data
