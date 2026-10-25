"""A rounded search box with a search icon and Docly's own clear button."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QAction, QIcon, QPalette
from PySide6.QtWidgets import QLineEdit, QToolButton, QWidget

from docly.ui.icons import make_icon, render_icon


class SearchField(QLineEdit):
    """``QLineEdit`` with a leading search icon and a trailing clear (x) button
    that appears only when there is text. Icons follow the palette, so they
    recolour with the theme without needing the ThemeManager."""

    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SearchField")
        self.setPlaceholderText(placeholder)
        self.search_action = QAction(self)
        self.search_action.setEnabled(False)  # decoration only
        self.addAction(self.search_action, QLineEdit.ActionPosition.LeadingPosition)
        self.clear_action = QAction("Clear search", self)
        self.clear_action.setToolTip("Clear search")
        self.clear_action.triggered.connect(self._clear)
        self.addAction(self.clear_action, QLineEdit.ActionPosition.TrailingPosition)
        self.search_action.setText("Search")
        # The line edit turns each action into a small tool button; name them for screen readers.
        for button in self.findChildren(QToolButton):
            action = button.defaultAction()
            if action is not None:
                button.setAccessibleName(action.text())
                button.setToolTip(action.toolTip() or action.text())
        self.textChanged.connect(self._update_clear)
        self._paint_icons()
        self._update_clear(self.text())

    def _clear(self) -> None:
        self.clear()
        self.setFocus()

    def _update_clear(self, text: str) -> None:
        self.clear_action.setVisible(bool(text))

    def _paint_icons(self) -> None:
        colour = self.palette().color(QPalette.ColorRole.PlaceholderText).name()
        dpr = self.devicePixelRatioF()
        # Disabled actions draw their icon greyed; give both modes the same pixmap.
        search = QIcon()
        pixmap = render_icon("search", colour, 16, dpr)
        search.addPixmap(pixmap, QIcon.Mode.Normal)
        search.addPixmap(pixmap, QIcon.Mode.Disabled)
        self.search_action.setIcon(search)
        self.clear_action.setIcon(make_icon("x", colour, 16, dpr))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icons()
        super().changeEvent(event)
