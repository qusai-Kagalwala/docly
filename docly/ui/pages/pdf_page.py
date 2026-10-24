"""PDF page (placeholder until Phases 7–8)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from docly.ui.pages.base_page import BasePage, EmptyStateCard
from docly.ui.theme import ThemeManager


class PdfPage(BasePage):
    """Merge, split, reorder and compress PDFs."""

    PAGE_ID = "pdf"
    TITLE = "PDF"
    SUBTITLE = "Merge, split, reorder and compress PDFs."
    ICON = "file-text"

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.add_card(
            EmptyStateCard(
                theme,
                icon=self.ICON,
                heading="PDF tools are on the way",
                text="Merge files, split by page ranges, drag pages into order, turn images into a PDF, and compress to a target size.",
                chip="Coming in Phases 7–8",
            )
        )
        self.finish_layout()
