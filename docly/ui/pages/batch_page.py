"""Batch page (placeholder until Phase 9)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from docly.ui.pages.base_page import BasePage, EmptyStateCard
from docly.ui.theme import ThemeManager


class BatchPage(BasePage):
    """Apply one preset to many files at once."""

    PAGE_ID = "batch"
    TITLE = "Batch"
    SUBTITLE = "Apply one preset to many files at once."
    ICON = "layers"

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.add_card(
            EmptyStateCard(
                theme,
                icon=self.ICON,
                heading="Batch mode is on the way",
                text="Queue many files, apply one preset to all of them, and get a summary report. Originals are never touched.",
                chip="Coming in Phase 9",
            )
        )
        self.finish_layout()
