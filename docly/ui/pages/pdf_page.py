"""PDF page: combine PDFs and photos, arrange pages, then save or split.

Flow:
    files → opened one at a time in the background (asks for passwords)
          → every page appears in the thumbnail grid
    drag / turn / delete / duplicate pages (all undoable)
    Create PDF  → one file          Split → several files
    → result card → Save (Docly_Output) / Save as… / Open folder

The original files are never changed: pages are copied into a new PDF.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from docly.core.errors import DoclyError, PasswordRequiredError, WrongPasswordError
from docly.core.image_pdf import PageSize
from docly.core.page_ranges import parse_ranges
from docly.core.pdf_compress import apply_to_result
from docly.core.pdf_ops import PageRef, PdfResult, Source, build_pdf, load_source, split_plan, suggest_name
from docly.logger import get_logger
from docly.presets import PresetLoadResult, default_presets
from docly.ui.pages.base_page import BasePage, SideColumn
from docly.ui.pdf.compress_card import CompressCard
from docly.ui.pdf.file_list import FileList, FileRow
from docly.ui.pdf.page_grid import PageGrid
from docly.ui.pdf.password_dialog import ask_password
from docly.ui.pdf.plan_model import PlanModel
from docly.ui.pdf.thumbnails import ThumbnailCache, ThumbSource
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.drop_zone import IMAGE_EXTENSIONS, DropZone, ask_open_files, paths_from_mime
from docly.ui.widgets.pdf_result_card import PdfResultCard
from docly.ui.widgets.segmented import SegmentedControl
from docly.ui.widgets.status_badge import Banner
from docly.ui.widgets.style import set_style_prop
from docly.ui.workers import CancelToken, TaskRunner

log = get_logger(__name__)

PDF_EXTENSIONS = (".pdf", *IMAGE_EXTENSIONS)
PDF_FILE_FILTER = (
    "PDFs and photos (*.pdf *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *.heic *.heif);;"
    "PDF documents (*.pdf);;All files (*)"
)
SIDE_WIDTH = 340  # a little wider than the photo pages: more cards, longer labels
SEGMENT_MIN = 56
SPLIT_EVERY_PAGE, SPLIT_EVERY_N, SPLIT_RANGES = "single", "every", "ranges"


class _Progress(QObject):
    """Carries progress from a worker thread to the UI thread."""

    changed = Signal(int, int)
    stage = Signal(str)  # e.g. "Shrinking part 2 of 4…"


class _NeedsPassword:
    def __init__(self, path: Path, wrong: bool) -> None:
        self.path = path
        self.wrong = wrong


class PdfPage(BasePage):
    """Merge, split, reorder and turn PDF pages; turn photos into a PDF."""

    PAGE_ID = "pdf"
    TITLE = "PDF"
    SUBTITLE = "Combine PDFs and photos, put pages in order, then save or split."
    ICON = "file-text"
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
        self.sources: list[Source] = []  # append-only while a session lasts
        self._queue: list[tuple[Path, str | None]] = []  # files waiting to open
        self._insert_at: int | None = None  # where the next opened file's pages go
        self._opening: Path | None = None
        self._build_lock = threading.Lock()  # one PDF build at a time
        self._progress = _Progress(self)

        self.model = PlanModel(self)
        self.thumbnails = ThumbnailCache(self)
        self.loader = TaskRunner(parent=self)
        self.processor = TaskRunner(parent=self)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.thumbnails.shutdown)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.content.addLayout(columns, 1)

        # ----- left: banner + drop zone / page grid --------------------------
        left = QVBoxLayout()
        left.setSpacing(10)
        columns.addLayout(left, 1)
        self.banner = Banner(theme)
        left.addWidget(self.banner)

        self.stack = QStackedWidget()
        self.drop_zone = DropZone(
            theme,
            title="Drop PDFs or photos here",
            hint="or click to browse · PDF, JPG, PNG, WebP, BMP, TIFF, GIF",
            privacy="Your files stay on this computer. Originals are never changed.",
            icon="file-text",
            multiple=True,
            file_filter=PDF_FILE_FILTER,
            picker_title="Choose PDFs or photos",
        )
        self.grid = PageGrid(self.model, self.thumbnails, theme)
        self.workspace = self._build_workspace(theme)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.workspace)
        left.addWidget(self.stack, 1)

        self.status_label = QLabel()
        self.status_label.setProperty("role", "caption")
        left.addWidget(self.status_label)

        # ----- right: files, photo page size, split, result ---------------------
        self.side_scroll = SideColumn(SIDE_WIDTH + 14)
        self.side = self.side_scroll.column
        columns.addWidget(self.side_scroll)

        files_card = Card(theme)
        files_card.body.addWidget(_section("Files"))
        self.file_list = FileList(theme)
        files_card.body.addWidget(self.file_list)
        self.add_button = QPushButton("Add files…")
        files_card.body.addWidget(self.add_button)
        self.side.addWidget(files_card)

        self.page_size_card = Card(theme)
        self.page_size_card.body.addWidget(_section("Page size for photos"))
        self.page_size = SegmentedControl(
            [("a4", "A4"), ("letter", "Letter"), ("fit", "Fit photo")], min_button_width=SEGMENT_MIN
        )
        self.page_size.set_value("a4")
        self.page_size_card.body.addWidget(self.page_size)
        size_hint = QLabel("Photos are centred on the page with a small margin. “Fit photo” makes the page the photo's size.")
        size_hint.setProperty("role", "caption")
        size_hint.setWordWrap(True)
        self.page_size_card.body.addWidget(size_hint)
        self.side.addWidget(self.page_size_card)

        self.compress_card = CompressCard(theme, presets.presets, region)
        self.side.addWidget(self.compress_card)

        self.result_card = PdfResultCard(theme)
        self.side.addWidget(self.result_card)

        self.split_card = self._build_split_card(theme)
        self.side.addWidget(self.split_card)
        self.side.addStretch(1)

        # ----- signals ------------------------------------------------------------
        self.drop_zone.filesChosen.connect(self.add_files)
        self.add_button.clicked.connect(self.browse)
        self.grid.filesDropped.connect(self.add_files)
        self.grid.message.connect(lambda text: self.show_banner(text, "info"))
        self.grid.extractRequested.connect(self.extract_rows)
        self.grid.selectionModel().selectionChanged.connect(self._update_status)
        self.file_list.removeRequested.connect(self.remove_source)
        self.model.planChanged.connect(self._on_plan_changed)
        self.page_size.valueChanged.connect(lambda _v: self._mark_stale())
        self.compress_card.changed.connect(self._mark_stale)
        self.loader.finished.connect(self._on_opened)
        self.loader.failed.connect(self._on_open_failed)
        self.processor.finished.connect(self._on_built)
        self.processor.failed.connect(self.result_card.show_error)
        self.result_card.createRequested.connect(self.create_pdf)
        self.result_card.cancelRequested.connect(self.cancel)
        self._progress.changed.connect(self.result_card.set_progress)
        self._progress.stage.connect(self.result_card.set_stage)

        self._on_plan_changed()

    # ----- layout pieces ------------------------------------------------------
    def _build_workspace(self, theme: ThemeManager) -> QWidget:
        card = Card(theme)
        card.body.setContentsMargins(10, 10, 10, 10)
        card.body.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.tool_buttons: dict[str, QToolButton] = {}
        for name, action in (
            ("rotate_left", self.grid.rotate_left_action),
            ("rotate_right", self.grid.rotate_right_action),
            ("duplicate", self.grid.duplicate_action),
            ("delete", self.grid.delete_action),
            ("", None),
            ("undo", self.grid.undo_action),
            ("redo", self.grid.redo_action),
        ):
            if action is None:
                toolbar.addSpacing(10)
                continue
            button = QToolButton()
            button.setDefaultAction(action)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            shortcut = action.shortcut().toString(action.shortcut().SequenceFormat.NativeText)
            button.setToolTip(f"{action.text()} ({shortcut})" if shortcut else action.text())
            toolbar.addWidget(button)
            self.tool_buttons[name] = button
        toolbar.addStretch(1)
        self.selection_label = QLabel()
        self.selection_label.setProperty("role", "caption")
        toolbar.addWidget(self.selection_label)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Remove every file and start over")
        toolbar.addWidget(self.clear_button)
        self.clear_button.clicked.connect(self.clear)
        card.body.addLayout(toolbar)
        card.body.addWidget(self.grid, 1)
        tip = QLabel("Drag pages to reorder · right-click for more · Ctrl+Z to undo")
        tip.setProperty("role", "caption")
        card.body.addWidget(tip)
        return card

    def _build_split_card(self, theme: ThemeManager) -> Card:
        card = Card(theme)
        card.body.addWidget(_section("Split into several PDFs"))
        self.split_mode = SegmentedControl(
            [(SPLIT_EVERY_PAGE, "Each page"), (SPLIT_EVERY_N, "Every N"), (SPLIT_RANGES, "Ranges")],
            min_button_width=SEGMENT_MIN,
        )
        self.split_mode.set_value(SPLIT_EVERY_PAGE)
        card.body.addWidget(self.split_mode)

        self.split_every = QSpinBox()
        self.split_every.setRange(1, 999)
        self.split_every.setValue(2)
        self.split_every.setPrefix("Every ")
        self.split_every.setSuffix(" pages")
        card.body.addWidget(self.split_every)

        self.split_ranges = QLineEdit()
        self.split_ranges.setPlaceholderText("e.g. 1-3, 4, 5-")
        self.split_ranges.setToolTip("One PDF per range. Page numbers are as shown in the grid.")
        card.body.addWidget(self.split_ranges)

        self.split_hint = QLabel()
        self.split_hint.setWordWrap(True)
        self.split_hint.setProperty("role", "caption")
        card.body.addWidget(self.split_hint)

        self.split_button = QPushButton("Split")
        card.body.addWidget(self.split_button)

        self.split_mode.valueChanged.connect(lambda _v: self._update_split())
        self.split_every.valueChanged.connect(lambda _v: self._update_split())
        self.split_ranges.textChanged.connect(lambda _t: self._update_split())
        self.split_ranges.returnPressed.connect(self.split_pdf)
        self.split_button.clicked.connect(self.split_pdf)
        return card

    # ----- opening files --------------------------------------------------------
    def browse(self) -> None:
        start = str(self.sources[-1].path.parent) if self.sources else ""
        paths = ask_open_files(self, "Choose PDFs or photos", PDF_FILE_FILTER, start)
        if paths:
            self.add_files(paths)

    def add_files(self, paths: list[Path], insert_at: int | None = None) -> None:
        """Open ``paths`` one after another and add their pages at ``insert_at``."""
        usable = [Path(p) for p in paths if Path(p).suffix.lower() in PDF_EXTENSIONS]
        skipped = [Path(p).name for p in paths if Path(p).suffix.lower() not in PDF_EXTENSIONS]
        if skipped:
            self.show_banner(f"Skipped {', '.join(skipped)}: use PDFs or photos.", "warning")
        else:
            self.hide_banner()
        if not usable:
            return
        if not self._queue and self._opening is None:
            self._insert_at = insert_at
        self._queue.extend((p, None) for p in usable)
        self._open_next()

    def ask_password(self, file_name: str, wrong: bool) -> str | None:
        """Ask for a password (tests replace this)."""
        return ask_password(self, file_name, wrong)

    def _open_next(self) -> None:
        if self._opening is not None or not self._queue:
            self._update_status()
            return
        path, password = self._queue.pop(0)
        self._opening = path
        self._update_status()

        def job(_token: CancelToken) -> tuple[Path, Source] | _NeedsPassword:
            try:
                return path, load_source(path, password)
            except PasswordRequiredError:
                return _NeedsPassword(path, wrong=False)
            except WrongPasswordError:
                return _NeedsPassword(path, wrong=True)

        self.loader.submit(job)

    def _on_opened(self, payload: tuple[Path, Source] | _NeedsPassword) -> None:
        self._opening = None
        if isinstance(payload, _NeedsPassword):
            password = self.ask_password(payload.path.name, payload.wrong)
            if password:
                self._queue.insert(0, (payload.path, password))
            else:
                self.show_banner(f"Skipped {payload.path.name} (no password).", "info")
            self._open_next()
            return
        path, source = payload
        index = len(self.sources)
        self.sources.append(source)
        self.thumbnails.add_source(index, ThumbSource(source.data, source.is_pdf, source.password))
        refs = [PageRef(index, page) for page in range(source.page_count)]
        if len(self.model) == 0:
            self.model.reset(refs)
        else:
            self.model.append(refs, self._insert_at, text=f"Add {source.name}")
        if self._insert_at is not None:
            self._insert_at += len(refs)
        if source.warnings:
            self.show_banner(f"{source.name}: " + " ".join(source.warnings), "warning")
        log.info("Added %s (%d pages)", path.name, source.page_count)
        self._open_next()

    def _on_open_failed(self, message: str) -> None:
        self._opening = None
        self.show_banner(message, "danger")
        self._open_next()

    # ----- editing --------------------------------------------------------------
    def remove_source(self, source: int) -> None:
        if all(ref.source == source for ref in self.model.plan):
            self.clear()  # removing the last file starts over
            return
        self.model.remove_source(source, self.sources[source].name)

    def clear(self) -> None:
        """Forget every file and go back to the drop zone."""
        self.processor.cancel()
        self.loader.cancel()
        self._queue.clear()
        self._opening = None
        self._insert_at = None
        # Sources are not closed here: a cancelled build may still be reading
        # them. They close when nothing refers to them any more.
        self.sources = []
        self.thumbnails.clear()
        self.model.reset()
        self.hide_banner()

    # ----- building ---------------------------------------------------------------
    def current_page_size(self) -> PageSize:
        return {"letter": PageSize.LETTER, "fit": PageSize.FIT}.get(self.page_size.value() or "", PageSize.A4)

    def output_name(self) -> str:
        return suggest_name(self.sources, self.model.plan)

    def create_pdf(self) -> None:
        plan = self.model.plan
        if not plan:
            return
        self._submit(plan, groups=None, name=self.output_name(), split=False)

    def extract_rows(self, rows: list[int]) -> None:
        if rows:
            self._submit(self.model.plan, groups=[sorted(rows)], name=self._split_base(), split=False)

    def split_groups(self) -> list[list[int]]:
        """Groups of grid positions for the current split settings. Raises DoclyError."""
        count = len(self.model)
        mode = self.split_mode.value()
        if mode == SPLIT_RANGES:
            return parse_ranges(self.split_ranges.text(), count)
        size = 1 if mode == SPLIT_EVERY_PAGE else self.split_every.value()
        return [list(range(start, min(start + size, count))) for start in range(0, count, size)]

    def split_pdf(self) -> None:
        try:
            groups = self.split_groups()
        except DoclyError as exc:
            self.split_hint.setText(str(exc))
            return
        if groups:
            self._submit(self.model.plan, groups=groups, name=self._split_base(), split=True)

    def cancel(self) -> None:
        self.processor.cancel()
        self.result_card.show_idle(self._idle_text())

    def _split_base(self) -> str:
        name = self.output_name()
        return name.replace("_edited.pdf", ".pdf")

    def _submit(self, plan: list[PageRef], groups: list[list[int]] | None, name: str, split: bool) -> None:
        sources = list(self.sources)
        page_size = self.current_page_size()
        first = sources[plan[groups[0][0]].source if groups else plan[0].source].path
        lock, progress = self._build_lock, self._progress
        shrink = self.compress_card.settings()  # read widgets here, never on the worker

        def job(token: CancelToken) -> tuple[list[PdfResult], Path, bool]:
            def report(done: int, total: int) -> None:
                progress.changed.emit(done, total)

            with lock:
                if groups is None:
                    results = [build_pdf(sources, plan, name, page_size, cancel=token, progress=report)]
                else:
                    results = split_plan(sources, plan, groups, name, page_size=page_size, cancel=token)
            if shrink.active:
                for index, result in enumerate(results):
                    part = f" part {index + 1} of {len(results)}" if len(results) > 1 else ""
                    if shrink.label:
                        progress.stage.emit(f"Shrinking{part} to under {shrink.label}…")
                    else:
                        progress.stage.emit(f"Making pictures grey{part}…")
                    results[index] = apply_to_result(
                        result, shrink.target_bytes, shrink.min_bytes, shrink.grayscale, token, report
                    )
            return results, first, split

        self.result_card.show_busy("Splitting…" if split else "Building your PDF…")
        self.side_scroll.ensureWidgetVisible(self.result_card, 0, 0)
        self.processor.submit(job)

    def _on_built(self, payload: tuple[list[PdfResult], Path, bool]) -> None:
        results, first, split = payload
        self.result_card.show_results(results, first, split)
        self.side_scroll.ensureWidgetVisible(self.result_card, 0, 0)

    # ----- page-level drag & drop -------------------------------------------------
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

    # ----- state -------------------------------------------------------------------
    def show_banner(self, text: str, kind: str = "danger") -> None:
        self.banner.show_message(text, kind)

    def hide_banner(self) -> None:
        self.banner.hide()

    def _idle_text(self) -> str:
        count = len(self.model)
        if count == 0:
            return "Add PDFs or photos to begin."
        pages = f"{count} page" + ("" if count == 1 else "s")
        return f"{pages} arranged. Create a PDF, or split it below."

    def _mark_stale(self) -> None:
        if not self.processor.busy:
            self.result_card.show_idle(self._idle_text(), can_create=len(self.model) > 0)

    def _on_plan_changed(self) -> None:
        plan = self.model.plan
        has_pages = bool(plan)
        self.stack.setCurrentWidget(self.workspace if has_pages else self.drop_zone)
        used = self.model.sources_used()
        self.file_list.set_rows(
            [
                FileRow(
                    i,
                    self.sources[i].name,
                    self.model.pages_from(i),
                    self.sources[i].page_count,
                    self.sources[i].is_pdf,
                    tuple(self.sources[i].warnings),
                )
                for i in used
            ]
        )
        several = len(used) > 1
        self.grid.set_source_labels(
            (lambda ref: self.sources[ref.source].name if ref.source < len(self.sources) else "")
            if several
            else (lambda _ref: "")
        )
        self.page_size_card.setVisible(any(not self.sources[i].is_pdf for i in used))
        self.split_card.setVisible(len(plan) > 1)
        self.processor.cancel()
        self._mark_stale()
        self._update_split()
        self._update_status()

    def _update_split(self) -> None:
        mode = self.split_mode.value()
        self.split_every.setVisible(mode == SPLIT_EVERY_N)
        self.split_ranges.setVisible(mode == SPLIT_RANGES)
        try:
            groups = self.split_groups() if len(self.model) else []
        except DoclyError as exc:
            self.split_hint.setText(str(exc))
            set_style_prop(self.split_hint, "banner", "danger")
            set_style_prop(self.split_hint, "role", None)
            self.split_button.setEnabled(False)
            return
        set_style_prop(self.split_hint, "banner", None)
        set_style_prop(self.split_hint, "role", "caption")
        if mode == SPLIT_RANGES and not self.split_ranges.text().strip():
            self.split_hint.setText("Type the page ranges, separated by commas.")
            self.split_button.setEnabled(False)
            return
        self.split_hint.setText(f"Makes {len(groups)} PDF" + ("" if len(groups) == 1 else "s") + ".")
        self.split_button.setEnabled(len(groups) > 0)

    def _update_status(self, *_args: object) -> None:
        selected = len(self.grid.selected_rows())
        self.selection_label.setText(f"{selected} selected" if selected else "")
        if self._opening is not None:
            waiting = len(self._queue)
            more = f" ({waiting} more waiting)" if waiting else ""
            self.status_label.setText(f"Opening {self._opening.name}…{more}")
        else:
            count = len(self.model)
            files = len(self.model.sources_used())
            self.status_label.setText(
                f"{count} page{'s' if count != 1 else ''} from {files} file{'s' if files != 1 else ''}" if count else ""
            )


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label

