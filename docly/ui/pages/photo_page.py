"""Photo page (placeholder until Phase 4)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from docly.ui.pages.base_page import BasePage, EmptyStateCard
from docly.ui.theme import ThemeManager


class PhotoPage(BasePage):
    """Resize, crop and compress photos to a portal's exact rules."""

    PAGE_ID = "photo"
    TITLE = "Photo"
    SUBTITLE = "Resize, crop and compress photos to a portal's exact rules."
    ICON = "image"

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.add_card(
            EmptyStateCard(
                theme,
                icon=self.ICON,
                heading="Photo tools are on the way",
                text="Drop a photo here, pick a portal preset, and Docly will crop and compress it to the exact size and KB range.",
                chip="Coming in Phase 4",
            )
        )
        self.finish_layout()
