"""Guided tour: dim the window, spotlight one area, explain it in a bubble.

Desktop concept — *overlay widget*: the tour is a transparent widget laid
over the whole window. It paints a dark veil with a hole cut around the
part being explained, and catches clicks so nothing underneath is pressed
by accident. It follows the window when it is resized.

Each :class:`TourStep` names its target with a function (the widget may
only exist or be visible after ``before`` switches page).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from docly.ui import motion
from docly.ui.theme import ThemeManager, Tokens

SPOT_PADDING = 8
BUBBLE_WIDTH = 330
BUBBLE_GAP = 16
EDGE = 12


@dataclass(frozen=True)
class TourStep:
    """One stop on the tour."""

    title: str
    text: str
    targets: Callable[[], Sequence[QWidget]]  # highlighted together (their combined area)
    before: Callable[[], None] | None = None  # e.g. switch to the right page


class TourBubble(QFrame):
    """The speech bubble: step count, title, text, Back / Next / Skip."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("TourBubble")
        self.setFixedWidth(BUBBLE_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(6)
        self.counter = QLabel()
        self.counter.setProperty("role", "caption")
        self.title = QLabel()
        self.title.setProperty("role", "section")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setProperty("role", "body")
        self.text.setWordWrap(True)
        layout.addWidget(self.counter)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip_button = QPushButton("Skip tour")
        self.skip_button.setProperty("variant", "ghost")
        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.next_button.setProperty("variant", "primary")
        self.next_button.setDefault(True)
        buttons.addWidget(self.skip_button)
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)


