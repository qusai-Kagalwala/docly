"""Signature page: clean up a photo of ink on paper and fit it to a preset.

Also used for other ink-on-paper uploads: thumb impressions and handwritten
declarations.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from docly.core.compress import CancelCheck
from docly.core.image_io import LoadedImage
from docly.core.pipeline import ProcessResult, process_signature
from docly.core.resize import CropBox
from docly.core.signature import CleanOptions
from docly.presets.models import FileFormat, Preset, PresetKind
from docly.ui.pages.image_tool_page import ImageToolPage
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card
from docly.ui.widgets.image_preview import ImagePreview
from docly.ui.widgets.segmented import SegmentedControl

AREA_HINT = "Drag the edges to leave out the desk or page edges."
TRANSPARENT_TIP = (
    "Make the paper see-through, for placing your signature on documents and PDFs. "
    "Most portals want a white background, so leave this off for uploads."
)
STRENGTH_TIP = (
    "Low keeps faint or pencil strokes. High removes stubborn shadows and grey paper, "
    "but can thin very light strokes."
)


class SignaturePage(ImageToolPage):
    """Signature cleaner with live before/after preview."""

    PAGE_ID = "signature"
    TITLE = "Signature"
    SUBTITLE = "Clean up signatures, thumb impressions and handwritten declarations."
    ICON = "pen-line"
    PRESET_KINDS = (PresetKind.SIGNATURE, PresetKind.IMAGE)
    REPLACE_TEXT = "Replace image"
    RESET_TEXT = "Reset area"

    # ----- hooks --------------------------------------------------------
    def build_workspace(self, theme: ThemeManager) -> QWidget:
        workspace = QWidget()
        column = QVBoxLayout(workspace)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)

        original = Card(theme)
        original.body.setContentsMargins(12, 10, 12, 10)
        original.body.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Original")
        title.setProperty("role", "section")
        hint = QLabel(AREA_HINT)
        hint.setProperty("role", "caption")
        hint.setToolTip(AREA_HINT)
        header.addWidget(title)
        header.addWidget(hint, 1)
        original.body.addLayout(header)
        original.body.addWidget(self.crop_view, 1)
        column.addWidget(original, 3)

        cleaned = Card(theme)
        cleaned.body.setContentsMargins(12, 10, 12, 10)
        cleaned.body.setSpacing(4)
        title = QLabel("Cleaned")
        title.setProperty("role", "section")
        cleaned.body.addWidget(title)
        self.cleaned_view = ImagePreview(theme, "The cleaned result appears here.")
        cleaned.body.addWidget(self.cleaned_view, 1)
        column.addWidget(cleaned, 2)
        return workspace

    def build_settings(self, theme: ThemeManager) -> QWidget:
        card = Card(theme)
        section = QLabel("Cleaning")
        section.setProperty("role", "section")
        card.body.addWidget(section)

        row = QHBoxLayout()
        label = QLabel("Strength")
        label.setProperty("role", "body")
        label.setToolTip(STRENGTH_TIP)
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(CleanOptions().strength)
        self.strength.setPageStep(10)
        self.strength.setToolTip(STRENGTH_TIP)
        self.strength.setAccessibleName("Cleaning strength")
        self.strength_value = QLabel(str(self.strength.value()))
        self.strength_value.setProperty("role", "muted")
        self.strength_value.setFixedWidth(28)
        self.strength_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label)
        row.addWidget(self.strength, 1)
        row.addWidget(self.strength_value)
        card.body.addLayout(row)

        self.remove_specks = QCheckBox("Remove specks")
        self.remove_specks.setChecked(True)
        self.remove_specks.setToolTip("Remove dust, paper grain and tiny dots that aren't part of the signature.")
        self.trim = QCheckBox("Trim margins")
        self.trim.setChecked(True)
        self.trim.setToolTip("Cut away empty paper and leave an even border.")
        self.black_ink = QCheckBox("Make ink black")
        self.black_ink.setToolTip("Many portals ask for black ink. This changes only the colour, not the shape.")
        self.transparent = QCheckBox("Transparent background")
        self.transparent.setToolTip(TRANSPARENT_TIP)
        for box in (self.remove_specks, self.trim, self.black_ink, self.transparent):
            card.body.addWidget(box)
            box.toggled.connect(self.schedule)

        self.format_row = QWidget()
        format_layout = QHBoxLayout(self.format_row)
        format_layout.setContentsMargins(0, 4, 0, 0)
        format_label = QLabel("Format")
        format_label.setProperty("role", "body")
        self.format_switch = SegmentedControl([(FileFormat.JPG.value, "JPG"), (FileFormat.PNG.value, "PNG")])
        self.format_switch.set_value(FileFormat.JPG.value)
        format_layout.addWidget(format_label)
        format_layout.addStretch(1)
        format_layout.addWidget(self.format_switch)
        card.body.addWidget(self.format_row)

        self.strength.valueChanged.connect(self._on_strength)
        self.format_switch.valueChanged.connect(self._on_format)
        return card

    def configure_crop(self, preset: Preset | None) -> None:
        # The area is about the photo, not the preset, so keep the user's
        # selection when they switch presets; only set it up the first time.
        if not self.crop_view.free:
            self.crop_view.set_free()

    def job_settings(self) -> tuple[CleanOptions, FileFormat | None, bool]:
        return self.options(), self.output_format(), self.crop_view.is_whole_image

    def run(
        self, loaded: LoadedImage, preset: Preset, crop: CropBox | None, settings: object, cancel: CancelCheck
    ) -> ProcessResult:
        options, fmt, whole_image = settings  # type: ignore[misc]
        area = None if whole_image else crop
        return process_signature(loaded, preset, options, area, fmt, cancel)

    def on_preset_changed(self, preset: Preset | None) -> None:
        offers_png = preset is not None and len(preset.formats) > 1 and FileFormat.PNG in preset.formats
        self.format_row.setVisible(offers_png)
        if preset is not None and not offers_png:
            self.format_switch.set_value(preset.formats[0].value)
        if preset is not None and preset.formats == (FileFormat.PNG,):
            # A PNG-only signature preset (e.g. "transparent PNG"): start see-through.
            self.transparent.setChecked(True)
        self._update_transparent_option()

    def on_result(self, result: ProcessResult) -> None:
        self.cleaned_view.set_data(result.data)

    def on_failure(self, message: str) -> None:
        self.cleaned_view.clear()

    def update_controls(self, has_image: bool) -> None:
        self.reset_button.setVisible(has_image and not self.crop_view.is_whole_image)

    # ----- settings ---------------------------------------------------
    def options(self) -> CleanOptions:
        return CleanOptions(
            strength=self.strength.value(),
            remove_specks=self.remove_specks.isChecked(),
            trim=self.trim.isChecked(),
            black_ink=self.black_ink.isChecked(),
            transparent=self.transparent.isChecked() and self.output_format() == FileFormat.PNG,
        )

    def output_format(self) -> FileFormat | None:
        preset = self.preset
        if preset is None:
            return None
        chosen = FileFormat(self.format_switch.value() or preset.formats[0].value)
        return chosen if chosen in preset.formats else preset.formats[0]

    def _on_strength(self, value: int) -> None:
        self.strength_value.setText(str(value))
        self.schedule()

    def _on_format(self, _value: str) -> None:
        self._update_transparent_option()
        self.schedule()

    def _update_transparent_option(self) -> None:
        """Transparency needs PNG, so the option only shows for PNG output."""
        self.transparent.setVisible(self.output_format() == FileFormat.PNG)
