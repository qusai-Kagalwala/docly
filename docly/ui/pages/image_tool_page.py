"""Shared page for tools that turn one image into one upload-ready file.

The Photo and Signature pages work the same way:

    file → load (worker) → workspace shows it
    preset / setting changes → short pause → process (worker) → result card

Subclasses choose which presets to list, how the crop frame behaves, what
the workspace looks like, and which engine function processes the image.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from docly.core.compress import CancelCheck
from docly.core.image_io import LoadedImage, load_image
from docly.core.pipeline import ProcessResult
from docly.core.resize import CropBox
from docly.logger import get_logger
from docly.presets import PresetLoadResult, default_presets
from docly.presets.models import Preset, PresetKind
from docly.ui.pages.base_page import BasePage, SideColumn
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.crop_view import CropView
from docly.ui.widgets.drop_zone import DropZone, ask_open_image, paths_from_mime, pick_dropped_image
from docly.ui.widgets.preset_info import PresetInfoCard
from docly.ui.widgets.preset_picker import PresetPicker
from docly.ui.widgets.result_card import ResultCard
from docly.ui.widgets.style import set_style_prop
from docly.ui.workers import CancelToken, TaskRunner

log = get_logger(__name__)

DEBOUNCE_MS = 300  # wait this long after the last change before processing
DISPLAY_MAX = 1600  # longest side of the on-screen copy of the photo
SIDE_WIDTH = 320


def make_display_image(loaded: LoadedImage) -> QImage:
    """A reduced QImage for the screen (safe to build on a worker thread)."""
    preview = loaded.image.copy()
    preview.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.Resampling.BILINEAR)
    data = preview.tobytes("raw", "RGB")
    image = QImage(data, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888)
    return image.copy()  # own the pixels; ``data`` goes away after this function


class ImageToolPage(BasePage):
    """Base class. Subclasses override the hooks marked "hook" below."""

    SCROLLS = False  # the image fills the window; the side column scrolls
    PRESET_KINDS: tuple[PresetKind, ...] = (PresetKind.PHOTO,)
    REPLACE_TEXT = "Replace photo"
    RESET_TEXT = "Reset crop"

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

        self._path: Path | None = None  # file being opened or shown
        self._loaded_path: Path | None = None  # file currently on screen
        self._loaded: LoadedImage | None = None

        self.loader = TaskRunner(parent=self)
        self.processor = TaskRunner(parent=self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._process_now)

        # ----- layout: left (workspace) | right (preset, settings, result)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.content.addLayout(columns, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        columns.addLayout(left, 1)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.hide()
        left.addWidget(self.banner)

        self.crop_view = CropView(theme)
        self.stack = QStackedWidget()
        self.drop_zone = DropZone(theme)
        self.workspace = self.build_workspace(theme)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.workspace)
        left.addWidget(self.stack, 1)

        actions = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setProperty("role", "caption")
        self.replace_button = QPushButton(self.REPLACE_TEXT)
        self.reset_button = QPushButton(self.RESET_TEXT)
        actions.addWidget(self.file_label, 1)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.replace_button)
        left.addLayout(actions)

        self.side_scroll = SideColumn(SIDE_WIDTH + 14)
        self.side = self.side_scroll.column
        columns.addWidget(self.side_scroll)

        picker_card = Card(theme)
        section = QLabel("Preset")
        section.setProperty("role", "section")
        picker_card.body.addWidget(section)
        self.picker = PresetPicker(presets.presets, kinds=self.PRESET_KINDS, region=region)
        picker_card.body.addWidget(self.picker)
        self.side.addWidget(picker_card)

        self.info = PresetInfoCard(theme)
        self.side.addWidget(self.info)
        settings = self.build_settings(theme)
        if settings is not None:
            self.side.addWidget(settings)
        self.result_card = ResultCard(theme)
        self.side.addWidget(self.result_card)
        self.side.addStretch(1)

        # ----- signals --------------------------------------------------
        self.drop_zone.fileChosen.connect(self.load_file)
        self.drop_zone.message.connect(lambda text: self.show_banner(text, "info"))
        self.replace_button.clicked.connect(self.browse)
        self.reset_button.clicked.connect(self._reset_crop)
        self.crop_view.cropChanged.connect(self._on_crop_changed)
        self.picker.presetChanged.connect(self._on_preset_changed)
        self.loader.finished.connect(self._on_loaded)
        self.loader.failed.connect(self._on_load_failed)
        self.processor.started.connect(self.result_card.show_busy)
        self.processor.finished.connect(self._on_processed)
        self.processor.failed.connect(self._on_process_failed)

        self.info.show_preset(self.picker.current_preset())
        self.on_preset_changed(self.picker.current_preset())
        self._update_controls()

    # ----- hooks --------------------------------------------------------
    def build_workspace(self, theme: ThemeManager) -> QWidget:
        """hook: the widget shown once an image is loaded."""
        card = Card(theme)
        card.body.setContentsMargins(10, 10, 10, 10)
        card.body.addWidget(self.crop_view, 1)
        return card

    def build_settings(self, theme: ThemeManager) -> QWidget | None:
        """hook: an optional settings card between preset info and result."""
        return None

    def configure_crop(self, preset: Preset | None) -> None:
        """hook: set up the crop frame for ``preset`` (default: lock to its ratio)."""
        self.crop_view.set_ratio(preset.ratio if preset is not None else None)

    def job_settings(self) -> object:
        """hook: read the page's settings widgets (runs on the UI thread).

        The value is handed to :meth:`run`, because worker threads must
        never read widgets themselves.
        """
        return None

    def run(
        self, loaded: LoadedImage, preset: Preset, crop: CropBox | None, settings: object, cancel: CancelCheck
    ) -> ProcessResult:
        """hook: process on a worker thread. Must not touch widgets."""
        raise NotImplementedError

    def on_preset_changed(self, preset: Preset | None) -> None:
        """hook: react to a new preset (e.g. show a format switch)."""

    def on_result(self, result: ProcessResult) -> None:
        """hook: a new result arrived (already shown in the result card)."""

    def on_failure(self, message: str) -> None:
        """hook: processing failed (already shown in the result card)."""

    def update_controls(self, has_image: bool) -> None:
        """hook: show/hide page-specific controls."""

    # ----- public API -------------------------------------------------
    @property
    def preset(self) -> Preset | None:
        return self.picker.current_preset()

    @property
    def loaded(self) -> LoadedImage | None:
        return self._loaded

    def browse(self) -> None:
        start = str(self._loaded_path.parent) if self._loaded_path else ""
        path = ask_open_image(self, start)
        if path is not None:
            self.load_file(path)

    def load_file(self, path: Path) -> None:
        """Open ``path`` in the background."""
        self.hide_banner()
        self._debounce.stop()
        self.processor.cancel()
        target = Path(path)
        self._path = target
        self.file_label.setText(f"Opening {target.name}…")
        self.result_card.show_busy()
        log.info("Opening %s", target)

        def job(token: CancelToken) -> tuple[Path, LoadedImage, QImage]:
            loaded = load_image(target)
            if token.cancelled:
                return target, loaded, QImage()
            return target, loaded, make_display_image(loaded)

        self.loader.submit(job)

    def schedule(self) -> None:
        """Re-process after a short pause (call when any setting changes)."""
        if self._loaded is not None and self.preset is not None:
            self.result_card.show_busy()
            self._debounce.start()

    def show_banner(self, text: str, kind: str = "danger") -> None:
        self.banner.setText(text)
        set_style_prop(self.banner, "banner", kind)
        self.banner.show()

    def hide_banner(self) -> None:
        self.banner.hide()

    # ----- drag & drop anywhere on the page -----------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        path, note = pick_dropped_image(event.mimeData())
        event.acceptProposedAction()
        if path is None:
            self.show_banner(note or "That isn't a photo.", "danger")
            return
        self.load_file(path)
        if note:
            self.show_banner(note, "info")

    # ----- internals --------------------------------------------------
    def _on_loaded(self, payload: tuple[Path, LoadedImage, QImage]) -> None:
        path, loaded, display = payload
        self._loaded = loaded
        self._loaded_path = path
        self.crop_view.set_image(display, loaded.size, None)
        self.configure_crop(self.preset)
        self.stack.setCurrentWidget(self.workspace)
        w, h = loaded.size
        self.file_label.setText(f"{loaded.name} · {w} × {h} px")
        self._update_controls()
        self._process_now()

    def _on_load_failed(self, message: str) -> None:
        self.show_banner(message, "danger")
        self._path = self._loaded_path
        if self._loaded is None:
            self.file_label.clear()
            self.result_card.show_idle()
        else:
            # Keep the previous image on screen and its result.
            w, h = self._loaded.size
            self.file_label.setText(f"{self._loaded.name} · {w} × {h} px")
            self._process_now()
        self._update_controls()

    def _on_preset_changed(self, preset: Preset | None) -> None:
        self.info.show_preset(preset)
        self.configure_crop(preset)
        self.on_preset_changed(preset)
        self._update_controls()
        self.schedule()

    def _on_crop_changed(self) -> None:
        self._update_controls()
        self.schedule()

    def _reset_crop(self) -> None:
        self.crop_view.reset()
        self._update_controls()
        self.schedule()

    def _process_now(self) -> None:
        self._debounce.stop()
        loaded, preset = self._loaded, self.preset
        if loaded is None or preset is None:
            return
        crop = self.crop_view.crop_box()
        settings = self.job_settings()
        self.processor.submit(lambda token: self.run(loaded, preset, crop, settings, token))

    def _on_processed(self, result: ProcessResult) -> None:
        if self._loaded_path is not None:
            self.result_card.show_result(result, self._loaded_path)
            self.on_result(result)

    def _on_process_failed(self, message: str) -> None:
        self.result_card.show_error(message)
        self.on_failure(message)

    def _update_controls(self) -> None:
        has_image = self._loaded is not None
        self.replace_button.setVisible(has_image)
        self.reset_button.setVisible(has_image and self.crop_view.has_crop)
        if not has_image:
            self.stack.setCurrentWidget(self.drop_zone)
        self.update_controls(has_image)
