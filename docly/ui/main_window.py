"""Main window: sidebar on the left, the selected page on the right."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from docly import config
from docly.logger import get_logger
from docly.presets import PresetLoadResult
from docly.ui.about_dialog import AboutDialog
from docly.ui.icons import make_icon
from docly.ui.pages.base_page import BasePage
from docly.ui.pages.batch_page import BatchPage
from docly.ui.pages.pdf_page import PdfPage
from docly.ui.pages.photo_page import PhotoPage
from docly.ui.pages.settings_page import SettingsPage
from docly.ui.pages.signature_page import SignaturePage
from docly.ui.sidebar import NavItem, Sidebar
from docly.ui.theme import ThemeManager, Tokens

log = get_logger(__name__)

#: Sidebar order. Later phases replace a page class, not this list.
PAGE_CLASSES: tuple[type[BasePage], ...] = (PhotoPage, SignaturePage, PdfPage, BatchPage, SettingsPage)


class MainWindow(QMainWindow):
    """Top-level window that hosts the sidebar and the page stack."""

    def __init__(
        self,
        theme: ThemeManager,
        presets: PresetLoadResult | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(config.APP_NAME)
        self.setMinimumSize(*config.WINDOW_MIN_SIZE)
        self.resize(*config.WINDOW_DEFAULT_SIZE)

        root = QWidget()
        root.setObjectName("AppRoot")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        self.pages: list[BasePage] = [
            PhotoPage(theme, presets) if cls is PhotoPage else cls(theme) for cls in PAGE_CLASSES
        ]
        self.sidebar = Sidebar([NavItem(p.PAGE_ID, p.TITLE, p.ICON) for p in self.pages], theme)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        for page in self.pages:
            self.stack.addWidget(page)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)

        self.sidebar.pageRequested.connect(self._show_index)
        self.sidebar.aboutRequested.connect(self.show_about)
        self._about: AboutDialog | None = None

        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)
        self._show_index(0)

    # ----- navigation -------------------------------------------------
    def page_ids(self) -> list[str]:
        """IDs of all pages, in sidebar order."""
        return [page.PAGE_ID for page in self.pages]

    def current_page_id(self) -> str:
        """ID of the page currently on screen."""
        return self.pages[self.stack.currentIndex()].PAGE_ID

    def show_page(self, page_id: str) -> None:
        """Switch to the page with ``page_id`` (raises ``KeyError`` if unknown)."""
        ids = self.page_ids()
        if page_id not in ids:
            raise KeyError(page_id)
        self._show_index(ids.index(page_id))

    def _show_index(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        self.stack.setCurrentIndex(index)
        self.sidebar.set_current(index)
        log.debug("Showing page %s", self.pages[index].PAGE_ID)

    # ----- dialogs ----------------------------------------------------
    def show_about(self) -> AboutDialog:
        """Open the About dialog (window-modal, returns immediately)."""
        if self._about is None:
            self._about = AboutDialog(self.theme, self)
        self._about.open()
        return self._about

    def _apply_tokens(self, tokens: Tokens) -> None:
        self.setWindowIcon(make_icon("docly-mark", tokens.accent, 64))
