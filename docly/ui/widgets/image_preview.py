"""Shows an image scaled to fit, on a framed background."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from docly.ui.theme import ThemeManager, Tokens

PADDING = 12


class ImagePreview(QWidget):
    """Paints one image as large as fits, keeping its shape.

    Used for the cleaned signature: it shows the *actual output file*, on
    white like the upload will be, with a hairline so white edges are visible.
    """

    def __init__(self, theme: ThemeManager, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(240, 120))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image: QImage | None = None
        self._placeholder = placeholder
        self._tokens = theme.tokens
        theme.themeChanged.connect(self._apply_tokens)

    @property
    def image(self) -> QImage | None:
        return self._image

    def set_data(self, data: bytes) -> bool:
        """Show an encoded image (JPG/PNG bytes). Returns False if unreadable."""
        image = QImage.fromData(data)
        self._image = None if image.isNull() else image
        self.update()
        return self._image is not None

    def clear(self) -> None:
        self._image = None
        self.update()

    def image_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        avail_w = max(1.0, self.width() - 2 * PADDING)
        avail_h = max(1.0, self.height() - 2 * PADDING)
        scale = min(avail_w / self._image.width(), avail_h / self._image.height())
        w, h = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        t = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), t.qcolor("surface_alt"))
        if self._image is None:
            if self._placeholder:
                painter.setPen(t.qcolor("text_muted"))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            painter.end()
            return
        rect = self.image_rect()
        painter.drawImage(rect, self._image)
        painter.setPen(QPen(t.qcolor("border"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5))
        painter.end()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self.update()
