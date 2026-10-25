"""Helpers for changing a widget's style property at runtime."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_style_prop(widget: QWidget, name: str, value: str | None) -> None:
    """Change a dynamic property used by the stylesheet and restyle.

    Qt only re-reads stylesheet rules like ``QLabel[chip="success"]`` when a
    widget is polished, so after changing the property we unpolish and
    polish it again.
    """
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
