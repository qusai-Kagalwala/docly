"""Tests for icon loading and recolouring."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from docly import config
from docly.ui.icons import ICON_NAMES, render_icon


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_file_exists(name: str) -> None:
    assert (config.ICONS_DIR / f"{name}.svg").is_file()


@pytest.mark.parametrize("name", ICON_NAMES)
def test_icon_renders_in_requested_colour(qapp, name: str) -> None:
    pixmap = render_icon(name, "#D64545", 24)
    assert not pixmap.isNull()
    image = pixmap.toImage()
    painted = [
        QColor(image.pixel(x, y))
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    ]
    assert painted, "icon drew nothing"
    assert any(c.red() > 180 and c.green() < 110 and c.blue() < 110 for c in painted)


def test_high_dpi_render_is_sharp(qapp) -> None:
    pixmap = render_icon("sun", "#2F6FEB", 18, dpr=2.0)
    assert pixmap.width() == 36
    assert pixmap.devicePixelRatio() == 2.0


def test_missing_icon_does_not_crash(qapp) -> None:
    pixmap = render_icon("does-not-exist", "#000000", 18)
    assert not pixmap.isNull()
    assert pixmap.toImage().pixelColor(9, 9).alpha() == 0


def test_lucide_licence_is_bundled() -> None:
    assert (config.ICONS_DIR / "LICENSE-lucide.txt").is_file()
