"""List of the files whose pages are in the plan, each with a remove button."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from docly.ui.icons import make_icon, render_icon
from docly.ui.theme import ThemeManager, Tokens
from docly.ui.widgets.status_badge import kind_colour


@dataclass(frozen=True)
class FileRow:
    """What the list shows for one file."""

    source: int  # index into the page's sources
    name: str
    pages_used: int
    page_count: int
    is_pdf: bool
    warnings: tuple[str, ...] = ()


class FileList(QWidget):
    """One row per file: name, pages, a warning icon if it had problems, and a remove button.

    Signals:
        removeRequested(int): the source index whose pages should go.
    """

    removeRequested = Signal(int)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = theme.tokens
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.rows: list[FileRow] = []
        self.remove_buttons: dict[int, QToolButton] = {}
        theme.themeChanged.connect(self._apply_tokens)

    def set_rows(self, rows: list[FileRow]) -> None:
        self.rows = list(rows)
        self._rebuild()

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater waits for the event loop; hide it now
                widget.setParent(None)
                widget.deleteLater()
        self.remove_buttons.clear()
        for row in self.rows:
            self._layout.addWidget(self._make_row(row))

    def _make_row(self, row: FileRow) -> QWidget:
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(row.name)
        name.setToolTip(row.name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setMinimumWidth(40)
        details = QLabel(self._details(row))
        details.setProperty("role", "caption")
        text.addWidget(name)
        text.addWidget(details)
        line.addLayout(text, 1)

        if row.warnings:
            badge = QLabel()
            badge.setObjectName("StatusIcon")
            badge.setProperty("kind", "warning")
            badge.setFixedSize(24, 24)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            colour = kind_colour(self._tokens, "warning")
            badge.setPixmap(render_icon("triangle-alert", colour, 14, self.devicePixelRatioF()))
            badge.setToolTip("\n".join(row.warnings))
            badge.setAccessibleName("Warnings")
            line.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        remove = QToolButton()
        remove.setAutoRaise(True)
        remove.setIcon(make_icon("x", self._tokens.text_muted, 16, self.devicePixelRatioF()))
        remove.setToolTip(f"Remove {row.name}'s pages")
        remove.setAccessibleName(f"Remove {row.name}")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda _checked=False, s=row.source: self.removeRequested.emit(s))
        line.addWidget(remove, 0, Qt.AlignmentFlag.AlignVCenter)
        self.remove_buttons[row.source] = remove
        return holder

    @staticmethod
    def _details(row: FileRow) -> str:
        if not row.is_pdf:
            return "Photo · 1 page"
        total = f"{row.page_count} page" + ("" if row.page_count == 1 else "s")
        if row.pages_used == row.page_count:
            return f"PDF · {total}"
        return f"PDF · {row.pages_used} of {total} used"

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._tokens = tokens
        self._rebuild()
