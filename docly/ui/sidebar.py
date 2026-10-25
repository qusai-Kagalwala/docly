"""Left sidebar: brand, page navigation, theme toggle and About."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from docly import config
from docly.ui import motion
from docly.ui.icons import render_icon
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.nav_button import BAR_INSET, BAR_WIDTH, NavButton


@dataclass(frozen=True)
class NavItem:
    """One entry in the sidebar."""

    page_id: str
    label: str
    icon: str


class Sidebar(QFrame):
    """Navigation sidebar.

    Signals:
        pageRequested(int): user clicked the nav item at this index.
        aboutRequested(): user clicked About.
    """

    pageRequested = Signal(int)
    aboutRequested = Signal()

    def __init__(self, items: list[NavItem], theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(config.SIDEBAR_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 18, 10, 14)
        layout.setSpacing(2)

        # Brand row: app mark + name.
        brand = QHBoxLayout()
        brand.setContentsMargins(10, 0, 0, 0)
        brand.setSpacing(10)
        self._mark = QLabel()
        self._mark.setFixedSize(24, 24)
        self._brand_label = QLabel(config.APP_NAME)
        self._brand_label.setObjectName("SidebarBrand")
        brand.addWidget(self._mark)
        brand.addWidget(self._brand_label)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(22)

        # Page navigation (exclusive: exactly one checked).
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.nav_buttons: list[NavButton] = []
        for index, item in enumerate(items):
            button = NavButton(item.label, item.icon, theme)
            button.setObjectName(f"nav_{item.page_id}")
            button.setToolTip(item.label)
            self._group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self._group.idClicked.connect(self.pageRequested)
        # One accent bar that slides between items (instead of each button drawing its own).
        self.indicator = QFrame(self)
        self.indicator.setObjectName("NavIndicator")
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.indicator.hide()
        for button in self.nav_buttons:
            button.paint_bar = False

        layout.addStretch(1)
        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        layout.addWidget(divider)
        layout.addSpacing(8)

        # Bottom actions.
        self.theme_button = NavButton("", "moon", theme, checkable=False)
        self.theme_button.setObjectName("theme_toggle")
        self.theme_button.clicked.connect(theme.toggle)
        layout.addWidget(self.theme_button)

        self.about_button = NavButton("About", "info", theme, checkable=False)
        self.about_button.setObjectName("about_button")
        self.about_button.clicked.connect(self.aboutRequested)
        layout.addWidget(self.about_button)

        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    def set_current(self, index: int) -> None:
        """Highlight the nav item at ``index`` without emitting a signal."""
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
            self._place_indicator(animate=True)

    def indicator_target(self) -> QRect | None:
        """Where the sliding bar belongs: beside the checked item."""
        button = self._group.checkedButton()
        if button is None:
            return None
        geometry = button.geometry()
        return QRect(geometry.x() + 1, geometry.y() + BAR_INSET, int(BAR_WIDTH), geometry.height() - 2 * BAR_INSET)

    def _place_indicator(self, animate: bool) -> None:
        target = self.indicator_target()
        if target is None:
            self.indicator.hide()
            return
        if animate and self.indicator.isVisible():
            motion.slide_geometry(self.indicator, target, motion.NORMAL_MS)
        else:
            self.indicator.setGeometry(target)
        self.indicator.show()
        self.indicator.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_indicator(animate=False)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._place_indicator(animate=False)

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._mark.setPixmap(render_icon("docly-mark", tokens.accent, 24, self.devicePixelRatioF()))
        if tokens.is_dark:
            self.theme_button.set_content("Light mode", "sun")
            self.theme_button.setToolTip("Switch to light mode")
        else:
            self.theme_button.set_content("Dark mode", "moon")
            self.theme_button.setToolTip("Switch to dark mode")
