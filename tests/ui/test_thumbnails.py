"""Tests for background page thumbnails."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from docly.ui.pdf.thumbnails import THUMB_PX, ThumbnailCache, ThumbSource, render_image_thumb, rotated
from tests.core import images, pdfs

TIMEOUT = 15_000


@pytest.fixture
def cache(qapp):
    c = ThumbnailCache()
    yield c
    c.shutdown()


def wait_for(qtbot, cache: ThumbnailCache, keys) -> None:
    qtbot.waitUntil(lambda: all(cache.get(k) is not None or cache.failed(k) for k in keys), timeout=TIMEOUT)


def test_pdf_pages_render_in_proportion(qtbot, cache: ThumbnailCache) -> None:
    cache.add_source(0, ThumbSource(pdfs.make_pdf(["a", "b"]), is_pdf=True))
    cache.request([(0, 0), (0, 1)])
    wait_for(qtbot, cache, [(0, 0), (0, 1)])
    image = cache.get((0, 0))
    assert image.height() == THUMB_PX
    assert abs(image.width() - THUMB_PX * 595 / 842) <= 1
    assert image.pixelColor(2, 2) == QColor("white")  # transparent PDF background drawn on white


def test_page_rotation_is_respected(qtbot, cache: ThumbnailCache) -> None:
    cache.add_source(0, ThumbSource(pdfs.make_pdf(["a"], rotate=90), is_pdf=True))
    cache.request([(0, 0)])
    wait_for(qtbot, cache, [(0, 0)])
    image = cache.get((0, 0))
    assert image.width() > image.height()  # portrait page with /Rotate 90 looks landscape


def test_locked_pdf_uses_password(qtbot, cache: ThumbnailCache) -> None:
    data = pdfs.make_pdf(["a"], password="pw")
    cache.add_source(0, ThumbSource(data, is_pdf=True, password="pw"))
    cache.add_source(1, ThumbSource(data, is_pdf=True))  # no password: no preview, no crash
    cache.request([(0, 0), (1, 0)])
    wait_for(qtbot, cache, [(0, 0), (1, 0)])
    assert cache.get((0, 0)) is not None
    assert cache.failed((1, 0))


def test_images_and_broken_data(qtbot, cache: ThumbnailCache) -> None:
    jpeg = images.encode(images.photo_like(800, 400), "JPEG")
    cache.add_source(0, ThumbSource(jpeg, is_pdf=False))
    cache.add_source(1, ThumbSource(b"%PDF-1.7 not really", is_pdf=True))
    cache.request([(0, 0), (1, 0)])
    wait_for(qtbot, cache, [(0, 0), (1, 0)])
    assert cache.get((0, 0)).width() == THUMB_PX
    assert cache.failed((1, 0))


def test_ready_signal_and_no_rework(qtbot, cache: ThumbnailCache) -> None:
    cache.add_source(0, ThumbSource(pdfs.make_pdf(["a"]), is_pdf=True))
    with qtbot.waitSignal(cache.thumbnailReady, timeout=TIMEOUT) as blocker:
        cache.request([(0, 0)])
    assert blocker.args[0] == (0, 0)
    cache.request([(0, 0)])  # already cached: nothing queued
    assert cache.pending() == 0


def test_requested_first_are_drawn_first(qtbot, cache: ThumbnailCache) -> None:
    cache.add_source(0, ThumbSource(pdfs.make_pdf([str(i) for i in range(30)]), is_pdf=True))
    order: list[tuple[int, int]] = []
    cache.thumbnailReady.connect(order.append)
    cache.request([(0, i) for i in range(30)])
    cache.request([(0, 25), (0, 26)])  # user scrolled: these move to the front
    wait_for(qtbot, cache, [(0, i) for i in range(30)])
    assert order.index((0, 25)) < 10 and order.index((0, 26)) < 10


def test_clear_drops_late_results(qtbot, cache: ThumbnailCache) -> None:
    cache.add_source(0, ThumbSource(pdfs.make_pdf(["a"] * 10), is_pdf=True))
    cache.request([(0, i) for i in range(10)])
    cache.clear()
    qtbot.waitUntil(lambda: not cache.running, timeout=TIMEOUT)
    QApplication.processEvents()
    assert all(cache.get((0, i)) is None for i in range(10))  # results for a cleared source are dropped
    assert cache.pending() == 0


def test_rotated_and_image_helper(qapp) -> None:
    image = render_image_thumb(images.encode(images.photo_like(300, 600), "PNG"))
    assert (image.width(), image.height()) == (THUMB_PX // 2, THUMB_PX)
    turned = rotated(image, 90)
    assert (turned.width(), turned.height()) == (image.height(), image.width())
    assert rotated(image, 360) is image
