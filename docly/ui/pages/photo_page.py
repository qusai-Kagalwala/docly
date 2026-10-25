"""Photo page: drop a photo, pick a preset, adjust the crop, save."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from docly.core.compress import CancelCheck
from docly.core.image_io import LoadedImage
from docly.core.pipeline import ProcessResult, process_loaded
from docly.core.resize import CropBox
from docly.presets.models import Preset, PresetKind
from docly.ui.pages.image_tool_page import ImageToolPage, make_display_image
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card

NO_CROP_HINT = "This preset keeps the whole photo, so there's no crop frame."

__all__ = ["NO_CROP_HINT", "PhotoPage", "make_display_image"]


class PhotoPage(ImageToolPage):
    """Make a photo upload-ready for one preset (ratio-locked crop)."""

    PAGE_ID = "photo"
    TITLE = "Photo"
    SUBTITLE = "Resize, crop and compress photos to a portal's exact rules."
    ICON = "image"
    PRESET_KINDS = (PresetKind.PHOTO, PresetKind.IMAGE)

    def build_workspace(self, theme: ThemeManager) -> QWidget:
        self.crop_card = Card(theme)
        self.crop_card.body.setContentsMargins(10, 10, 10, 10)
        self.crop_card.body.addWidget(self.crop_view, 1)
        self.crop_hint = QLabel(NO_CROP_HINT)
        self.crop_hint.setProperty("role", "caption")
        self.crop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_card.body.addWidget(self.crop_hint)
        return self.crop_card

    def run(
        self, loaded: LoadedImage, preset: Preset, crop: CropBox | None, settings: object, cancel: CancelCheck
    ) -> ProcessResult:
        return process_loaded(loaded, preset, crop, cancel=cancel)

    def update_controls(self, has_image: bool) -> None:
        self.crop_hint.setVisible(has_image and not self.crop_view.has_crop)
