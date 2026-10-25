"""Loads the bundled Lucide SVG icons and recolours them per theme.

Lucide icons draw with ``stroke="currentColor"``; we swap that for a token
colour before rendering, so one SVG file works in both themes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from docly import config
from docly.logger import get_logger

log = get_logger(__name__)

#: Every icon the UI uses. Tests check that each file exists.
ICON_NAMES: tuple[str, ...] = (
    "docly-mark",
    "image",
    "pen-line",
    "file-text",
    "layers",
    "settings",
    "sun",
    "moon",
    "info",
    "chevron-down",
    "chevron-up",
    # Status badges, inputs and links
    "circle-check",
    "triangle-alert",
    "circle-x",
    "loader-circle",
    "search",
    "minus",
    "plus",
    # Home page and tour
    "house",
    "compass",
    "star",
    "arrow-right",
    # Fill & Sign
    "type",
    "calendar",
    "check",
    "signature",
    "square",
    "zoom-in",
    "zoom-out",
    "chevron-left",
    "chevron-right",
    "mouse-pointer-2",
    # PDF page toolbar
    "rotate-ccw",
    "rotate-cw",
    "trash-2",
    "copy",
    "undo-2",
    "redo-2",
    "x",
)


@lru_cache(maxsize=None)
def _svg_text(name: str) -> str | None:
    path = config.ICONS_DIR / f"{name}.svg"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        log.warning("Icon not found: %s", path)
        return None


@lru_cache(maxsize=256)
def render_icon(name: str, color: str, size: int = 18, dpr: float = 1.0) -> QPixmap:
    """Render icon ``name`` in ``color`` at ``size`` logical pixels.

    ``dpr`` is the screen's device-pixel ratio (1.5 at 150 % scaling), so
    icons stay sharp on high-DPI displays. A missing or broken icon gives a
    transparent pixmap instead of an error.
    """
    physical = max(1, round(size * dpr))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    svg = _svg_text(name)
    if svg is not None:
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
        if renderer.isValid():
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, physical, physical))
            painter.end()
        else:
            log.warning("Icon could not be parsed: %s", name)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def export_icon_svg(name: str, color: str) -> Path | None:
    """Write a recoloured copy of an icon to the cache folder for use in QSS.

    Stylesheets can only load images from files (``url(...)``), so icons
    that QSS draws, like the dropdown arrow, need a real file per colour.
    Returns ``None`` if the cache folder can't be written.
    """
    svg = _svg_text(name)
    if svg is None:
        return None
    folder = config.app_data_dir() / "cache" / "icons"
    target = folder / f"{name}-{color.lstrip('#').lower()}.svg"
    try:
        if not target.exists():
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(svg.replace("currentColor", color), encoding="utf-8")
    except OSError:
        log.warning("Could not write icon cache %s", target)
        return None
    return target


def make_icon(name: str, color: str, size: int = 18, dpr: float = 1.0) -> QIcon:
    """Same as :func:`render_icon` but wrapped in a ``QIcon``."""
    return QIcon(render_icon(name, color, size, dpr))
