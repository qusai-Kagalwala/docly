"""Photo page: drop a photo, pick a preset, adjust the crop, save.

Flow:
    file → load (worker) → crop view shows it
    preset / crop changes → short pause → process (worker) → result card
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from docly.core.image_io import LoadedImage, load_image
from docly.core.pipeline import ProcessResult, process_loaded
from docly.logger import get_logger
from docly.presets import PresetLoadResult, default_presets
from docly.presets.models import Preset
from docly.ui.pages.base_page import BasePage
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
NO_CROP_HINT = "This preset keeps the whole photo, so there's no crop frame."


def make_display_image(loaded: LoadedImage) -> QImage:
    """A reduced QImage for the screen (safe to build on a worker thread)."""
    preview = loaded.image.copy()
    preview.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.Resampling.BILINEAR)
    data = preview.tobytes("raw", "RGB")
    image = QImage(data, preview.width, preview.height, preview.width * 3, QImage.Format.Format_RGB888)
    return image.copy()  # own the pixels; ``data`` goes away after this function


class PhotoPage(BasePage):
    """Make a photo upload-ready for one preset."""

    PAGE_ID = "photo"
    TITLE = "Photo"
    SUBTITLE = "Resize, crop and compress photos to a portal's exact rules."
    ICON = "image"
    SCROLLS = False  # the photo fills the window; the side column scrolls

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

        # ----- layout: left (photo) | right (preset + result) ----------
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

        self.stack = QStackedWidget()
        self.drop_zone = DropZone(theme)
        self.crop_card = Card(theme)
        self.crop_card.body.setContentsMargins(10, 10, 10, 10)
        self.crop_view = CropView(theme)
        self.crop_card.body.addWidget(self.crop_view, 1)
        self.crop_hint = QLabel(NO_CROP_HINT)
        self.crop_hint.setProperty("role", "caption")
        self.crop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_card.body.addWidget(self.crop_hint)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.crop_card)
        left.addWidget(self.stack, 1)

        actions = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setProperty("role", "caption")
        self.replace_button = QPushButton("Replace photo")
        self.reset_button = QPushButton("Reset crop")
        actions.addWidget(self.file_label, 1)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.replace_button)
        left.addLayout(actions)

        side = QWidget()
        side.setObjectName("PageBody")
        right = QVBoxLayout(side)
        right.setSpacing(16)
        # Room on the right for the scrollbar and on the edges for card shadows.
        right.setContentsMargins(2, 0, 12, 4)
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_scroll.setFixedWidth(SIDE_WIDTH + 14)
        self.side_scroll.setWidget(side)
        columns.addWidget(self.side_scroll)

        picker_card = Card(theme)
        section = QLabel("Preset")
        section.setProperty("role", "section")
        picker_card.body.addWidget(section)
        self.picker = PresetPicker(presets.presets, region=region)
        picker_card.body.addWidget(self.picker)
        right.addWidget(picker_card)

        self.info = PresetInfoCard(theme)
        right.addWidget(self.info)
        self.result_card = ResultCard(theme)
        right.addWidget(self.result_card)
        right.addStretch(1)

        # ----- signals --------------------------------------------------
        self.drop_zone.fileChosen.connect(self.load_file)
        self.drop_zone.message.connect(lambda text: self.show_banner(text, "info"))
        self.replace_button.clicked.connect(self.browse)
        self.reset_button.clicked.connect(self._reset_crop)
        self.crop_view.cropChanged.connect(self._schedule)
        self.picker.presetChanged.connect(self._on_preset_changed)
        self.loader.finished.connect(self._on_loaded)
        self.loader.failed.connect(self._on_load_failed)
        self.processor.started.connect(self.result_card.show_busy)
        self.processor.finished.connect(self._on_processed)
        self.processor.failed.connect(self.result_card.show_error)

        self.info.show_preset(self.picker.current_preset())
        self._update_controls()

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
        self.crop_view.set_image(display, loaded.size, self._ratio())
        self.stack.setCurrentWidget(self.crop_card)
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
            # Keep the previous photo on screen and its result.
            self.file_label.setText(f"{self._loaded.name} · {self._loaded.size[0]} × {self._loaded.size[1]} px")
            self._process_now()
        self._update_controls()

    def _on_preset_changed(self, preset: Preset | None) -> None:
        self.info.show_preset(preset)
        self.crop_view.set_ratio(self._ratio())
        self._update_controls()
        self._schedule()

    def _reset_crop(self) -> None:
        self.crop_view.reset()
        self._schedule()

    def _ratio(self) -> float | None:
        preset = self.preset
        return preset.ratio if preset is not None else None

    def _schedule(self) -> None:
        if self._loaded is not None and self.preset is not None:
            self.result_card.show_busy()
            self._debounce.start()

    def _process_now(self) -> None:
        self._debounce.stop()
        loaded, preset = self._loaded, self.preset
        if loaded is None or preset is None:
            return
        crop = self.crop_view.crop_box()
        self.processor.submit(lambda token: process_loaded(loaded, preset, crop, cancel=token))

    def _on_processed(self, result: ProcessResult) -> None:
        if self._loaded_path is not None:
            self.result_card.show_result(result, self._loaded_path)

    def _update_controls(self) -> None:
        has_photo = self._loaded is not None
        self.replace_button.setVisible(has_photo)
        self.reset_button.setVisible(has_photo and self.crop_view.has_crop)
        self.crop_hint.setVisible(has_photo and not self.crop_view.has_crop)
        if not has_photo:
            self.stack.setCurrentWidget(self.drop_zone)
