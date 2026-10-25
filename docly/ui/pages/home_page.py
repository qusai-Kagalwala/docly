"""Home page: what Docly does, a card per tool, how it works, and who made it."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docly import config
from docly.ui.icons import make_icon, render_icon
from docly.ui.pages.base_page import BasePage
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.card import Card


@dataclass(frozen=True)
class Feature:
    page_id: str
    icon: str
    title: str
    text: str
    ready: bool = True


FEATURES: tuple[Feature, ...] = (
    Feature("photo", "image", "Photo", "Crop and resize a photo to any portal's rules, and hit its KB limit."),
    Feature("signature", "pen-line", "Signature", "Clean up a phone photo of your signature: white or see-through background."),
    Feature("pdf", "file-text", "PDF", "Merge, reorder, split and shrink PDFs and photos to a size limit."),
    Feature("batch", "layers", "Batch", "Prepare many files at once with one preset.", ready=False),
)

STEPS: tuple[tuple[str, str], ...] = (
    ("Pick your portal", "Choose the exam, visa or form. Docly knows its size, shape and KB limits."),
    ("Drop your file", "Drag a photo, signature or PDF in. Your original is never changed."),
    ("Check and save", "✅ means every rule is met. Save puts the result in a Docly_Output folder."),
)


def _link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'


class FeatureCard(Card):
    """A clickable card for one tool.

    Signals:
        activated(str): the tool's page id.
    """

    activated = Signal(str)

    def __init__(self, feature: Feature, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.feature = feature
        self.setProperty("feature", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{feature.title}: {feature.text}")
        self.body.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.icon = QLabel()
        title = QLabel(feature.title)
        title.setProperty("role", "section")
        top.addWidget(self.icon)
        top.addWidget(title)
        top.addStretch(1)
        if not feature.ready:
            chip = QLabel("Coming soon")
            chip.setProperty("chip", "neutral")
            top.addWidget(chip)
        self.body.addLayout(top)

        text = QLabel(feature.text)
        text.setProperty("role", "muted")
        text.setWordWrap(True)
        self.body.addWidget(text)
        self.body.addStretch(1)

        self.open_button = QPushButton("Open")
        self.open_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)  # arrow after the text
        self.open_button.setProperty("variant", "ghost")
        self.open_button.clicked.connect(self.activate)
        row = QHBoxLayout()
        row.addWidget(self.open_button)
        row.addStretch(1)
        self.body.addLayout(row)
        theme.themeChanged.connect(self._paint_icons)
        self._paint_icons(theme.tokens)

    def activate(self) -> None:
        self.activated.emit(self.feature.page_id)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activate()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate()
            return
        super().keyPressEvent(event)

    def _paint_icons(self, tokens: Tokens) -> None:
        dpr = self.devicePixelRatioF()
        self.icon.setPixmap(render_icon(self.feature.icon, tokens.accent, 22, dpr))
        self.open_button.setIcon(make_icon("arrow-right", tokens.text_muted, 16, dpr))


class HomePage(BasePage):
    """The first page: features, how it works, the tour, and credits.

    Signals:
        openPage(str): a feature card was chosen.
        tourRequested(): "Take the tour" was clicked.
    """

    PAGE_ID = "home"
    TITLE = "Home"
    SUBTITLE = "Get your documents upload-ready."
    ICON = "house"

    openPage = Signal(str)
    tourRequested = Signal()

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(theme, parent)
        self.header.hide()  # the welcome card is the header here

        # ----- welcome --------------------------------------------------------
        hero = Card(theme)
        hero.body.setContentsMargins(28, 24, 28, 24)
        row = QHBoxLayout()
        row.setSpacing(18)
        self.mark = QLabel()
        row.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(4)
        title = QLabel("Make photos, signatures and PDFs upload-ready")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        subtitle = QLabel(
            "Pick your exam, visa or admission portal and Docly gets the size, shape and KB limit right. "
            "Works offline. Your files never leave this PC."
        )
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        words.addWidget(title)
        words.addWidget(subtitle)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.tour_button = QPushButton("Take the tour")
        self.tour_button.setProperty("variant", "primary")
        self.start_button = QPushButton("Start with a photo")
        buttons.addWidget(self.tour_button)
        buttons.addWidget(self.start_button)
        buttons.addStretch(1)
        words.addSpacing(8)
        words.addLayout(buttons)
        row.addLayout(words, 1)
        hero.body.addLayout(row)
        self.add_card(hero)

        # ----- tools ----------------------------------------------------------
        self.content.addWidget(_section("Tools"))
        grid = QGridLayout()
        grid.setSpacing(16)
        self.feature_cards: dict[str, FeatureCard] = {}
        for index, feature in enumerate(FEATURES):
            card = FeatureCard(feature, theme)
            card.activated.connect(self.openPage)
            grid.addWidget(card, index // 2, index % 2)
            self.feature_cards[feature.page_id] = card
        self.content.addLayout(grid)

        # ----- how it works -----------------------------------------------------
        self.content.addWidget(_section("How it works"))
        steps = Card(theme)
        steps_row = QHBoxLayout()
        steps_row.setSpacing(20)
        for number, (heading, text) in enumerate(STEPS, start=1):
            column = QVBoxLayout()
            column.setSpacing(6)
            badge = QLabel(str(number))
            badge.setObjectName("StepNumber")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(heading)
            name.setProperty("role", "body")
            name.setStyleSheet("font-weight: 600;")
            info = QLabel(text)
            info.setProperty("role", "muted")
            info.setWordWrap(True)
            column.addWidget(badge)
            column.addWidget(name)
            column.addWidget(info)
            column.addStretch(1)
            steps_row.addLayout(column, 1)
        steps.body.addLayout(steps_row)
        self.add_card(steps)

        # ----- about the creator ----------------------------------------------------
        credits = Card(theme)
        credits.body.setSpacing(4)
        made = QLabel(f"Made by <b>{config.CREATOR_NAME}</b>")
        made.setTextFormat(Qt.TextFormat.RichText)
        made.setProperty("role", "body")
        self.links = QLabel(
            " · ".join(
                (
                    _link(config.CREATOR_GITHUB_URL, "GitHub"),
                    _link(config.CREATOR_LINKEDIN_URL, "LinkedIn"),
                    _link(config.REPO_URL, "Source code"),
                )
            )
        )
        self.links.setTextFormat(Qt.TextFormat.RichText)
        self.links.setOpenExternalLinks(True)  # opens the browser only when clicked
        version = QLabel(f"{config.APP_NAME} {config.APP_VERSION} · Free and open source ({config.APP_LICENSE})")
        version.setProperty("role", "caption")
        credit_row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(made)
        left.addWidget(self.links)
        left.addWidget(version)
        credit_row.addLayout(left, 1)
        self.star_link = QLabel(_link(config.REPO_URL, "⭐ Star Docly on GitHub"))
        self.star_link.setTextFormat(Qt.TextFormat.RichText)
        self.star_link.setOpenExternalLinks(True)
        self.star_link.setProperty("role", "caption")
        self.star_link.setToolTip("If Docly helped you, a star helps others find it.")
        credit_row.addWidget(self.star_link, 0, Qt.AlignmentFlag.AlignBottom)
        credits.body.addLayout(credit_row)
        self.add_card(credits)
        self.finish_layout()

        self.tour_button.clicked.connect(self.tourRequested)
        self.start_button.clicked.connect(lambda: self.openPage.emit("photo"))
        theme.themeChanged.connect(self._paint)
        self._paint(theme.tokens)

    def _paint(self, tokens: Tokens) -> None:
        dpr = self.devicePixelRatioF()
        self.mark.setPixmap(render_icon("docly-mark", tokens.accent, 52, dpr))
        self.tour_button.setIcon(make_icon("compass", tokens.on_accent, 16, dpr))


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label
