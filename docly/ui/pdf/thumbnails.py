"""Page thumbnails, drawn in the background.

Desktop concept — *one background render job*: drawing a PDF page takes
a few milliseconds to a second. Doing that for 200 pages on the UI thread
would freeze the window, so a single background job renders pages one at
a time and hands each finished picture back with a signal.

Why only one job at a time: the PDF renderer (PDFium, used by Qt's QtPdf
module) is not designed to be used from several threads at once. One job,
one queue, keeps it safe.

Pages the user can see are rendered first: the grid calls
:meth:`ThumbnailCache.request` with the visible pages at the front.
The job ends by itself when the queue is empty.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRunnable, QSize, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtPdf import QPdfDocument

from docly.core.image_io import load_image_bytes
from docly.logger import get_logger
from docly.ui.pdfium import PDFIUM_LOCK

log = get_logger(__name__)

THUMB_PX = 220  # longest side of a rendered thumbnail, in pixels
MAX_CACHED = 600  # thumbnails kept in memory (~120 KB each)

Key = tuple[int, int]  # (source index, page index)


@dataclass
class ThumbSource:
    """What the render thread needs to know about one input file."""

    data: bytes
    is_pdf: bool
    password: str | None = field(default=None, repr=False)


def render_image_thumb(data: bytes, name: str = "image") -> QImage:
    """Thumbnail of a photo (safe on any thread)."""
    loaded = load_image_bytes(data, name)
    image = loaded.image.copy()
    image.thumbnail((THUMB_PX, THUMB_PX), Image.Resampling.BILINEAR)
    rgb = image.convert("RGB")
    raw = rgb.tobytes("raw", "RGB")
    return QImage(raw, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()


def render_pdf_thumb(document: QPdfDocument, page: int) -> QImage:
    """Thumbnail of one page, on white (PDF pages are transparent by default)."""
    size = document.pagePointSize(page)  # already includes the page's own rotation
    if size.width() <= 0 or size.height() <= 0:
        return QImage()
    scale = THUMB_PX / max(size.width(), size.height())
    target = QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
    image = document.render(page, target)
    if image.isNull():
        return image
    backed = QImage(image.size(), QImage.Format.Format_RGB32)
    backed.fill(QColor("white"))
    painter = QPainter(backed)
    painter.drawImage(0, 0, image)
    painter.end()
    return backed


def rotated(image: QImage, angle: int) -> QImage:
    """``image`` turned clockwise by ``angle`` degrees (multiple of 90)."""
    if image.isNull() or angle % 360 == 0:
        return image
    return image.transformed(QTransform().rotate(angle % 360))


class _RenderSignals(QObject):
    rendered = Signal(object, object)  # key, QImage (null if it failed)
    done = Signal()


class _RenderJob(QRunnable):
    """Draws queued pages one by one until the queue is empty."""

    def __init__(self, cache: ThumbnailCache) -> None:
        super().__init__()
        self._next_job = cache._next_job  # bound method; never touches widgets
        self.signals = _RenderSignals()
        self.setAutoDelete(False)  # the cache keeps the reference

    def run(self) -> None:  # runs on a pool thread
        documents: dict[int, QPdfDocument | None] = {}
        buffers: list[QBuffer] = []
        try:
            while True:
                job = self._next_job()
                if job is None:
                    return
                key, source = job
                image = QImage()
                try:
                    if source.is_pdf:
                        with PDFIUM_LOCK:
                            if key[0] not in documents:
                                documents[key[0]] = _open_pdf(source, buffers)
                            document = documents[key[0]]
                            if document is not None and 0 <= key[1] < document.pageCount():
                                image = render_pdf_thumb(document, key[1])
                    else:
                        image = render_image_thumb(source.data)
                except Exception:  # never let one bad page stop the others
                    log.warning("Could not draw a thumbnail for %s", key, exc_info=True)
                self.signals.rendered.emit(key, image)
        finally:
            with PDFIUM_LOCK:
                for document in documents.values():
                    if document is not None:
                        document.close()
                        document.deleteLater()
            for buffer in buffers:
                buffer.close()
            self.signals.done.emit()


def _open_pdf(source: ThumbSource, buffers: list[QBuffer]) -> QPdfDocument | None:
    buffer = QBuffer()
    buffer.setData(QByteArray(source.data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    buffers.append(buffer)
    document = QPdfDocument()
    if source.password:
        document.setPassword(source.password)
    document.load(buffer)
    if document.status() != QPdfDocument.Status.Ready:
        log.info("Preview renderer could not open a PDF (%s)", document.error())
        return None
    return document


class ThumbnailCache(QObject):
    """Renders and remembers page thumbnails.

    Signals:
        thumbnailReady(object): the key ``(source, page)`` that is now available.
    """

    thumbnailReady = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sources: dict[int, ThumbSource] = {}
        self._images: OrderedDict[Key, QImage] = OrderedDict()
        self._failed: set[Key] = set()
        self._queue: list[Key] = []
        self._lock = threading.Lock()
        self._running = False
        self._stopping = False
        self._job: _RenderJob | None = None
        self._pool = QThreadPool.globalInstance()

    # ----- sources ------------------------------------------------------
    def add_source(self, index: int, source: ThumbSource) -> None:
        with self._lock:
            self._sources[index] = source

    def clear(self) -> None:
        """Forget every source and thumbnail (e.g. when starting over)."""
        with self._lock:
            self._queue.clear()
            self._sources.clear()
        self._images.clear()
        self._failed.clear()

    # ----- thumbnails -----------------------------------------------------
    def get(self, key: Key) -> QImage | None:
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
        return image

    def failed(self, key: Key) -> bool:
        return key in self._failed

    def request(self, keys: list[Key]) -> None:
        """Queue thumbnails that aren't ready yet; earlier keys come first."""
        wanted: list[Key] = []
        seen: set[Key] = set()
        for key in keys:
            if key in seen or key in self._images or key in self._failed:
                continue
            seen.add(key)
            wanted.append(key)
        if not wanted:
            return
        with self._lock:
            rest = [k for k in self._queue if k not in seen]
            self._queue = wanted + rest
        self._ensure_running()

    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def running(self) -> bool:
        return self._running

    def shutdown(self) -> None:
        """Stop rendering (the job ends after the page it is drawing)."""
        self._stopping = True
        with self._lock:
            self._queue.clear()

    # ----- internals ------------------------------------------------------
    def _ensure_running(self) -> None:
        if self._stopping or self._running:
            return
        self._running = True
        job = _RenderJob(self)
        job.signals.rendered.connect(self._on_rendered)
        job.signals.done.connect(self._on_job_done)
        self._job = job
        self._pool.start(job, -1)  # low priority: page work goes first

    def _next_job(self) -> tuple[Key, ThumbSource] | None:
        """Called on the render job's thread: the next key to draw, or None to stop."""
        with self._lock:
            while self._queue and not self._stopping:
                key = self._queue.pop(0)
                source = self._sources.get(key[0])
                if source is not None:
                    return key, source
            return None

    def _on_rendered(self, key: Key, image: QImage) -> None:
        with self._lock:
            known = key[0] in self._sources
        if not known:
            return  # cleared while it was drawing
        if image.isNull():
            self._failed.add(key)
        else:
            self._images[key] = image
            while len(self._images) > MAX_CACHED:
                self._images.popitem(last=False)
        self.thumbnailReady.emit(key)

    def _on_job_done(self) -> None:
        self._running = False
        # A request may have arrived just as the job was finishing.
        if self.pending():
            self._ensure_running()
