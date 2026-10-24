"""Page title with the small hand-drawn squiggle underline."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from docly.ui.theme import ThemeManager, Tokens


class Squiggle(QWidget):
    """A short wavy accent line, painted with QPainter."""

    WIDTH = 56
    HEIGHT = 8

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(self.WIDTH, self.HEIGHT))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._color = theme.tokens.qcolor("accent")
        theme.themeChanged.connect(self._apply_tokens)

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._color = tokens.qcolor("accent")
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        mid = self.height() / 2
        amp = 2.2
        step = 9.0
        x = 2.0
        path = QPainterPath(QPointF(x, mid))
        up = True
        while x + step <= self.width() - 2:
            dy = -amp if up else amp
            path.quadTo(QPointF(x + step / 2, mid + dy * 2), QPointF(x + step, mid))
            x += step
            up = not up
        painter.drawPath(path)
        painter.end()


class PageHeader(QWidget):
    """Title (20px semibold), squiggle, and an optional muted subtitle."""

    def __init__(self, title: str, subtitle: str, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "title")
        self.title_label.setAccessibleName(title)
        layout.addWidget(self.title_label)

        self.squiggle = Squiggle(theme)
        layout.addWidget(self.squiggle)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "muted")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addSpacing(4)
        layout.addWidget(self.subtitle_label)
