"""One lock for every use of QtPdf (PDFium) off the UI thread.

PDFium, the PDF engine inside QtPdf (and Chrome), keeps shared internal
state and must not be used by two threads at the same time. Any background
job that opens, renders or closes a ``QPdfDocument`` holds this lock while
doing so. The UI thread never renders PDFs itself.
"""

from __future__ import annotations

import threading

PDFIUM_LOCK = threading.RLock()
