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


def ask_open_files(parent: QWidget, title: str, file_filter: str, start_dir: str = "") -> list[Path]:
    """File picker that allows choosing several files; empty if cancelled."""
    names, _ = QFileDialog.getOpenFileNames(parent, title, start_dir, file_filter)
    return [Path(name) for name in names]


def ask_open_image(parent: QWidget, start_dir: str = "") -> Path | None:
    """Show the Windows file picker; ``None`` if the user cancels."""
    file_name, _ = QFileDialog.getOpenFileName(parent, "Choose a photo", start_dir, FILE_FILTER)
    return Path(file_name) if file_name else None


class DropZone(QFrame):
    """Large dashed target: "Drop a photo here or click to browse".

    By default it opens one photo. With ``multiple=True`` it accepts any
    number of files and emits them all through :attr:`filesChosen` (the
    page decides which ones it can use).

    Signals:
        fileChosen(object): a ``Path`` to open (single-file mode).
        filesChosen(object): a list of ``Path`` (multiple-file mode).
        message(str): something to tell the user (rejection or tip).
    """

    fileChosen = Signal(object)
    filesChosen = Signal(object)
    message = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        parent: QWidget | None = None,
        *,
        title: str = "Drop a photo here",
        hint: str = "or click to browse · JPG, PNG, WebP, BMP, TIFF, GIF",
        privacy: str = "Your photo stays on this computer.",
        icon: str = "image",
        multiple: bool = False,
        file_filter: str = FILE_FILTER,
        picker_title: str = "Choose a photo",
    ) -> None:
        super().__init__(parent)
        self.multiple = multiple
        self._icon_name = icon
        self._file_filter = file_filter
        self._picker_title = picker_title
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(260)
        self.setAccessibleName(f"{title} or click to browse")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        for text, role in ((title, "section"), (hint, "muted"), (privacy, "caption")):
            label = QLabel(text)
            label.setProperty("role", role)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)

        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    @property
    def active(self) -> bool:
        return self.property("active") == "true"

    def browse(self) -> None:
        """Open the file picker."""
        if self.multiple:
            paths = ask_open_files(self, self._picker_title, self._file_filter)
            if paths:
                self.filesChosen.emit(paths)
            return
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
        if self.multiple:
            event.acceptProposedAction()
            paths = paths_from_mime(event.mimeData())
            if paths:
                self.filesChosen.emit(paths)
            return
        path, note = pick_dropped_image(event.mimeData())
        event.acceptProposedAction()
        if note:
            self.message.emit(note)
        if path is not None:
            self.fileChosen.emit(path)

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._icon.setPixmap(render_icon(self._icon_name, tokens.accent, 44, self.devicePixelRatioF()))
