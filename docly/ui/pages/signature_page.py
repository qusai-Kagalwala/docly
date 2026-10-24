"""Signature page (placeholder until Phase 5)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from docly.ui.pages.base_page import BasePage, EmptyStateCard
from docly.ui.theme import ThemeManager


class SignaturePage(BasePage):
    """Clean up scanned signatures so they upload crisp and clear."""

    PAGE_ID = "signature"
    TITLE = "Signature"
    SUBTITLE = "Clean up scanned signatures so they upload crisp and clear."
    ICON = "pen-line"

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.add_card(
            EmptyStateCard(
                theme,
                icon=self.ICON,
                heading="Signature cleaner is on the way",
                text="Docly will whiten the background, darken the ink and trim the margins of a signature photo.",
                chip="Coming in Phase 5",
            )
        )
        self.finish_layout()
