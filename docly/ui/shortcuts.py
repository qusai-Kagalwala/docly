"""Keyboard shortcuts: the list shown to people, and the dialog that shows it.

Desktop note: a ``QShortcut`` listens for a key combination while its
window is active. The app-wide ones are created in :class:`MainWindow`;
page-specific ones (Delete, Ctrl+Z, Ctrl+R…) live on the pages and only
work while that part of the page has focus.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docly import config
from docly.ui.theme import ThemeManager
from docly.ui.widgets.card import Card

#: (section, [(keys, what it does)]) — what the dialog lists.
SHORTCUTS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Anywhere",
        (
            ("Ctrl+1 … Ctrl+7", "Go to Home, Photo, Signature, PDF, Fill & Sign, Batch, Settings"),
            ("Ctrl+O", "Open a file on the current page"),
            ("Ctrl+S", "Save the result on the current page"),
            ("F1", "Show this list"),
        ),
    ),
    (
        "PDF pages",
        (
            ("Ctrl+R / Ctrl+Shift+R", "Turn selected pages right / left"),
            ("Ctrl+D", "Duplicate selected pages"),
            ("Delete", "Delete selected pages"),
            ("Ctrl+A", "Select all pages"),
            ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
        ),
    ),
    (
        "Fill & Sign",
        (
            ("Double-click text", "Type on the page"),
            ("Ctrl+Enter or Esc", "Finish typing / put the text back"),
            ("Arrow keys (Shift = 10 pt)", "Nudge the selected item"),
            ("Delete", "Remove the selected item"),
            ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
        ),
    ),
)


class ShortcutsDialog(QDialog):
    """A small window listing every shortcut."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ShortcutsDialog")
        self.setWindowTitle(f"{config.APP_NAME} keyboard shortcuts")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        card = Card(theme)
        card.body.setSpacing(4)
        outer.addWidget(card)
        title = QLabel("Keyboard shortcuts")
        title.setProperty("role", "title")
        card.body.addWidget(title)
        self.rows: list[tuple[str, str]] = []
        # One grid for every section, so the descriptions line up.
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        row = 0
        for section, entries in SHORTCUTS:
            heading = QLabel(section)
            heading.setProperty("role", "section")
            grid.addWidget(heading, row, 0, 1, 2)
            grid.setRowMinimumHeight(row, 34)
            row += 1
            for keys, action in entries:
                key_label = QLabel(keys)
                key_label.setObjectName("ShortcutKeys")
                text = QLabel(action)
                text.setProperty("role", "body")
                text.setWordWrap(True)
                grid.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                grid.addWidget(text, row, 1)
                self.rows.append((keys, action))
                row += 1
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        close = QPushButton("Close")
        close.setProperty("variant", "primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        card.body.addSpacing(12)
        card.body.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.setMinimumWidth(520)
