"""Result card for the PDF page: create, progress/cancel, then save.

One result → Save / Save as… / Open folder.
Several results (a split) → Save all / Save to folder… / Open folder;
"Save all" puts them in ``Docly_Output\\<name>_split\\`` so a 40-page
split doesn't scatter 40 files among your other outputs.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from docly.core.errors import FileAccessError
from docly.core.files import write_file, write_new_file
from docly.core.pdf_ops import PdfResult
from docly.logger import get_logger
from docly.ui import desktop
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.style import set_style_prop

log = get_logger(__name__)


def format_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def save_with_fallback(folder: Path, results: list[PdfResult]) -> tuple[list[Path], str]:
    """Write every result into ``folder`` (never overwriting).

    If ``folder`` can't be written to, uses ``Pictures\\Docly_Output``
    instead (keeping any ``_split`` subfolder name). Returns the paths and
    a note for the user. Raises :class:`FileAccessError` if both fail.
    """
    try:
        return [write_new_file(folder, r.suggested_name, r.data) for r in results], ""
    except FileAccessError as first_error:
        log.info("Output folder not writable (%s); using Pictures", first_error)
    fallback = desktop.pictures_output_folder()
    if folder.name != desktop.OUTPUT_FOLDER_NAME:
        fallback = fallback / folder.name
    return (
        [write_new_file(fallback, r.suggested_name, r.data) for r in results],
        " (the original's folder is read-only)",
    )


class PdfResultCard(Card):
    """Signals:
    createRequested(): the user clicked the main "Create PDF" button.
    cancelRequested(): the user clicked Cancel while working.
    saved(object): list of ``Path`` written.
    """

    createRequested = Signal()
    cancelRequested = Signal()
    saved = Signal(object)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.body.setSpacing(10)
        self._results: list[PdfResult] = []
        self._source: Path | None = None
        self._split = False
        self.saved_paths: list[Path] = []

        status = QHBoxLayout()
        status.setSpacing(12)
        self.mark = QLabel()
        self.mark.setObjectName("StatusMark")
        status.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("StatusTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        status.addLayout(text, 1)
        self.body.addLayout(status)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.cancel_button = QPushButton("Cancel")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        self.body.addLayout(progress_row)

        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.body.addWidget(self.notes)

        self.saved_label = QLabel()
        self.saved_label.setProperty("role", "caption")
        self.saved_label.setWordWrap(True)
        self.saved_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.saved_label)

        self.create_button = QPushButton("Create PDF")
        self.create_button.setProperty("variant", "primary")
        self.create_button.setToolTip("Build one PDF from the pages, in this order")
        self.body.addWidget(self.create_button)

        # Save gets its own full-width row: split results use longer labels
        # ("Save all", "Save to folder…") and the side column is narrow.
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("variant", "primary")
        self.body.addWidget(self.save_button)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.save_as_button = QPushButton("Save as…")
        self.reveal_button = QPushButton("Open folder")
        self.reveal_button.setToolTip("Show the saved file in File Explorer")
        buttons.addWidget(self.save_as_button, 1)
        buttons.addWidget(self.reveal_button, 1)
        self.body.addLayout(buttons)

        self.create_button.clicked.connect(self.createRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self.reveal_button.clicked.connect(self.reveal)
        self.show_idle("Add PDFs or photos to begin.", can_create=False)

    # ----- states -----------------------------------------------------
    @property
    def results(self) -> list[PdfResult]:
        return list(self._results)

    def show_idle(self, message: str, can_create: bool = True) -> None:
        self._results = []
        self.saved_paths = []
        self._set_status("", "Output", message, None)
        self._show_progress(False)
        self.notes.hide()
        self.saved_label.hide()
        self.create_button.show()
        self.create_button.setEnabled(can_create)
        self._show_save_buttons(False)

    def show_busy(self, text: str = "Building your PDF…") -> None:
        self._set_status("⏳", "Working…", text, None)
        self.progress.setRange(0, 0)
        self._show_progress(True)
        self.notes.hide()
        self.saved_label.hide()
        self.create_button.hide()
        self._show_save_buttons(False)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def show_error(self, message: str) -> None:
        self._results = []
        self._set_status("❌", "Couldn't create the PDF", message, "fail")
        self._show_progress(False)
        self.notes.hide()
        self.saved_label.hide()
        self.create_button.show()
        self.create_button.setEnabled(True)
        self._show_save_buttons(False)

    def show_results(self, results: list[PdfResult], source: Path, split: bool = False) -> None:
        self._results = list(results)
        self._source = source
        self._split = split
        self.saved_paths = []
        total = sum(r.size_bytes for r in results)
        if split:
            title = f"{len(results)} PDFs ready"
            summary = f"{sum(r.page_count for r in results)} pages in total · {format_size(total)}"
        else:
            result = results[0]
            title = "PDF ready"
            pages = f"{result.page_count} page" + ("" if result.page_count == 1 else "s")
            summary = f"{result.suggested_name} · {pages} · {format_size(total)}"
        self._set_status("✅", title, summary, "pass")
        self._show_progress(False)
        warnings = sorted({w for r in results for w in r.warnings})
        self.notes.setText("\n".join(f"⚠ {w}" for w in warnings))
        set_style_prop(self.notes, "banner", "warning" if warnings else None)
        self.notes.setVisible(bool(warnings))
        self.saved_label.hide()
        self.create_button.hide()
        self.save_button.setText("Save all" if split else "Save")
        self.save_as_button.setText("Save to folder…" if split else "Save as…")
        tip = f"Save into Docly_Output\\{self.split_folder_name()}" if split else "Save into Docly_Output next to the original"
        self.save_button.setToolTip(tip)
        self._show_save_buttons(True)
        self.reveal_button.setEnabled(False)

    # ----- saving -----------------------------------------------------
    def split_folder_name(self) -> str:
        if not self._results:
            return ""
        first = self._results[0].suggested_name
        stem = first.rsplit("_pages-", 1)[0] if "_pages-" in first else first.rsplit(".", 1)[0]
        return f"{stem}_split"

    def default_folder(self) -> Path | None:
        if self._source is None:
            return None
        folder = desktop.output_folder_for(self._source)
        return folder / self.split_folder_name() if self._split else folder

    def save(self) -> list[Path]:
        """Save into ``Docly_Output`` (a ``_split`` subfolder for splits)."""
        folder = self.default_folder()
        if not self._results or folder is None:
            return []
        try:
            paths, note = save_with_fallback(folder, self._results)
        except FileAccessError as exc:
            self._show_saved([], str(exc))
            return []
        where = paths[0] if len(paths) == 1 else paths[0].parent
        self._show_saved(paths, f"Saved {len(paths)} files to {where}{note}" if len(paths) > 1 else f"Saved to {where}{note}")
        return paths

    def save_as(self) -> list[Path]:
        if not self._results or self._source is None:
            return []
        start = desktop.output_folder_for(self._source)
        if not start.exists():
            start = self._source.parent
        if self._split:
            folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the PDFs", str(start))
            if not folder:
                return []
            try:
                paths = [write_new_file(Path(folder), r.suggested_name, r.data) for r in self._results]
            except FileAccessError as exc:
                self._show_saved([], str(exc))
                return []
            self._show_saved(paths, f"Saved {len(paths)} files to {folder}")
            return paths
        name, _ = QFileDialog.getSaveFileName(
            self, "Save as", str(start / self._results[0].suggested_name), "PDF document (*.pdf)"
        )
        if not name:
            return []
        path = Path(name) if Path(name).suffix else Path(name).with_suffix(".pdf")
        try:
            write_file(path, self._results[0].data)
        except FileAccessError as exc:
            self._show_saved([], str(exc))
            return []
        self._show_saved([path], f"Saved to {path}")
        return [path]

    def reveal(self) -> None:
        if self.saved_paths:
            desktop.reveal_in_folder(self.saved_paths[0])

    # ----- helpers ----------------------------------------------------
    def _show_saved(self, paths: list[Path], message: str) -> None:
        self.saved_paths = list(paths)
        self.saved_label.setText(message)
        set_style_prop(self.saved_label, "banner", None if paths else "danger")
        set_style_prop(self.saved_label, "role", "caption" if paths else None)
        self.saved_label.show()
        self.reveal_button.setEnabled(bool(paths))
        if paths:
            log.info("Saved %d PDF(s) to %s", len(paths), paths[0].parent)
            self.saved.emit(list(paths))

    def _set_status(self, mark: str, title: str, subtitle: str, state: str | None) -> None:
        self.mark.setText(mark)
        self.mark.setVisible(bool(mark))
        self.title.setText(title)
        set_style_prop(self.title, "state", state)
        self.subtitle.setText(subtitle)

    def _show_progress(self, visible: bool) -> None:
        self.progress.setVisible(visible)
        self.cancel_button.setVisible(visible)

    def _show_save_buttons(self, visible: bool) -> None:
        for button in (self.save_button, self.save_as_button, self.reveal_button):
            button.setVisible(visible)
