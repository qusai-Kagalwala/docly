"""Shared page layout: header + scrollable column of cards."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from docly.ui.icons import render_icon
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.card import Card
from docly.ui.widgets.page_header import PageHeader

PAGE_PADDING = 24
CARD_GAP = 16


class BasePage(QWidget):
    """Base class for every sidebar page.

    Subclasses set the class attributes and add cards with
    :meth:`add_card`. Content scrolls, so small windows never break the
    layout.
    """

    PAGE_ID: str = ""
    TITLE: str = ""
    SUBTITLE: str = ""
    ICON: str = "info"
    #: False for pages that manage their own scrolling (e.g. a photo that
    #: should fill the window rather than scroll with the page).
    SCROLLS: bool = True

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"page_{self.PAGE_ID}")
        self.theme = theme

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        body.setObjectName("PageBody")
        if self.SCROLLS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(body)
            outer.addWidget(scroll)
        else:
            outer.addWidget(body)

        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(PAGE_PADDING, PAGE_PADDING, PAGE_PADDING, PAGE_PADDING)
        self.content.setSpacing(CARD_GAP)

        self.header = PageHeader(self.TITLE, self.SUBTITLE, theme)
        self.content.addWidget(self.header)
        self._stretch_added = False

    def add_card(self, card: Card) -> Card:
        """Append a card to the page column."""
        self.content.addWidget(card)
        return card

    def finish_layout(self) -> None:
        """Push content to the top. Call once after adding cards."""
        if not self._stretch_added:
            self.content.addStretch(1)
            self._stretch_added = True


class EmptyStateCard(Card):
    """Placeholder card: large muted icon, heading, hint and a status chip."""

    def __init__(self, theme: ThemeManager, icon: str, heading: str, text: str, chip: str = "") -> None:
        super().__init__(theme)
        self.setMinimumHeight(260)
        self._icon_name = icon
        self.body.setContentsMargins(32, 40, 32, 40)
        self.body.setSpacing(10)
        self.body.addStretch(1)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.icon_label)

        heading_label = QLabel(heading)
        heading_label.setProperty("role", "section")
        heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(heading_label)

        text_label = QLabel(text)
        text_label.setProperty("role", "muted")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label.setWordWrap(True)
        self.body.addWidget(text_label)

        if chip:
            chip_row = QHBoxLayout()
            chip_row.addStretch(1)
            chip_label = QLabel(chip)
            chip_label.setProperty("chip", "neutral")
            chip_row.addWidget(chip_label)
            chip_row.addStretch(1)
            self.body.addSpacing(4)
            self.body.addLayout(chip_row)
        self.body.addStretch(1)

        theme.themeChanged.connect(self._refresh_icon)
        self._refresh_icon(theme.tokens)

    def _refresh_icon(self, tokens: Tokens) -> None:
        self.icon_label.setPixmap(render_icon(self._icon_name, tokens.text_muted, 44, self.devicePixelRatioF()))


class SideColumn(QScrollArea):
    """The scrolling settings column on the right of a tool page.

    It is ``base_width`` wide, but grows when its cards need more room
    instead of cutting them off. Windows' Segoe UI is noticeably wider than
    other fonts, and display scaling or a user's larger text setting widens
    it further, so a fixed pixel width isn't safe.

    Add cards to :attr:`column` (a ``QVBoxLayout``).
    """

    def __init__(self, base_width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base = base_width
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("PageBody")
        self.column = QVBoxLayout(inner)
        self.column.setSpacing(CARD_GAP)
        # Room on the right for the scrollbar and on the edges for card shadows.
        self.column.setContentsMargins(2, 0, 12, 4)
        self.setWidget(inner)
        # Qt sends LayoutRequest whenever the cards' sizes may have changed
        # (text, visibility, fonts), so the column re-measures itself then.
        inner.installEventFilter(self)
        self.fit()

    def needed_width(self) -> int:
        scrollbar = self.verticalScrollBar().sizeHint().width()
        return self.widget().minimumSizeHint().width() + scrollbar + 2

    def fit(self) -> None:
        width = max(self._base, self.needed_width())
        if self.minimumWidth() != width or self.maximumWidth() != width:
            self.setFixedWidth(width)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self.fit()
        return super().eventFilter(watched, event)
