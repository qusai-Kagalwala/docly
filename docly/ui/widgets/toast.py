"""Toasts: a short message that floats at the bottom of the window.

"Saved photo_ibps.jpg · Open folder" appears for a few seconds and fades
away. Hovering keeps it open. Only one toast shows at a time; a new one
replaces the old.

Desktop note: a toast is an *overlay* — a child widget positioned by hand
on top of the page, not part of any layout — so it never pushes the page
content around. The host re-positions it when the window resizes.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from docly.ui import motion
from docly.ui.icons import make_icon, render_icon
from docly.ui.theme import ThemeManager
from docly.ui.widgets.status_badge import ICONS, kind_colour
from docly.ui.widgets.style import set_style_prop

SHOW_MS = 4000
MARGIN = 24
MAX_WIDTH = 520


class Toast(QFrame):
    """One toast. Create through :class:`ToastHost`."""

    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.label = QLabel()
        self.label.setObjectName("ToastText")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setMaximumWidth(MAX_WIDTH - 180)
        self.action_button = QPushButton()
        self.action_button.setProperty("variant", "ghost")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("Dismiss")
        self.close_button.setAccessibleName("Dismiss")
        layout.addWidget(self.icon)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.action_button)
        layout.addWidget(self.close_button)
        self.kind = "success"
        self._action: Callable[[], None] | None = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.action_button.clicked.connect(self._run_action)
        self.close_button.clicked.connect(self.dismiss)
        theme.themeChanged.connect(lambda _t: self._paint())
        self.hide()

    def text(self) -> str:
        return self.label.text()

    def set_content(self, text: str, kind: str, action_text: str | None, action: Callable[[], None] | None) -> None:
        self.kind = kind
        self.label.setText(text)
        self.label.setToolTip(text)
        self._action = action
        self.action_button.setText(action_text or "")
        self.action_button.setVisible(bool(action_text and action))
        set_style_prop(self, "kind", kind)
        self.setAccessibleName(text)
        self._paint()

    def _paint(self) -> None:
        tokens = self._theme.tokens
        dpr = self.devicePixelRatioF()
        self.icon.setPixmap(render_icon(ICONS.get(self.kind, "info"), kind_colour(tokens, self.kind), 18, dpr))
        self.close_button.setIcon(make_icon("x", tokens.text_muted, 14, dpr))

    def _run_action(self) -> None:
        if self._action is not None:
            self._action()
        self.dismiss()

    def dismiss(self) -> None:
        self.timer.stop()
        self.hide()

    # Keep the toast open while the pointer is over it.
    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        if self.isVisible():
            self.timer.start(SHOW_MS // 2)
        super().leaveEvent(event)


class ToastHost(QObject):
    """Shows toasts over ``window`` (usually the main window's central widget)."""

    def __init__(self, window: QWidget, theme: ThemeManager) -> None:
        super().__init__(window)
        self._window = window
        self.toast = Toast(theme, window)
        window.installEventFilter(self)

    def show(
        self,
        text: str,
        kind: str = "success",
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
        duration: int = SHOW_MS,
    ) -> Toast:
        toast = self.toast
        toast.set_content(text, kind, action_text, action)
        toast.adjustSize()
        toast.raise_()
        end = self._resting_point()
        if motion.enabled() and not toast.isVisible():
            toast.move(end + QPoint(0, 16))
            motion.fade_in(toast, motion.NORMAL_MS)
            motion.move_to(toast, end, motion.NORMAL_MS)
        else:
            toast.move(end)
            toast.show()
        toast.timer.start(duration)
        return toast

    def _resting_point(self) -> QPoint:
        toast = self.toast
        width = min(toast.sizeHint().width(), MAX_WIDTH, self._window.width() - 2 * MARGIN)
        toast.resize(width, toast.sizeHint().height())
        # Centred over the page area (to the right of the sidebar).
        sidebar = self._window.findChild(QWidget, "Sidebar")
        left = sidebar.width() if sidebar is not None and sidebar.isVisible() else 0
        x = left + (self._window.width() - left - toast.width()) // 2
        y = self._window.height() - toast.height() - MARGIN
        return QPoint(max(MARGIN, x), max(MARGIN, y))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._window and event.type() == QEvent.Type.Resize and self.toast.isVisible():
            self.toast.move(self._resting_point())
        return False
