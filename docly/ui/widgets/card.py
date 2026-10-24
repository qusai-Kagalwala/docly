"""Card: the basic surface used on every page."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from docly.ui.theme import ThemeManager, Tokens

SHADOW_BLUR = 20
SHADOW_OFFSET_Y = 2


class Card(QFrame):
    """A rounded surface with a 1px border and a soft shadow.

    Add content to :attr:`body` (a ``QVBoxLayout``). Styling comes from the
    ``#Card`` rule in the stylesheet; only the shadow is set here, because
    QSS cannot draw shadows.
    """

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None, shadow: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(10)

        self._shadow: QGraphicsDropShadowEffect | None = None
        if shadow:
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(SHADOW_BLUR)
            self._shadow.setOffset(0, SHADOW_OFFSET_Y)
            self.setGraphicsEffect(self._shadow)
        theme.themeChanged.connect(self._apply_tokens)
        self._apply_tokens(theme.tokens)

    def _apply_tokens(self, tokens: Tokens) -> None:
        if self._shadow is not None:
            self._shadow.setColor(tokens.qcolor("shadow", 70 if tokens.is_dark else 20))
