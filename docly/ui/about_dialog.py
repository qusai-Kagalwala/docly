"""About Docly dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from docly import config
from docly.ui.icons import render_icon
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.card import Card


class AboutDialog(QDialog):
    """Name, version, creator, licence and the offline promise.

    Signals:
        tourRequested(): "Take the tour" was clicked.
    """

    tourRequested = Signal()
    shortcutsRequested = Signal()

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutDialog")
        self.setWindowTitle(f"About {config.APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(440)  # grows for wider Windows fonts
        # Remove the "?" help button some Windows dialogs show.
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        card = Card(theme)
        card.body.setContentsMargins(28, 28, 28, 22)
        card.body.setSpacing(6)
        outer.addWidget(card)

        self._mark = QLabel()
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(self._mark)
        card.body.addSpacing(4)

        name = QLabel(config.APP_NAME)
        name.setProperty("role", "title")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(name)

        tagline = QLabel(config.APP_TAGLINE)
        tagline.setProperty("role", "muted")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(tagline)

        version_row = QHBoxLayout()
        version_row.addStretch(1)
        self.version_chip = QLabel(f"Version {config.APP_VERSION}")
        self.version_chip.setProperty("chip", "neutral")
        version_row.addWidget(self.version_chip)
        version_row.addStretch(1)
        card.body.addSpacing(6)
        card.body.addLayout(version_row)
        card.body.addSpacing(10)

        offline = QLabel("Works fully offline. Docly makes no network calls and collects no data.")
        offline.setProperty("role", "body")
        offline.setWordWrap(True)
        offline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(offline)
        card.body.addSpacing(6)

        self.link_label = QLabel(f'<a href="{config.REPO_URL}">github.com/qusai-Kagalwala/docly</a>')
        self.link_label.setTextFormat(Qt.TextFormat.RichText)
        self.link_label.setOpenExternalLinks(True)  # opens in the browser only when clicked
        self.link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(self.link_label)

        made = QLabel(f"Made by {config.CREATOR_NAME}")
        made.setProperty("role", "body")
        made.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.body.addWidget(made)

        credits = QLabel(
            f"Released under the {config.APP_LICENSE} licence · Icons by Lucide (ISC) · "
            "Portrait model MODNet (Apache-2.0)"
        )
        credits.setProperty("role", "caption")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setWordWrap(True)
        card.body.addWidget(credits)

        buttons = QHBoxLayout()
        self.tour_button = QPushButton("Take the tour")
        self.tour_button.setObjectName("about_tour")
        self.tour_button.clicked.connect(self.tourRequested)
        buttons.addWidget(self.tour_button)
        self.shortcuts_button = QPushButton("Keyboard shortcuts")
        self.shortcuts_button.setObjectName("about_shortcuts")
        self.shortcuts_button.setToolTip("F1")
        self.shortcuts_button.clicked.connect(self.shortcutsRequested)
        buttons.addWidget(self.shortcuts_button)
        self.licences_button = QPushButton("Open-source licences")
        self.licences_button.setObjectName("about_licences")
        self.licences_button.clicked.connect(self.show_licences)
        buttons.addWidget(self.licences_button)
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("about_close")
        self.close_button.setProperty("variant", "primary")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        outer.addSpacing(4)
        outer.addLayout(buttons)

        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    def show_licences(self) -> LicencesDialog:
        dialog = LicencesDialog(self)
        dialog.open()
        return dialog

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._mark.setPixmap(render_icon("docly-mark", tokens.accent, 48, self.devicePixelRatioF()))


def read_notices() -> str:
    try:
        return config.NOTICES_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "The licence file is missing from this copy of Docly.\n"
            f"See {config.REPO_URL} for the licences of the software Docly uses."
        )


class LicencesDialog(QDialog):
    """The licences of everything packaged with Docly (read-only text)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LicencesDialog")
        self.setWindowTitle("Open-source licences")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        intro = QLabel(
            f"{config.APP_NAME} is free software under the {config.APP_LICENSE} licence. "
            "It is built on the open-source projects below."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "body")
        layout.addWidget(intro)
        self.text = QPlainTextEdit(read_notices())
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.text.setAccessibleName("Licence texts")
        layout.addWidget(self.text, 1)
        close = QPushButton("Close")
        close.setProperty("variant", "primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
