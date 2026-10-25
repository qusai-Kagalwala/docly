"""Main window: sidebar on the left, the selected page on the right."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from docly import config
from docly.logger import get_logger
from docly.presets import PresetLoadResult
from docly.ui import desktop, motion
from docly.ui.about_dialog import AboutDialog
from docly.ui.icons import make_icon
from docly.ui.pages.base_page import BasePage
from docly.ui.pages.batch_page import BatchPage
from docly.ui.pages.home_page import HomePage
from docly.ui.pages.image_tool_page import ImageToolPage
from docly.ui.pages.pdf_page import PdfPage
from docly.ui.pages.photo_page import PhotoPage
from docly.ui.pages.settings_page import SettingsPage
from docly.ui.pages.sign_page import SignPage
from docly.ui.pages.signature_page import SignaturePage
from docly.ui.shortcuts import ShortcutsDialog
from docly.ui.sidebar import NavItem, Sidebar
from docly.ui.theme import LIGHT, ThemeManager, Tokens
from docly.ui.tour import TourOverlay, TourStep
from docly.ui.widgets.pdf_result_card import PdfResultCard
from docly.ui.widgets.preset_picker import PresetPicker
from docly.ui.widgets.result_card import ResultCard
from docly.ui.widgets.toast import ToastHost

log = get_logger(__name__)

#: Sidebar order. Later phases replace a page class, not this list.
PAGE_CLASSES: tuple[type[BasePage], ...] = (
    HomePage, PhotoPage, SignaturePage, PdfPage, SignPage, BatchPage, SettingsPage,
)  # fmt: skip


def app_icon() -> QIcon:
    """Docly's app icon (the same file the .exe and the Store use)."""
    for path in (config.APP_ICON_PATH, config.APP_ICON_PNG):
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return make_icon("docly-mark", LIGHT.accent, 64)  # icon files missing: never leave the window blank


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
            cls(theme, presets) if issubclass(cls, (ImageToolPage, PdfPage, SignPage, BatchPage)) else cls(theme) for cls in PAGE_CLASSES
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
        self.tour: TourOverlay | None = None
        home = self.page("home")
        assert isinstance(home, HomePage)
        home.openPage.connect(self.show_page)
        home.tourRequested.connect(self.start_tour)
        signature, sign = self.page("signature"), self.page("sign")
        assert isinstance(signature, SignaturePage) and isinstance(sign, SignPage)
        signature.signatureMade.connect(sign.set_last_signature)

        settings = self.page("settings")
        assert isinstance(settings, SettingsPage)
        settings.tourRequested.connect(self.start_tour)
        settings.shortcutsRequested.connect(self.show_shortcuts)
        self._shortcuts_dialog: ShortcutsDialog | None = None
        self._remember_presets()
        self._make_shortcuts()

        self.toasts = ToastHost(root, theme)
        for card in root.findChildren(ResultCard) + root.findChildren(PdfResultCard):
            card.saved.connect(self._on_saved)

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
        if index != self.stack.currentIndex():
            self._crossfade()
        self.stack.setCurrentIndex(index)
        self.sidebar.set_current(index)
        log.debug("Showing page %s", self.pages[index].PAGE_ID)

    def _crossfade(self) -> None:
        """Bring the new page in by fading away a plain cover in the window's
        background colour. The old page is never shown semi-transparent (a
        fading snapshot of it left a "ghost" over the new page), and the new
        page is live and clickable straight away."""
        if not motion.enabled() or not self.stack.isVisible():
            return
        for old in self.stack.findChildren(QWidget, "PageCover"):
            old.deleteLater()  # a quick second click: start again
        cover = QWidget(self.stack)
        cover.setObjectName("PageCover")
        cover.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        cover.setGeometry(self.stack.rect())
        cover.show()
        cover.raise_()
        motion.fade_out_and_delete(cover, motion.NORMAL_MS)

    def page(self, page_id: str) -> BasePage:
        """The page object with ``page_id`` (raises ``KeyError`` if unknown)."""
        for candidate in self.pages:
            if candidate.PAGE_ID == page_id:
                return candidate
        raise KeyError(page_id)

    # ----- guided tour -------------------------------------------------
    def tour_steps(self) -> list[TourStep]:
        sidebar = self.sidebar
        nav = dict(zip(self.page_ids(), sidebar.nav_buttons, strict=True))
        photo, pdf = self.page("photo"), self.page("pdf")
        go = self.show_page
        return [
            TourStep(
                "Welcome to Docly",
                "Pick a tool on the left. Home brings you back to this page any time.",
                lambda: [nav[i] for i in ("home", "photo", "signature", "pdf", "batch")],
                lambda: go("home"),
            ),
            TourStep(
                "1. Choose your portal",
                "Search for your exam, visa or form. Docly then knows the exact pixels, shape and KB limit.",
                lambda: [photo.picker.parentWidget()],
                lambda: (go("photo"), photo.side_scroll.ensureWidgetVisible(photo.picker.parentWidget())),
            ),
            TourStep(
                "2. Drop your photo",
                "Drag a photo here or click to browse, then drag the frame to crop. Need a white or light-blue "
                "background? Pick it under Background. Your original is never changed.",
                lambda: [photo.stack],
                lambda: go("photo"),
            ),
            TourStep(
                "3. Check and save",
                "“Ready to upload” means every rule is met. Save puts the result in a Docly_Output folder next to your photo.",
                lambda: [photo.result_card],
                lambda: (go("photo"), photo.side_scroll.ensureWidgetVisible(photo.result_card)),
            ),
            TourStep(
                "Signatures",
                "Photograph your signature on paper. Docly whitens the paper, darkens the ink and trims it to size.",
                lambda: [nav["signature"]],
            ),
            TourStep(
                "PDFs",
                "Combine PDFs and photos, drag pages into order, split them, and shrink to a size limit. "
                "Fill & Sign (next in the list) types on forms and adds your signature.",
                lambda: [pdf.stack, nav["sign"]],
                lambda: go("pdf"),
            ),
            TourStep(
                "You're all set",
                "Switch dark mode here. Restart this tour any time from Home or About.",
                lambda: [sidebar.theme_button, sidebar.about_button],
                lambda: go("home"),
            ),
        ]

    def start_tour(self) -> TourOverlay:
        """Show the guided tour (replacing one already running)."""
        if self._about is not None and self._about.isVisible():
            self._about.accept()
        if self.tour is not None:
            self.tour.skip()
        self.tour = TourOverlay(self.centralWidget(), self.tour_steps(), self.theme)
        self.tour.finished.connect(self._on_tour_finished)
        self.tour.start()
        log.info("Tour started")
        return self.tour

    def maybe_start_tour(self) -> bool:
        """Start the tour on first launch only. Returns True if it started."""
        if self.theme.store.tour_seen():
            return False
        self.start_tour()
        return True

    def _on_tour_finished(self, completed: bool) -> None:
        self.theme.store.set_tour_seen(True)
        self.tour = None
        log.info("Tour %s", "completed" if completed else "skipped")

    # ----- keyboard ---------------------------------------------------
    def _make_shortcuts(self) -> None:
        """App-wide keys: Ctrl+1…7 pages, Ctrl+O open, Ctrl+S save, F1 help."""
        self.shortcuts: dict[str, QShortcut] = {}

        def add(keys: str, slot) -> None:  # noqa: ANN001
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(slot)
            self.shortcuts[keys] = shortcut

        for number, page_id in enumerate(self.page_ids()[:9], start=1):
            add(f"Ctrl+{number}", lambda pid=page_id: self.show_page(pid))
        add("Ctrl+O", self.open_on_current_page)
        add("Ctrl+S", self.save_on_current_page)
        add("F1", self.show_shortcuts)

    def current_page(self) -> BasePage:
        return self.pages[self.stack.currentIndex()]

    def open_on_current_page(self) -> None:
        """Ctrl+O: the current page's file picker (Home goes to Photo first)."""
        page = self.current_page()
        if not hasattr(page, "browse"):
            if page.PAGE_ID != "home":
                return
            self.show_page("photo")
            page = self.current_page()
        page.browse()  # type: ignore[attr-defined]

    def save_on_current_page(self) -> bool:
        """Ctrl+S: press the current page's Save button if it's ready."""
        card = getattr(self.current_page(), "result_card", None)
        button = getattr(card, "save_button", None)
        if button is None or not button.isEnabled() or not button.isVisible():
            return False
        button.click()
        return True

    def _about_to_shortcuts(self) -> None:
        if self._about is not None:
            self._about.accept()
        self.show_shortcuts()

    def show_shortcuts(self) -> ShortcutsDialog:
        if self._shortcuts_dialog is None:
            self._shortcuts_dialog = ShortcutsDialog(self.theme, self)
        self._shortcuts_dialog.open()
        return self._shortcuts_dialog

    # ----- remembered presets ---------------------------------------------
    def preset_pickers(self) -> dict[str, PresetPicker]:
        """Every preset picker by a stable key, e.g. ``"batch/1"``."""
        pickers: dict[str, PresetPicker] = {}
        for page in self.pages:
            for index, picker in enumerate(page.findChildren(PresetPicker)):
                pickers[f"{page.PAGE_ID}/{index}"] = picker
        return pickers

    def _remember_presets(self) -> None:
        store = self.theme.store
        for key, picker in self.preset_pickers().items():
            if store.remember_presets():
                last = store.last_preset(key)
                if last is not None and picker.select(last):
                    log.debug("Restored preset %s on %s", last, key)
            picker.presetChanged.connect(lambda preset, k=key: self._on_preset_picked(k, preset))

    def _on_preset_picked(self, key: str, preset: object) -> None:
        store = self.theme.store
        preset_id = getattr(preset, "id", None)
        if store.remember_presets() and preset_id:
            store.set_last_preset(key, preset_id)

    # ----- toasts -----------------------------------------------------
    def _on_saved(self, saved: Path | list[Path]) -> None:
        """A result card saved something: confirm it with a toast."""
        paths = saved if isinstance(saved, list) else [saved]
        if not paths:
            return
        first = paths[0]
        text = f"Saved {first.name}" if len(paths) == 1 else f"Saved {len(paths)} files"
        self.toasts.show(text, "success", "Open folder", lambda: desktop.reveal_in_folder(first))

    # ----- dialogs ----------------------------------------------------
    def show_about(self) -> AboutDialog:
        """Open the About dialog (window-modal, returns immediately)."""
        if self._about is None:
            self._about = AboutDialog(self.theme, self)
            self._about.tourRequested.connect(self.start_tour)
            self._about.shortcutsRequested.connect(self._about_to_shortcuts)
        self._about.open()
        return self._about

    def _apply_tokens(self, tokens: Tokens) -> None:
        self.setWindowIcon(app_icon())
