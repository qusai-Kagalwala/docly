"""Drag-and-drop area that also opens a file picker when clicked."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout, QWidget

from docly.ui.icons import render_icon
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.style import set_style_prop

#: Extensions offered in the file picker and accepted on drop. HEIC is
#: accepted so the loader can explain how to convert it.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif")
FILE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *.heic *.heif);;All files (*)"
MULTIPLE_FILES_TIP = "Docly opened the first file. To prepare many files at once, use Batch mode."


def paths_from_mime(mime: QMimeData) -> list[Path]:
    """Local file paths carried by a drag (ignores web links)."""
    if not mime.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and url.toLocalFile()]


def pick_dropped_image(mime: QMimeData) -> tuple[Path | None, str | None]:
    """Choose the image to open from a drop.

    Returns ``(path, message)``: ``path`` is None if nothing usable was
    dropped, and ``message`` explains a rejection or gives the multi-file tip.
    """
    paths = paths_from_mime(mime)
    if not paths:
        return None, "Drop a photo file from your computer."
    images = [p for p in paths if p.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        return None, f"{paths[0].name} isn't a photo. Use JPG, PNG, WebP, BMP, TIFF or GIF."
    return images[0], (MULTIPLE_FILES_TIP if len(paths) > 1 else None)


def ask_open_image(parent: QWidget, start_dir: str = "") -> Path | None:
    """Show the Windows file picker; ``None`` if the user cancels."""
    file_name, _ = QFileDialog.getOpenFileName(parent, "Choose a photo", start_dir, FILE_FILTER)
    return Path(file_name) if file_name else None


class DropZone(QFrame):
    """Large dashed target: "Drop a photo here or click to browse".

    Signals:
        fileChosen(object): a ``Path`` to open.
        message(str): something to tell the user (rejection or tip).
    """

    fileChosen = Signal(object)
    message = Signal(str)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(260)
        self.setAccessibleName("Drop a photo here or click to browse")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        title = QLabel("Drop a photo here")
        title.setProperty("role", "section")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("or click to browse · JPG, PNG, WebP, BMP, TIFF, GIF")
        hint.setProperty("role", "muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        privacy = QLabel("Your photo stays on this computer.")
        privacy.setProperty("role", "caption")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(privacy)
        layout.addStretch(1)

        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    @property
    def active(self) -> bool:
        return self.property("active") == "true"

    def browse(self) -> None:
        """Open the file picker."""
        path = ask_open_image(self)
        if path is not None:
            self.fileChosen.emit(path)

    # ----- events -----------------------------------------------------
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.browse()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.browse()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            set_style_prop(self, "active", "true")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        set_style_prop(self, "active", None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        set_style_prop(self, "active", None)
        path, note = pick_dropped_image(event.mimeData())
        event.acceptProposedAction()
        if note:
            self.message.emit(note)
        if path is not None:
            self.fileChosen.emit(path)

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._icon.setPixmap(render_icon("image", tokens.accent, 44, self.devicePixelRatioF()))
