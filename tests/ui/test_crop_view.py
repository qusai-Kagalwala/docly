"""Tests for the ratio-locked crop view."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage

from docly.core.resize import CropBox
from docly.ui.widgets.crop_view import CropView


@pytest.fixture
def view(qtbot, theme_manager) -> CropView:
    widget = CropView(theme_manager)
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    widget.show()
    qtbot.waitExposed(widget)
    image = QImage(1200, 800, QImage.Format.Format_RGB888)
    image.fill(0x808080)
    widget.set_image(image, (2400, 1600), 1.0)
    return widget


def widget_point(view: CropView, x: float, y: float) -> QPoint:
    from PySide6.QtCore import QPointF

    return view.to_widget(QPointF(x, y)).toPoint()


def test_frame_starts_centred_with_ratio(view: CropView) -> None:
    assert view.display_box == QRectF(200, 0, 800, 800)
    assert view.crop_box() == CropBox(400, 0, 1600, 1600)  # in full-resolution pixels


def test_wide_ratio(view: CropView) -> None:
    view.set_ratio(3.0)
    box = view.display_box
    assert (box.width(), box.height()) == (1200, 400)
    assert box.y() == 200


def test_move_is_clamped_inside_photo(qtbot, view: CropView) -> None:
    centre = widget_point(view, 600, 400)
    with qtbot.waitSignal(view.cropChanged, timeout=1000):
        qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=centre)
        qtbot.mouseMove(view, centre + QPoint(300, 0))
        qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=centre + QPoint(300, 0))
    box = view.display_box
    assert box.x() == pytest.approx(400)  # 1200 - 800: as far right as it can go
    assert box.width() == box.height()


def test_resize_keeps_ratio(qtbot, view: CropView) -> None:
    corner = widget_point(view, 1000, 800)  # bottom-right handle
    target = widget_point(view, 700, 500)
    with qtbot.waitSignal(view.cropChanged, timeout=1000):
        qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
        qtbot.mouseMove(view, target)
        qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=target)
    box = view.display_box
    assert box.width() == pytest.approx(box.height())
    assert box.width() < 800
    assert box.topLeft().x() == pytest.approx(200)  # anchored at the opposite corner


def test_resize_cannot_leave_photo(qtbot, view: CropView) -> None:
    view.set_ratio(1.0)
    view.move_box(-1000, 0)  # frame at the left edge
    corner = widget_point(view, 800, 800)
    far = QPoint(view.width() + 500, view.height() + 500)
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    qtbot.mouseMove(view, far)
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=far)
    box = view.display_box
    assert box.right() <= 1200 + 1e-6 and box.bottom() <= 800 + 1e-6


def test_click_outside_frame_does_nothing(qtbot, view: CropView) -> None:
    before = view.display_box
    outside = widget_point(view, 50, 400)
    with qtbot.assertNotEmitted(view.cropChanged):
        qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=outside)
        qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=outside)
    assert view.display_box == before


def test_arrow_keys_nudge(qtbot, view: CropView) -> None:
    with qtbot.waitSignal(view.cropChanged, timeout=1000):
        qtbot.keyClick(view, Qt.Key.Key_Left)
    assert view.display_box.x() == pytest.approx(199)
    qtbot.keyClick(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert view.display_box.x() == pytest.approx(209)


def test_no_ratio_means_no_crop(view: CropView) -> None:
    view.set_ratio(None)
    assert not view.has_crop
    assert view.crop_box() is None


def test_reset_recentres(view: CropView) -> None:
    view.move_box(-100, 0)
    view.reset()
    assert view.display_box == QRectF(200, 0, 800, 800)


def test_paints_in_both_themes(view: CropView, theme_manager) -> None:
    assert not view.grab().isNull()
    theme_manager.toggle()
    assert not view.grab().isNull()
