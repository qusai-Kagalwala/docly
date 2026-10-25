"""Page title with the small hand-drawn squiggle underline.

When a page opens, the squiggle draws itself in from the left and ripples
for a couple of seconds, slowing down until it rests in its usual shape.
It stays still when motion is off (Windows "Animation effects" or tests).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from docly.ui import motion
from docly.ui.theme import ThemeManager, Tokens

RIPPLE_MS = 2600
RIPPLE_WAVES = 3  # whole waves travelled, so it ends exactly in the resting shape
DRAW_IN = 0.14  # share of the animation spent drawing the line in


class Squiggle(QWidget):
    """A short wavy accent line, painted with QPainter."""

    WIDTH = 56
    HEIGHT = 8
    AMPLITUDE = 2.2
    HALF_WAVE = 9.0  # px from one crest to the next trough

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(self.WIDTH, self.HEIGHT))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._color = theme.tokens.qcolor("accent")
        self._progress = 1.0  # 1 = at rest
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(RIPPLE_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.valueChanged.connect(self._on_progress)
        theme.themeChanged.connect(self._apply_tokens)

    def play(self) -> None:
        """Draw in and ripple (does nothing when motion is off)."""
        if not motion.enabled():
            return
        self.animation.stop()
        self._progress = 0.0
        self.animation.start()

    @property
    def is_playing(self) -> bool:
        return self.animation.state() == QAbstractAnimation.State.Running

    def _on_progress(self, value: object) -> None:
        self._progress = float(value)  # type: ignore[arg-type]
        self.update()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self._color = tokens.qcolor("accent")
        self.update()

    def wave_state(self) -> tuple[float, float, float]:
        """(visible share of the line, wave phase, amplitude) for the current frame."""
        t = self._progress
        reveal = QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(min(1.0, t / DRAW_IN))
        # The wave travels fast at first and glides to a stop on a whole wave.
        phase = -2 * math.pi * RIPPLE_WAVES * QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(t)
        # A little livelier while moving, settling back to the normal height.
        amplitude = self.AMPLITUDE * (1.0 + 0.2 * (1.0 - t))
        return reveal, phase, amplitude

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        reveal, phase, amplitude = self.wave_state()
        mid = self.height() / 2
        left, right = 2.0, self.width() - 2.0
        end = left + (right - left) * reveal
        path = QPainterPath()
        x = left
        while True:
            y = mid - amplitude * math.sin(math.pi * (x - left) / self.HALF_WAVE + phase)
            if x == left:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))
            if x >= end:
                break
            x = min(end, x + 0.5)
        if reveal > 0:
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

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        # Only when the page opens — not when the window is restored from the taskbar.
        if not event.spontaneous():
            self.squiggle.play()
