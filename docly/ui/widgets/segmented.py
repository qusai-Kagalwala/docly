"""Segmented control: a row of mutually exclusive options."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QWidget


class SegmentedControl(QFrame):
    """Pill-style selector, e.g. System / Light / Dark.

    Signals:
        valueChanged(str): the user picked a different option.
    """

    valueChanged = Signal(str)

    def __init__(
        self, options: list[tuple[str, str]], parent: QWidget | None = None, min_button_width: int | None = None
    ) -> None:
        """``options`` is a list of ``(value, label)`` pairs.

        ``min_button_width`` lets the buttons shrink below their natural
        width (for narrow side columns; Windows fonts run wider).
        """
        super().__init__(parent)
        self.setObjectName("Segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName(f"segment_{value}")
            button.setProperty("segment", "true")
            button.setCheckable(True)
            if min_button_width is not None:
                button.setMinimumWidth(min_button_width)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button)
            self.buttons[value] = button
            layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, v=value: self.valueChanged.emit(v))

    def value(self) -> str | None:
        """Currently selected value."""
        for value, button in self.buttons.items():
            if button.isChecked():
                return value
        return None

    def set_value(self, value: str) -> None:
        """Select ``value`` without emitting :attr:`valueChanged`."""
        button = self.buttons.get(value)
        if button is not None:
            button.setChecked(True)
