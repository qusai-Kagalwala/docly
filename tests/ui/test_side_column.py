"""The settings column grows instead of cutting cards off (wide Windows fonts)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from docly.ui.pages.base_page import SideColumn
from docly.ui.pages.photo_page import PhotoPage
from docly.ui.pages.signature_page import SignaturePage
from tests.core import images


def test_grows_for_wide_content_and_shrinks_back(qtbot) -> None:
    column = SideColumn(300)
    qtbot.addWidget(column)
    column.show()
    assert column.width() == 300
    wide = QLabel("x" * 120)
    column.column.addWidget(wide)
    qtbot.waitUntil(lambda: column.width() > 300, timeout=2000)
    assert column.widget().minimumSizeHint().width() <= column.viewport().width()
    wide.hide()
    qtbot.waitUntil(lambda: column.width() == 300, timeout=2000)


@pytest.mark.parametrize("page_class", [PhotoPage, SignaturePage])
def test_tool_pages_never_clip_their_cards(qtbot, theme_manager, bundled_presets, page_class, tmp_path: Path) -> None:
    page = page_class(theme_manager, bundled_presets, region="IN")
    qtbot.addWidget(page)
    page.resize(1100, 720)
    page.show()
    qtbot.waitExposed(page)
    path = images.save(images.photo_like(800, 1000), tmp_path / "photo.jpg")
    page.load_file(path)
    qtbot.waitUntil(lambda: page.result_card.save_button.isEnabled(), timeout=15_000)
    qtbot.wait(50)
    assert page.side_scroll.widget().minimumSizeHint().width() <= page.side_scroll.viewport().width()
