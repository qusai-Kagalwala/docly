"""Settings page. Phase 1 has Appearance and Diagnostics; more in Phase 10.2."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docly import config
from docly.logger import current_log_file, get_logger
from docly.ui.pages.base_page import BasePage
from docly.ui.theme import ThemeManager, ThemeMode
from docly.ui.widgets.card import Card
from docly.ui.widgets.segmented import SegmentedControl

log = get_logger(__name__)


def _setting_row(title: str, description: str, control: QWidget) -> QHBoxLayout:
    """A row with a title + muted description on the left, a control on the right."""
    row = QHBoxLayout()
    row.setSpacing(16)
    text_col = QVBoxLayout()
    text_col.setSpacing(2)
    title_label = QLabel(title)
    title_label.setProperty("role", "body")
    desc_label = QLabel(description)
    desc_label.setProperty("role", "caption")
    desc_label.setWordWrap(True)
    text_col.addWidget(title_label)
    text_col.addWidget(desc_label)
    row.addLayout(text_col, 1)
    row.addWidget(control)
    return row


class SettingsPage(BasePage):
    """App preferences."""

    PAGE_ID = "settings"
    TITLE = "Settings"
    SUBTITLE = "Appearance and app information."
    ICON = "settings"

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)

        # Appearance -------------------------------------------------
        appearance = Card(theme)
        section = QLabel("Appearance")
        section.setProperty("role", "section")
        appearance.body.addWidget(section)

        self.theme_selector = SegmentedControl(
            [(ThemeMode.SYSTEM.value, "System"), (ThemeMode.LIGHT.value, "Light"), (ThemeMode.DARK.value, "Dark")]
        )
        self.theme_selector.set_value(theme.mode.value)
        self.theme_selector.valueChanged.connect(theme.set_mode)
        theme.modeChanged.connect(self.theme_selector.set_value)
        appearance.body.addLayout(
            _setting_row("Theme", "System follows your Windows light or dark setting.", self.theme_selector)
        )
        self.add_card(appearance)

        # Diagnostics ------------------------------------------------
        diagnostics = Card(theme)
        section = QLabel("Diagnostics")
        section.setProperty("role", "section")
        diagnostics.body.addWidget(section)

        self.open_logs_button = QPushButton("Open log folder")
        self.open_logs_button.setObjectName("open_logs_button")
        self.open_logs_button.clicked.connect(self._open_log_folder)
        log_file = current_log_file()
        location = str(log_file.parent) if log_file else str(config.log_dir())
        diagnostics.body.addLayout(
            _setting_row(
                "Log files",
                f"Useful when reporting a problem. Saved in {location}",
                self.open_logs_button,
            )
        )
        self.add_card(diagnostics)
        self.finish_layout()

    def _open_log_folder(self) -> None:
        log_file = current_log_file()
        folder = log_file.parent if log_file else config.log_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            log.warning("Could not open log folder: %s", folder)
