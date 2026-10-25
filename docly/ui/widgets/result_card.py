"""Result card: a status icon, the checks, a preview, and Save / Save as / Show in folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from docly.core.errors import FileAccessError
from docly.core.files import write_file, write_new_file
from docly.core.pipeline import ProcessResult
from docly.core.validate import Check
from docly.logger import get_logger
from docly.ui import desktop, motion
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.image_preview import ImagePreview
from docly.ui.widgets.status_badge import IconText, StatusIcon
from docly.ui.widgets.style import set_style_prop

log = get_logger(__name__)

PREVIEW_SIZE = QSize(96, 96)


def ask_save_path(parent: QWidget, suggested: Path, extension: str) -> Path | None:
    """Windows "Save as" dialog. It asks before replacing an existing file."""
    file_filter = f"{extension.upper()} image (*.{extension})"
    name, _ = QFileDialog.getSaveFileName(parent, "Save as", str(suggested), file_filter)
    if not name:
        return None
    path = Path(name)
    return path if path.suffix else path.with_suffix(f".{extension}")


class ResultCard(Card):
    """Shows the outcome of processing and saves the file.

    Signals:
        saved(object): the ``Path`` the file was written to.
    """

    saved = Signal(object)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.body.setSpacing(10)
        self._result: ProcessResult | None = None
        self._source: Path | None = None
        self.saved_path: Path | None = None

        self._theme = theme
        self.status_row = QWidget()
        status = QHBoxLayout(self.status_row)
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(12)
        self.mark = StatusIcon(theme)
        status.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("StatusTitle")
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        status.addLayout(text, 1)
        self.body.addWidget(self.status_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # "busy" animation
        self.progress.setTextVisible(False)
        self.body.addWidget(self.progress)

        content = QHBoxLayout()
        content.setSpacing(12)
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(4)
        content.addLayout(self.checks_box, 1)
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("OutputPreview")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(6, 6, 6, 6)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(PREVIEW_SIZE)
        preview_layout.addWidget(self.preview)
        content.addWidget(self.preview_frame, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(content)

        self.notes = QLabel()
        self.notes.setProperty("role", "caption")
        self.notes.setWordWrap(True)
        self.body.addWidget(self.notes)

        self.saved_label = QLabel()
        self.saved_label.setProperty("role", "caption")
        self.saved_label.setWordWrap(True)
        self.saved_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.saved_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("variant", "primary")
        self.save_button.setToolTip("Save into a Docly_Output folder next to the original")
        self.save_as_button = QPushButton("Save as…")
        self.reveal_button = QPushButton("Open folder")
        self.reveal_button.setToolTip("Show the saved file in File Explorer")
        for button in (self.save_button, self.save_as_button, self.reveal_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.body.addLayout(buttons)

        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self.reveal_button.clicked.connect(self.reveal)
        self.show_idle()

    # ----- states -----------------------------------------------------
    def show_idle(self, message: str = "Add a photo to see if it's ready to upload.") -> None:
        self._result = None
        self._set_status("", "Waiting for a photo", message, None)
        self.progress.hide()
        self._clear_details()
        self._set_buttons(False)

    def show_busy(self) -> None:
        self._set_status("working", "Preparing…", "Cropping, resizing and compressing.", None)
        self.progress.show()
        self._set_buttons(False)

    def show_error(self, message: str) -> None:
        self._result = None
        self._set_status("danger", "Couldn't process this photo", message, "fail")
        self.progress.hide()
        self._clear_details()
        self._set_buttons(False)

    def show_result(self, result: ProcessResult, source: Path) -> None:
        self._result = result
        self._source = source
        self.saved_path = None
        self.saved_label.hide()
        self.progress.hide()
        c = result.compression
        summary = f"{result.size_bytes / 1024:.1f} KB · {c.width} × {c.height} px"
        if c.quality is not None:
            summary += f" · quality {c.quality}"
        if result.passed:
            self._set_status("success", "Ready to upload", summary, "pass")
        else:
            self._set_status("danger", "Needs attention", summary, "fail")
        self._show_checks(result.report.checks)
        self.notes.setText("\n".join(result.notes))
        self.notes.setVisible(bool(result.notes))
        self._show_preview(result.data)
        self.save_button.setEnabled(True)
        self.save_as_button.setEnabled(True)
        self.reveal_button.setEnabled(False)

    # ----- actions ----------------------------------------------------
    def save(self) -> Path | None:
        """Save into ``Docly_Output`` next to the original (never overwrites).

        If that folder can't be written to, falls back to
        ``Pictures\\Docly_Output`` and says so.
        """
        if self._result is None or self._source is None:
            return None
        name = self._result.suggested_name
        try:
            path = write_new_file(desktop.output_folder_for(self._source), name, self._result.data)
            note = ""
        except FileAccessError as first_error:
            log.info("Default output folder not writable (%s); using Pictures", first_error)
            try:
                path = write_new_file(desktop.pictures_output_folder(), name, self._result.data)
                note = " (Docly couldn't write to the usual folder)"
            except FileAccessError as exc:
                self._show_saved(None, str(exc))
                return None
        self._show_saved(path, f"Saved to {path}{note}")
        return path

    def save_as(self) -> Path | None:
        if self._result is None or self._source is None:
            return None
        suggested = desktop.output_folder_for(self._source) / self._result.suggested_name
        if not suggested.parent.exists():
            suggested = self._source.parent / self._result.suggested_name
        path = ask_save_path(self, suggested, self._result.format.value)
        if path is None:
            return None
        try:
            write_file(path, self._result.data)
        except FileAccessError as exc:
            self._show_saved(None, str(exc))
            return None
        self._show_saved(path, f"Saved to {path}")
        return path

    def reveal(self) -> None:
        if self.saved_path is not None:
            desktop.reveal_in_folder(self.saved_path)

    # ----- helpers ----------------------------------------------------
    def _show_saved(self, path: Path | None, message: str) -> None:
        self.saved_path = path
        self.saved_label.setText(message)
        set_style_prop(self.saved_label, "banner", None if path else "danger")
        set_style_prop(self.saved_label, "role", "caption" if path else None)
        self.saved_label.show()
        self.reveal_button.setEnabled(path is not None)
        if path is not None:
            log.info("Saved %s", path)
            self.saved.emit(path)

    def _set_status(self, kind: str, title: str, subtitle: str, state: str | None) -> None:
        """``kind`` picks the icon tile: success, warning, danger, working or "" (none)."""
        changed = kind != self.mark.kind or title != self.title.text()
        self.mark.set_kind(kind)
        self.title.setText(title)
        if changed and state is not None:
            motion.fade_in(self.status_row, motion.FAST_MS)
        set_style_prop(self.title, "state", state)
        self.subtitle.setText(subtitle)

    def _set_buttons(self, enabled: bool) -> None:
        self.save_button.setEnabled(enabled)
        self.save_as_button.setEnabled(enabled)
        self.reveal_button.setEnabled(enabled and self.saved_path is not None)

    def _clear_details(self) -> None:
        self._show_checks(())
        self.notes.hide()
        self.saved_label.hide()
        self.preview.clear()
        self.preview_frame.hide()

    def _show_checks(self, checks: tuple[Check, ...] | tuple[()]) -> None:
        while self.checks_box.count():
            item = self.checks_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for check in checks:
            actual = check.actual.split(" (")[0]  # "48.2 KB (49,357 bytes)" -> "48.2 KB"
            row = IconText(self._theme, check_kind(check), f"{check.name}: {actual}")
            row.setToolTip(f"{check.actual}\nExpected {check.expected}")
            self.checks_box.addWidget(row)
        self.checks_box.addStretch(1)

    def _show_preview(self, data: bytes) -> None:
        image = QImage.fromData(data)
        if image.isNull():
            self.preview_frame.hide()
            return
        pixmap = QPixmap.fromImage(image).scaled(
            PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        if image.hasAlphaChannel():
            # Show see-through areas on a light checkerboard, not the card colour,
            # so dark ink stays visible in dark mode.
            backed = QPixmap(pixmap.size())
            painter = QPainter(backed)
            ImagePreview.paint_checkerboard(painter, QRectF(backed.rect()))
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            pixmap = backed
        self.preview.setPixmap(pixmap)
        self.preview_frame.show()


def check_kind(check: Check) -> str:
    """success, danger (blocks the upload) or warning (worth a look)."""
    if check.passed:
        return "success"
    return "danger" if check.blocking else "warning"
