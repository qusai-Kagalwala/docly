"""Batch page: one preset (or size limit) applied to many files at once.

Flow:
    choose Photos / Signatures / PDFs → add files → pick preset & options
    Start → each file is processed in the background, the table fills in
    → summary, Open folder, Open report (Docly report.csv)

Each file is handled on its own, so one bad file never stops the rest.
Originals are never changed.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from docly.core.background import model_available
from docly.core.batch import MAX_FILES, BatchKind, BatchReport, BatchSettings, ItemResult, Status, batch_folder, run_batch
from docly.core.errors import DoclyError
from docly.core.signature import CleanOptions
from docly.logger import get_logger
from docly.presets import PresetLoadResult, default_presets
from docly.presets.models import PresetKind
from docly.ui import desktop
from docly.ui.pages.base_page import BasePage, SideColumn
from docly.ui.pdf.compress_card import CompressCard
from docly.ui.theme import ThemeManager
from docly.ui.widgets.background_card import BackgroundCard
from docly.ui.widgets.card import Card
from docly.ui.widgets.drop_zone import IMAGE_EXTENSIONS, DropZone, ask_open_files, paths_from_mime
from docly.ui.widgets.preset_picker import PresetPicker
from docly.ui.widgets.segmented import SegmentedControl
from docly.ui.widgets.status_badge import Banner, StatusDelegate
from docly.ui.widgets.style import set_style_prop
from docly.ui.workers import TaskRunner

log = get_logger(__name__)

SIDE_WIDTH = 320
IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *.heic *.heif);;All files (*)"
PDF_FILTER = "PDF documents (*.pdf);;All files (*)"
STATUS_TEXT = {
    Status.READY: "Ready",
    Status.CHECK: "Check",
    Status.FAILED: "Failed",
    Status.NOT_DONE: "Not done",
}
WAITING, WORKING = "Waiting", "Working…"
#: Status words → capsule kind (Waiting and Not done stay plain, muted words).
STATUS_KIND = {
    STATUS_TEXT[Status.READY]: "success",
    STATUS_TEXT[Status.CHECK]: "warning",
    STATUS_TEXT[Status.FAILED]: "danger",
    WORKING: "working",
}
COLUMNS = ("File", "Status", "Result", "Notes")


class _Relay(QObject):
    """Carries per-file results from the worker thread to the UI thread."""

    item = Signal(int, object)


class BatchPage(BasePage):
    PAGE_ID = "batch"
    TITLE = "Batch"
    SUBTITLE = "Apply one preset to many files at once."
    ICON = "layers"
    SCROLLS = False

    def __init__(
        self,
        theme: ThemeManager,
        presets: PresetLoadResult | None = None,
        region: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(theme, parent)
        self.setAcceptDrops(True)
        presets = presets if presets is not None else default_presets()
        self.files: list[Path] = []
        self.report: BatchReport | None = None
        self._stop = threading.Event()
        self._relay = _Relay(self)
        self.runner = TaskRunner(parent=self)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.content.addLayout(columns, 1)

        # ----- left: mode, files ------------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(10)
        columns.addLayout(left, 1)
        top = QHBoxLayout()
        self.mode = SegmentedControl(
            [(BatchKind.PHOTO.value, "Photos"), (BatchKind.SIGNATURE.value, "Signatures"), (BatchKind.PDF.value, "PDFs")]
        )
        self.mode.set_value(BatchKind.PHOTO.value)
        self.add_button = QPushButton("Add files…")
        self.clear_button = QPushButton("Clear")
        top.addWidget(self.mode)
        top.addStretch(1)
        top.addWidget(self.add_button)
        top.addWidget(self.clear_button)
        left.addLayout(top)

        self.banner = Banner(theme)
        left.addWidget(self.banner)

        self.stack = QStackedWidget()
        self.drop_zone = DropZone(
            theme,
            title="Drop many files here",
            hint="or click to browse · all photos, all signatures, or all PDFs",
            privacy="Your files stay on this computer. Originals are never changed.",
            icon="layers",
            multiple=True,
            file_filter=IMAGE_FILTER,
            picker_title="Choose files",
        )
        self.table_card = Card(theme)
        self.table_card.body.setContentsMargins(10, 10, 10, 10)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(1, StatusDelegate(theme, STATUS_KIND, self.table))
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table_card.body.addWidget(self.table, 1)
        tip = QLabel("Select rows and press Delete to remove them before starting.")
        tip.setProperty("role", "caption")
        self.table_card.body.addWidget(tip)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.table_card)
        left.addWidget(self.stack, 1)

        self.count_label = QLabel()
        self.count_label.setProperty("role", "caption")
        left.addWidget(self.count_label)

        # ----- right: preset, options, run --------------------------------------------
        self.side_scroll = SideColumn(SIDE_WIDTH + 14)
        self.side = self.side_scroll.column
        columns.addWidget(self.side_scroll)

        self.preset_card = Card(theme)
        heading = QLabel("Preset")
        heading.setProperty("role", "section")
        self.preset_card.body.addWidget(heading)
        self.photo_picker = PresetPicker(presets.presets, kinds=(PresetKind.PHOTO, PresetKind.IMAGE), region=region)
        self.sign_picker = PresetPicker(presets.presets, kinds=(PresetKind.SIGNATURE, PresetKind.IMAGE), region=region)
        self.preset_card.body.addWidget(self.photo_picker)
        self.preset_card.body.addWidget(self.sign_picker)
        self.side.addWidget(self.preset_card)

        # Photos: framing + background.
        self.photo_options = Card(theme)
        heading = QLabel("Cropping")
        heading.setProperty("role", "section")
        self.photo_options.body.addWidget(heading)
        self.frame_person = QCheckBox("Frame the person")
        self.frame_person.setChecked(True)
        self.frame_person.setToolTip(
            "Finds the person and keeps space above their head, instead of cutting the middle out. "
            "Photos where it has to guess are marked Check."
        )
        self.frame_person.setEnabled(model_available())
        self.photo_options.body.addWidget(self.frame_person)
        self.side.addWidget(self.photo_options)
        self.background_card = BackgroundCard(theme, available=model_available())
        self.side.addWidget(self.background_card)

        # Signatures: ink.
        self.sign_options = Card(theme)
        heading = QLabel("Cleaning")
        heading.setProperty("role", "section")
        self.sign_options.body.addWidget(heading)
        self.black_ink = QCheckBox("Make ink black")
        self.sign_options.body.addWidget(self.black_ink)
        self.side.addWidget(self.sign_options)

        # PDFs: size limit.
        self.compress_card = CompressCard(theme, presets.presets, region)
        self.side.addWidget(self.compress_card)

        # Run.
        self.run_card = Card(theme)
        self.summary = QLabel("Add files to begin.")
        self.summary.setObjectName("StatusTitle")
        self.summary.setWordWrap(True)
        self.run_card.body.addWidget(self.summary)
        self.detail = QLabel()
        self.detail.setProperty("role", "caption")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.run_card.body.addWidget(self.detail)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.cancel_button = QPushButton("Cancel")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        self.run_card.body.addLayout(progress_row)
        self.start_button = QPushButton("Start")
        self.start_button.setProperty("variant", "primary")
        self.run_card.body.addWidget(self.start_button)
        result_row = QHBoxLayout()
        self.open_folder_button = QPushButton("Open folder")
        self.open_report_button = QPushButton("Open report")
        result_row.addWidget(self.open_folder_button, 1)
        result_row.addWidget(self.open_report_button, 1)
        self.run_card.body.addLayout(result_row)
        self.side.addWidget(self.run_card)
        self.side.addStretch(1)

        # ----- signals ------------------------------------------------------------
        self.mode.valueChanged.connect(self._on_mode)
        self.add_button.clicked.connect(self.browse)
        self.clear_button.clicked.connect(self.clear)
        self.drop_zone.filesChosen.connect(self.add_files)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancel)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.open_report_button.clicked.connect(self.open_report)
        self.photo_picker.presetChanged.connect(self._on_preset)
        self._relay.item.connect(self._on_item)
        self.runner.finished.connect(self._on_finished)
        self.runner.failed.connect(self._on_failed)
        delete = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_selected)
        self._on_mode(BatchKind.PHOTO.value)

    # ----- mode & files ----------------------------------------------------------------
    @property
    def kind(self) -> BatchKind:
        return BatchKind(self.mode.value() or BatchKind.PHOTO.value)

    def accepted_extensions(self) -> tuple[str, ...]:
        return (".pdf",) if self.kind == BatchKind.PDF else IMAGE_EXTENSIONS

    def _on_mode(self, _value: str) -> None:
        kind = self.kind
        if self.files and not self.running:
            kept = [p for p in self.files if p.suffix.lower() in self.accepted_extensions()]
            if len(kept) != len(self.files):
                self.show_banner(f"Removed {len(self.files) - len(kept)} file(s) that don't fit this mode.", "info")
            self.files = []
            self._rebuild_table()
            self.add_files(kept)
        self.preset_card.setVisible(kind != BatchKind.PDF)
        self.photo_picker.setVisible(kind == BatchKind.PHOTO)
        self.sign_picker.setVisible(kind == BatchKind.SIGNATURE)
        self.photo_options.setVisible(kind == BatchKind.PHOTO)
        self.background_card.setVisible(kind == BatchKind.PHOTO)
        self.sign_options.setVisible(kind == BatchKind.SIGNATURE)
        self.compress_card.setVisible(kind == BatchKind.PDF)
        self.drop_zone.set_file_filter(PDF_FILTER if kind == BatchKind.PDF else IMAGE_FILTER)
        self._on_preset(self.photo_picker.current_preset())
        self._update_controls()

    def _on_preset(self, preset) -> None:  # noqa: ANN001
        self.background_card.set_preset(preset)

    def browse(self) -> None:
        file_filter = PDF_FILTER if self.kind == BatchKind.PDF else IMAGE_FILTER
        paths = ask_open_files(self, "Choose files", file_filter)
        if paths:
            self.add_files(paths)

    def add_files(self, paths: list[Path]) -> None:
        if self.running:
            return
        accepted = self.accepted_extensions()
        known = {p.resolve() if p.is_absolute() else p for p in self.files}
        added, wrong = 0, 0
        for raw in paths:
            path = Path(raw)
            if path.suffix.lower() not in accepted:
                wrong += 1
                continue
            key = path.resolve() if path.is_absolute() else path
            if key in known:
                continue
            if len(self.files) >= MAX_FILES:
                self.show_banner(f"A batch can hold up to {MAX_FILES} files.", "warning")
                break
            known.add(key)
            self.files.append(path)
            added += 1
        if wrong:
            noun = "PDFs" if self.kind == BatchKind.PDF else "images"
            self.show_banner(f"Skipped {wrong} file(s) that aren't {noun}. Switch the mode above for other kinds.", "warning")
        elif added:
            self.hide_banner()
        self.report = None
        self._rebuild_table()

    def remove_selected(self) -> None:
        if self.running:
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self.files[row]
        self._rebuild_table()

    def clear(self) -> None:
        if self.running:
            return
        self.files = []
        self.report = None
        self.hide_banner()
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        self.table.setRowCount(len(self.files))
        for row, path in enumerate(self.files):
            self._set_row(row, path.name, WAITING, "", "")
            self.table.item(row, 0).setToolTip(str(path))
        self._update_controls()

    def _set_row(self, row: int, name: str | None, status: str, result: str, notes: str) -> None:
        values = (name, status, result, notes)
        for column, value in enumerate(values):
            if value is None:
                continue
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            item.setText(value)
            if column == 3:
                item.setToolTip(value)

    # ----- running ---------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.runner.busy

    def settings(self) -> BatchSettings:
        """Read every option now, on the UI thread (workers never read widgets)."""
        kind = self.kind
        if kind == BatchKind.PDF:
            shrink = self.compress_card.settings()
            return BatchSettings(
                kind, target_bytes=shrink.target_bytes, min_bytes=shrink.min_bytes, grayscale=shrink.grayscale,
                label=f"PDFs {shrink.label}".strip(),
            )  # fmt: skip
        if kind == BatchKind.SIGNATURE:
            preset = self.sign_picker.current_preset()
            return BatchSettings(
                kind, preset, clean=CleanOptions(black_ink=self.black_ink.isChecked()),
                label=preset.name if preset else "Signatures",
            )  # fmt: skip
        preset = self.photo_picker.current_preset()
        return BatchSettings(
            kind, preset, self.background_card.options(), frame_person=self.frame_person.isChecked() and model_available(),
            label=preset.name if preset else "Photos",
        )  # fmt: skip

    def output_folder(self, settings: BatchSettings) -> Path:
        """The dated folder in the output folder (Settings), or under Pictures if that's read-only."""
        folder = batch_folder(self.files[0], settings.label, base=desktop.output_folder_for(self.files[0]))
        try:
            folder.parent.mkdir(parents=True, exist_ok=True)
            probe = folder.parent / ".docly-write-test"
            probe.write_bytes(b"")
            probe.unlink()
            return folder
        except OSError:
            fallback = desktop.pictures_output_folder() / folder.name
            self.show_banner(f"Docly can't write to {folder.parent}, so results go to {fallback.parent}.", "info")
            return fallback

    def start(self) -> None:
        if self.running or not self.files:
            return
        settings = self.settings()
        try:
            settings.check()
        except DoclyError as exc:
            self.show_banner(str(exc), "danger")
            return
        folder = self.output_folder(settings)
        files = list(self.files)
        for row in range(len(files)):
            self._set_row(row, None, WAITING, "", "")
        self._set_row(0, None, WORKING, "", "")
        self._stop.clear()
        self.report = None
        stop, relay = self._stop, self._relay
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.summary.setText(f"Working on {len(files)} files…")
        set_style_prop(self.summary, "state", None)
        self.detail.setText(f"Saving into {folder}")
        log.info("Batch started: %d files, %s", len(files), settings.kind.value)

        def job(_token) -> BatchReport:  # noqa: ANN001
            return run_batch(files, settings, folder, cancel=stop.is_set, on_item=relay.item.emit)

        self.runner.submit(job)
        self._update_controls()

    def cancel(self) -> None:
        """Stop after the current file; finished files stay saved."""
        if self.running:
            self._stop.set()
            self.summary.setText("Stopping after this file…")

    def _on_item(self, index: int, result: ItemResult) -> None:
        if index >= self.table.rowCount():
            return
        size = f"{result.size_bytes / 1024:.0f} KB" if result.size_bytes else ""
        if result.width and result.height:
            size += f" · {result.width}×{result.height}"
        self._set_row(index, None, STATUS_TEXT[result.status], size, result.message)
        self.progress.setValue(index + 1)
        if index + 1 < self.table.rowCount() and not self._stop.is_set():
            self._set_row(index + 1, None, WORKING, "", "")
        self.table.scrollToItem(self.table.item(index, 0))

    def _on_finished(self, report: BatchReport) -> None:
        self.report = report
        for row, item in enumerate(report.items):
            if item.status == Status.NOT_DONE and row < self.table.rowCount():
                self._set_row(row, None, STATUS_TEXT[Status.NOT_DONE], "", item.message)
        self.summary.setText(report.summary())
        bad = report.count(Status.FAILED) + report.count(Status.CHECK)
        set_style_prop(self.summary, "state", "warn" if bad else "pass")
        where = report.folder
        self.detail.setText(f"Saved in {where}" + ("\nStopped early; finished files are kept." if report.cancelled else ""))
        self.progress.setValue(self.progress.maximum())
        self._update_controls()
        # The buttons only just appeared; scroll once the layout has placed them.
        QTimer.singleShot(0, self, lambda: self.side_scroll.ensureWidgetVisible(self.open_folder_button, 0, 8))

    def _on_failed(self, message: str) -> None:
        self.summary.setText("The batch couldn't run")
        set_style_prop(self.summary, "state", "fail")
        self.detail.setText(message)
        self._update_controls()

    def open_folder(self) -> None:
        if self.report is not None:
            target = self.report.report_path or self.report.folder
            desktop.reveal_in_folder(target)

    def open_report(self) -> None:
        if self.report is not None and self.report.report_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report.report_path)))

    # ----- page-level drop ---------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = paths_from_mime(event.mimeData())
        event.acceptProposedAction()
        if paths:
            self.add_files(paths)

    def show_banner(self, text: str, kind: str = "danger") -> None:
        self.banner.show_message(text, kind)

    def hide_banner(self) -> None:
        self.banner.hide()

    def _update_controls(self) -> None:
        running = self.running
        has_files = bool(self.files)
        self.stack.setCurrentWidget(self.table_card if has_files else self.drop_zone)
        self.start_button.setVisible(not running)
        self.start_button.setText("Run again" if self.report is not None else "Start")
        self.start_button.setEnabled(has_files)
        self.progress.setVisible(running or self.report is not None)
        self.cancel_button.setVisible(running)
        for widget in (self.add_button, self.clear_button, self.mode, self.preset_card, self.photo_options,
                       self.background_card, self.sign_options, self.compress_card):  # fmt: skip
            widget.setEnabled(not running)
        done = self.report is not None and not running
        self.open_folder_button.setVisible(done)
        self.open_report_button.setVisible(done and self.report.report_path is not None)  # type: ignore[union-attr]
        count = len(self.files)
        self.count_label.setText(f"{count} file{'s' if count != 1 else ''}" if count else "")
        if not running and self.report is None:
            self.summary.setText(
                f"{count} file{'s' if count != 1 else ''} ready to go." if count else "Add files to begin."
            )
            set_style_prop(self.summary, "state", None)
            self.detail.setText("Results go into a new dated folder inside Docly_Output, next to the first file.")
