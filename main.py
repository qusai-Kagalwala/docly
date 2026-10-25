"""Docly entry point: ``python main.py``."""

import sys

# PySide6 has reference-counting bugs on Python 3.11 that can crash the app
# on exit; Python 3.12+ is immune, so it's the minimum.
if sys.version_info < (3, 12):
    sys.exit(f"Docly needs Python 3.12 or newer (you have {sys.version.split()[0]}).")

from docly.ui.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
