"""Ask for a PDF's open password.

The password lives only in memory while the file is open. It is never
saved, logged or written into the output (Docly's output PDFs have no
password).
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from docly.ui.widgets.style import set_style_prop


class PasswordDialog(QDialog):
    """"<name> is locked" + a masked password field.

    ``wrong=True`` shows "That password didn't work" under the field.
    """

    def __init__(self, file_name: str, wrong: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Password needed")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        heading = QLabel(f"{file_name} is locked")
        heading.setProperty("role", "section")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        hint = QLabel("Enter its password to add its pages. The saved PDF will not have a password.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.field = QLineEdit()
        self.field.setAccessibleName("Password")
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setPlaceholderText("Password")
        self.field.setAccessibleName("Password")
        layout.addWidget(self.field)

        self.show_box = QCheckBox("Show password")
        self.show_box.toggled.connect(self._toggle_visible)
        layout.addWidget(self.show_box)

        self.error = QLabel("That password didn't work. Check it and try again.")
        self.error.setWordWrap(True)
        set_style_prop(self.error, "banner", "danger")
        self.error.setVisible(wrong)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox()
        self.ok_button = buttons.addButton("Open", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok_button.setProperty("variant", "primary")
        self.skip_button = buttons.addButton("Skip this file", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.field.textChanged.connect(lambda text: self.ok_button.setEnabled(bool(text)))
        self.ok_button.setEnabled(False)
        self.field.setFocus()

    def password(self) -> str:
        return self.field.text()

    def _toggle_visible(self, visible: bool) -> None:
        self.field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)


def ask_password(parent: QWidget | None, file_name: str, wrong: bool = False) -> str | None:
    """Show the dialog; returns the password, or ``None`` to skip the file."""
    dialog = PasswordDialog(file_name, wrong, parent)
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.password():
            return dialog.password()
        return None
    finally:
        dialog.field.clear()
        dialog.deleteLater()
