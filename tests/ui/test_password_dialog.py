"""Tests for the PDF password prompt."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

from docly.ui.pdf.password_dialog import PasswordDialog, ask_password


def test_masked_with_show_toggle(qtbot) -> None:
    dialog = PasswordDialog("marks.pdf")
    qtbot.addWidget(dialog)
    assert dialog.field.echoMode() == QLineEdit.EchoMode.Password
    dialog.show_box.setChecked(True)
    assert dialog.field.echoMode() == QLineEdit.EchoMode.Normal
    dialog.show_box.setChecked(False)
    assert dialog.field.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.error.isVisibleTo(dialog)


def test_open_needs_text(qtbot) -> None:
    dialog = PasswordDialog("marks.pdf")
    qtbot.addWidget(dialog)
    assert not dialog.ok_button.isEnabled()
    dialog.field.setText("secret")
    assert dialog.ok_button.isEnabled()
    assert dialog.password() == "secret"


def test_wrong_password_message(qtbot) -> None:
    dialog = PasswordDialog("marks.pdf", wrong=True)
    qtbot.addWidget(dialog)
    assert dialog.error.isVisibleTo(dialog)
    assert "didn't work" in dialog.error.text()


def _answer(text: str | None) -> None:
    """Fill in and close the dialog as soon as it opens."""

    def act() -> None:
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, PasswordDialog) and w.isVisible())
        if text is None:
            dialog.reject()
        else:
            dialog.field.setText(text)
            dialog.accept()

    QTimer.singleShot(50, act)


def test_ask_password_returns_text_or_none(qtbot) -> None:
    _answer("pw")
    assert ask_password(None, "a.pdf") == "pw"
    _answer(None)
    assert ask_password(None, "a.pdf") is None