class TourOverlay(QWidget):
    """Runs a list of :class:`TourStep` over ``host`` (usually the window's central widget).

    Signals:
        finished(bool): True if the user reached the end, False if skipped.
        stepChanged(int): the step now shown (0-based).
    """

    finished = Signal(bool)
    stepChanged = Signal(int)

    def __init__(self, host: QWidget, steps: Sequence[TourStep], theme: ThemeManager) -> None:
        super().__init__(host)
        if not steps:
            raise ValueError("A tour needs at least one step")
        self.setObjectName("TourOverlay")
        self.steps = list(steps)
        self.index = 0
        self.tokens: Tokens = theme.tokens
        self.spot = QRect()
        self._glide: QPropertyAnimation | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Docly tour")

        self.bubble = TourBubble(self)
        self.bubble.next_button.clicked.connect(self.next)
        self.bubble.back_button.clicked.connect(self.back)
        self.bubble.skip_button.clicked.connect(self.skip)
        host.installEventFilter(self)
        theme.themeChanged.connect(self._apply_tokens)

    # ----- control ----------------------------------------------------------
    def start(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.go_to(0)

    def go_to(self, index: int) -> None:
        self.index = max(0, min(index, len(self.steps) - 1))
        step = self.steps[self.index]
        if step.before is not None:
            step.before()
        b = self.bubble
        b.counter.setText(f"Step {self.index + 1} of {len(self.steps)}")
        b.title.setText(step.title)
        b.text.setText(step.text)
        b.back_button.setEnabled(self.index > 0)
        last = self.index == len(self.steps) - 1
        b.next_button.setText("Done" if last else "Next")
        b.skip_button.setVisible(not last)
        self.relayout()
        # Pages switched by ``before`` lay themselves out on the next pass.
        QTimer.singleShot(0, self, self.relayout)  # cancelled if the tour closes first
        self.stepChanged.emit(self.index)

    def next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self._close(True)
        else:
            self.go_to(self.index + 1)

    def back(self) -> None:
        if self.index > 0:
            self.go_to(self.index - 1)

    def skip(self) -> None:
        self._close(False)

    # ----- geometry -----------------------------------------------------------
    def target_rect(self) -> QRect:
        """Area of the current step's widgets, in overlay coordinates."""
        area = QRect()
        for widget in self.steps[self.index].targets():
            if widget is None or not widget.isVisible():
                continue
            top_left = widget.mapTo(self.parentWidget(), QPoint(0, 0))
            area = area.united(QRect(top_left, widget.size()))
        if area.isNull():
            return QRect()
        padded = area.adjusted(-SPOT_PADDING, -SPOT_PADDING, SPOT_PADDING, SPOT_PADDING)
        return padded.intersected(self.rect().adjusted(EDGE // 2, EDGE // 2, -EDGE // 2, -EDGE // 2))

    def relayout(self, animate: bool = True) -> None:
        """Re-measure the spotlight and place the bubble (gliding to it
        between steps; jumping straight there when the window resizes)."""
        if self.parentWidget() is None:
            return
        self.setGeometry(self.parentWidget().rect())
        self.spot = self.target_rect()
        # Wrapped text needs its height worked out for the bubble's fixed width.
        layout = self.bubble.layout()
        layout.activate()
        height = layout.totalHeightForWidth(BUBBLE_WIDTH) if layout.hasHeightForWidth() else self.bubble.sizeHint().height()
        self.bubble.resize(BUBBLE_WIDTH, max(height, self.bubble.minimumSizeHint().height()))
        target = self._bubble_position(self.bubble.width(), self.bubble.height())
        if self._glide is not None:
            try:
                self._glide.stop()  # deletes itself when stopped
            except RuntimeError:
                pass
            self._glide = None
        if animate and self.bubble.pos() != target:
            self._glide = motion.move_to(self.bubble, target, motion.NORMAL_MS)
        else:
            self.bubble.move(target)
        self.update()

    def _bubble_position(self, width: int, height: int) -> QPoint:
        area = self.rect().adjusted(EDGE, EDGE, -EDGE, -EDGE)
        spot = self.spot

        def clamp_x(x: int) -> int:
            return max(area.left(), min(x, area.right() - width))

        def clamp_y(y: int) -> int:
            return max(area.top(), min(y, area.bottom() - height))

        if spot.isNull():  # nothing to point at: centre the bubble
            return QPoint(area.center().x() - width // 2, area.center().y() - height // 2)
        candidates = [
            QPoint(spot.right() + BUBBLE_GAP, clamp_y(spot.top())),  # right
            QPoint(spot.left() - BUBBLE_GAP - width, clamp_y(spot.top())),  # left
            QPoint(clamp_x(spot.left()), spot.bottom() + BUBBLE_GAP),  # below
            QPoint(clamp_x(spot.left()), spot.top() - BUBBLE_GAP - height),  # above
        ]
        for point in candidates:
            box = QRect(point.x(), point.y(), width, height)
            if area.contains(box) and not box.intersects(spot):
                return point
        # Big targets: sit inside the spotlight's bottom-right corner, clamped.
        return QPoint(clamp_x(spot.right() - width - EDGE), clamp_y(spot.bottom() - height - EDGE))

    # ----- painting & input ---------------------------------------------------------
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        veil = QPainterPath()
        veil.addRect(QRectF(self.rect()))
        if not self.spot.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self.spot), 10, 10)
            veil = veil.subtracted(hole)
        painter.fillPath(veil, QColor(0, 0, 0, 150 if self.tokens.is_dark else 120))
        if not self.spot.isNull():
            painter.setPen(QPen(QColor(self.tokens.accent), 2))
            painter.drawRoundedRect(QRectF(self.spot), 10, 10)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        event.accept()  # the tour is in charge; clicks don't reach the app underneath

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.skip()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.next()
        elif key == Qt.Key.Key_Left:
            self.back()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.relayout(animate=False)
        return super().eventFilter(watched, event)

    # ----- internals ------------------------------------------------------------------
    def _close(self, completed: bool) -> None:
        if self.parentWidget() is not None:
            self.parentWidget().removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    def _apply_tokens(self, tokens: Tokens) -> None:
        self.tokens = tokens
        self.update()
