"""Settings page: where results are saved, presets, appearance, help, diagnostics.

Settings take effect straight away and are saved to the settings file in
AppData. The page also applies the saved choices when the app starts.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docly import config
from docly.core.files import os_path
from docly.logger import current_log_file, get_logger
from docly.ui import desktop, motion
from docly.ui.pages.base_page import BasePage
from docly.ui.theme import ThemeManager, ThemeMode
from docly.ui.widgets.card import Card
from docly.ui.widgets.segmented import SegmentedControl
from docly.ui.widgets.status_badge import Banner

log = get_logger(__name__)

NEXT_TO_ORIGINAL, ONE_FOLDER = "next", "folder"


def ask_folder(parent: QWidget, start: str) -> Path | None:
    """Windows folder picker; None if cancelled."""
    chosen = QFileDialog.getExistingDirectory(parent, "Choose where Docly saves results", start)
    return Path(chosen) if chosen else None


def can_write_to(folder: Path) -> bool:
    """Try creating (and removing) a small file, the only reliable test on Windows."""
    probe = folder / ".docly-write-test"
    try:
        os.makedirs(os_path(folder), exist_ok=True)
        with open(os_path(probe), "wb"):
            pass
        os.remove(os_path(probe))
        return True
    except OSError:
        return False


def _setting_row(title: str, description: str, control: QWidget | None = None) -> tuple[QHBoxLayout, QLabel]:
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
    if control is not None:
        row.addWidget(control)
    return row, desc_label


def _section(card: Card, text: str) -> None:
    label = QLabel(text)
    label.setProperty("role", "section")
    card.body.addWidget(label)


class SettingsPage(BasePage):
    """App preferences.

    Signals:
        tourRequested(): "Show the tour again".
        shortcutsRequested(): "Keyboard shortcuts".
        rememberPresetsChanged(bool)
    """

    PAGE_ID = "settings"
    TITLE = "Settings"
    SUBTITLE = "Where results go, presets, appearance and help."
    ICON = "settings"

    tourRequested = Signal()
    shortcutsRequested = Signal()
    rememberPresetsChanged = Signal(bool)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.store = theme.store

        # ----- saving ------------------------------------------------------
        saving = Card(theme)
        _section(saving, "Saving")
        self.save_mode = SegmentedControl([(NEXT_TO_ORIGINAL, "Next to the original"), (ONE_FOLDER, "One folder")])
        self.save_mode.setAccessibleName("Where to save results")
        row, _desc = _setting_row(
            "Save results",
            "Next to the original puts them in a Docly_Output folder beside each file. "
            "Your originals are never changed.",
            self.save_mode,
        )
        saving.body.addLayout(row)
        self.folder_row = QWidget()
        folder_line = QHBoxLayout(self.folder_row)
        folder_line.setContentsMargins(0, 0, 0, 0)
        self.folder_label = QLabel()
        self.folder_label.setProperty("role", "caption")
        self.folder_label.setWordWrap(True)
        self.choose_button = QPushButton("Choose folder…")
        folder_line.addWidget(self.folder_label, 1)
        folder_line.addWidget(self.choose_button)
        saving.body.addWidget(self.folder_row)
        self.folder_message = Banner(theme)
        saving.body.addWidget(self.folder_message)
        self.add_card(saving)

        # ----- presets -------------------------------------------------------
        presets = Card(theme)
        _section(presets, "Presets")
        self.remember_presets = QCheckBox("Remember the last preset on each page")
        self.remember_presets.setChecked(self.store.remember_presets())
        presets.body.addWidget(self.remember_presets)
        self.add_card(presets)

        # ----- appearance ------------------------------------------------------
        appearance = Card(theme)
        _section(appearance, "Appearance")
        self.theme_selector = SegmentedControl(
            [(ThemeMode.SYSTEM.value, "System"), (ThemeMode.LIGHT.value, "Light"), (ThemeMode.DARK.value, "Dark")]
        )
        self.theme_selector.set_value(theme.mode.value)
        self.theme_selector.valueChanged.connect(theme.set_mode)
        theme.modeChanged.connect(self.theme_selector.set_value)
        row, _desc = _setting_row("Theme", "System follows your Windows light or dark setting.", self.theme_selector)
        appearance.body.addLayout(row)
        self.reduce_motion = QCheckBox("Reduce motion")
        self.reduce_motion.setToolTip("Turn off Docly's animations")
        self.reduce_motion.setChecked(self.store.reduce_motion())
        appearance.body.addWidget(self.reduce_motion)
        hint = QLabel("Animations are also off when Windows' Animation effects setting is off.")
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        appearance.body.addWidget(hint)
        self.add_card(appearance)

        # ----- help ---------------------------------------------------------------
        help_card = Card(theme)
        _section(help_card, "Help")
        buttons = QHBoxLayout()
        self.tour_button = QPushButton("Show the tour again")
        self.shortcuts_button = QPushButton("Keyboard shortcuts")
        self.shortcuts_button.setToolTip("F1")
        buttons.addWidget(self.tour_button)
        buttons.addWidget(self.shortcuts_button)
        buttons.addStretch(1)
        help_card.body.addLayout(buttons)
        self.add_card(help_card)

        # ----- diagnostics -----------------------------------------------------------
        diagnostics = Card(theme)
        _section(diagnostics, "Diagnostics")
        self.open_logs_button = QPushButton("Open log folder")
        self.open_logs_button.setObjectName("open_logs_button")
        self.open_logs_button.clicked.connect(self._open_log_folder)
        log_file = current_log_file()
        location = str(log_file.parent) if log_file else str(config.log_dir())
        row, _desc = _setting_row("Log files", f"Useful when reporting a problem. Saved in {location}", self.open_logs_button)
        diagnostics.body.addLayout(row)
        self.add_card(diagnostics)
        self.finish_layout()

        self.save_mode.valueChanged.connect(self._on_save_mode)
        self.choose_button.clicked.connect(self.choose_folder)
        self.remember_presets.toggled.connect(self._on_remember)
        self.reduce_motion.toggled.connect(self._on_reduce_motion)
        self.tour_button.clicked.connect(self.tourRequested)
        self.shortcuts_button.clicked.connect(self.shortcutsRequested)

        # Apply what was saved last time.
        motion.set_reduce_motion(self.store.reduce_motion())
        folder = self.store.output_folder()
        desktop.set_custom_output_folder(folder)
        self.save_mode.set_value(ONE_FOLDER if folder is not None else NEXT_TO_ORIGINAL)
        self._show_folder()

    # ----- saving -------------------------------------------------------------
    def _on_save_mode(self, value: str) -> None:
        if value == NEXT_TO_ORIGINAL:
            self.set_output_folder(None)
        elif desktop.custom_output_folder() is None and not self.choose_folder():
            self.save_mode.set_value(NEXT_TO_ORIGINAL)  # cancelled: nothing changes

    def choose_folder(self) -> bool:
        """Ask for a folder; True if one was chosen and it can be written to."""
        current = desktop.custom_output_folder()
        start = str(current) if current is not None else str(desktop.pictures_output_folder().parent)
        folder = ask_folder(self, start)
        if folder is None:
            return False
        return self.set_output_folder(folder)

    def set_output_folder(self, folder: Path | None) -> bool:
        if folder is not None and not can_write_to(folder):
            self.folder_message.show_message(
                f"Docly can't save into {folder}. Choose a folder you can write to.", "danger"
            )
            return False
        self.folder_message.hide()
        self.store.set_output_folder(folder)
        desktop.set_custom_output_folder(folder)
        self.save_mode.set_value(ONE_FOLDER if folder is not None else NEXT_TO_ORIGINAL)
        self._show_folder()
        log.info("Output folder: %s", folder or "next to the original")
        return True

    def _show_folder(self) -> None:
        folder = desktop.custom_output_folder()
        self.folder_row.setVisible(folder is not None)
        self.folder_label.setText(f"Saving into {folder}" if folder is not None else "")
        self.folder_label.setToolTip(str(folder) if folder is not None else "")

    # ----- other settings ------------------------------------------------------
    def _on_remember(self, remember: bool) -> None:
        self.store.set_remember_presets(remember)
        self.rememberPresetsChanged.emit(remember)

    def _on_reduce_motion(self, reduce: bool) -> None:
        self.store.set_reduce_motion(reduce)
        motion.set_reduce_motion(reduce)

    def _open_log_folder(self) -> None:
        log_file = current_log_file()
        folder = log_file.parent if log_file else config.log_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            log.warning("Could not open log folder: %s", folder)
