"""Small, quick animations, and the switch that turns them all off.

Motion is on unless Windows' "Animation effects" setting is off or the
user turns on "Reduce motion" in Docly's settings. Every helper here does
the final state instantly when motion is off, so nothing ever waits on an
animation to be usable.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPoint, QPropertyAnimation, QRect
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from docly.logger import get_logger

log = get_logger(__name__)

FAST_MS = 150
NORMAL_MS = 200
ENV_REDUCE = "DOCLY_REDUCE_MOTION"  # set to 1 to disable (tests use this)

_user_reduce = False


def windows_animations_enabled() -> bool:
    """Windows' "Animation effects" switch (Settings › Accessibility › Visual effects)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        value = ctypes.c_int(1)
        spi_getclientareaanimation = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(spi_getclientareaanimation, 0, ctypes.byref(value), 0):
            return bool(value.value)
    except Exception:  # never let a settings probe break the app
        log.debug("Could not read Windows animation setting", exc_info=True)
    return True


def set_reduce_motion(reduce: bool) -> None:
    """The user's "Reduce motion" setting."""
    global _user_reduce
    _user_reduce = reduce


def enabled() -> bool:
    if _user_reduce or os.environ.get(ENV_REDUCE) == "1":
        return False
    return windows_animations_enabled()


def _opacity(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    return effect


def fade_in(widget: QWidget, duration: int = NORMAL_MS) -> QPropertyAnimation | None:
    """Show ``widget`` and fade it from transparent. Don't use on widgets
    that already have their own graphics effect (cards have shadows)."""
    widget.show()
    if not enabled() or (widget.graphicsEffect() is not None and not isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect)):
        return None
    effect = _opacity(widget)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Remove the effect afterwards: an idle opacity effect still costs a repaint layer.
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def fade_out_and_delete(widget: QWidget, duration: int = FAST_MS) -> QPropertyAnimation | None:
    if not enabled():
        widget.deleteLater()
        return None
    effect = _opacity(widget)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InCubic)
    animation.finished.connect(widget.deleteLater)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def move_to(widget: QWidget, target: QPoint, duration: int = NORMAL_MS) -> QPropertyAnimation | None:
    if not enabled() or not widget.isVisible():
        widget.move(target)
        return None
    animation = QPropertyAnimation(widget, b"pos", widget)
    animation.setDuration(duration)
    animation.setEndValue(target)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def slide_geometry(widget: QWidget, target: QRect, duration: int = NORMAL_MS) -> QPropertyAnimation | None:
    if not enabled() or not widget.isVisible():
        widget.setGeometry(target)
        return None
    animation = QPropertyAnimation(widget, b"geometry", widget)
    animation.setDuration(duration)
    animation.setEndValue(target)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation
