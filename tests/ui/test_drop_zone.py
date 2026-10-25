"""Tests for the drop zone."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from docly.ui.widgets import drop_zone
from docly.ui.widgets.drop_zone import MULTIPLE_FILES_TIP, DropZone, pick_dropped_image


def mime_for(*paths: Path | str) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) if not str(p).startswith("http") else QUrl(str(p)) for p in paths])
    return mime


def test_single_image() -> None:
    path, note = pick_dropped_image(mime_for(Path("C:/photos/me.JPG")))
    assert path is not None and path.name == "me.JPG"
    assert note is None


def test_multiple_files_take_first_image_with_tip() -> None:
    path, note = pick_dropped_image(mime_for("C:/docs/cv.pdf", "C:/photos/a.png", "C:/photos/b.png"))
    assert path is not None and path.name == "a.png"
    assert note == MULTIPLE_FILES_TIP


def test_non_image_is_rejected() -> None:
    path, note = pick_dropped_image(mime_for("C:/docs/cv.pdf"))
    assert path is None
    assert "cv.pdf isn't a photo" in note


def test_web_links_are_ignored() -> None:
    path, note = pick_dropped_image(mime_for("https://example.org/photo.jpg"))
    assert path is None and note


def test_heic_is_accepted_so_loader_can_explain() -> None:
    path, _ = pick_dropped_image(mime_for("C:/photos/IMG_0001.HEIC"))
    assert path is not None


def test_drop_event_emits_path(qtbot, theme_manager, tmp_path: Path) -> None:
    zone = DropZone(theme_manager)
    qtbot.addWidget(zone)
    mime = mime_for(tmp_path / "me.jpg")
    enter = QDragEnterEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dragEnterEvent(enter)
    assert zone.active
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    with qtbot.waitSignal(zone.fileChosen, timeout=1000) as blocker:
        zone.dropEvent(drop)
    assert blocker.args[0] == tmp_path / "me.jpg"
    assert not zone.active


def test_drop_of_non_image_emits_message(qtbot, theme_manager) -> None:
    zone = DropZone(theme_manager)
    qtbot.addWidget(zone)
    mime = mime_for("C:/a.docx")  # keep a reference: the event doesn't own it
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    with qtbot.waitSignal(zone.message, timeout=1000) as blocker:
        zone.dropEvent(drop)
    assert "a.docx" in blocker.args[0]


def test_click_opens_file_picker(qtbot, theme_manager, monkeypatch, tmp_path: Path) -> None:
    chosen = tmp_path / "picked.png"
    monkeypatch.setattr(drop_zone, "ask_open_image", lambda parent, start="": chosen)
    zone = DropZone(theme_manager)
    qtbot.addWidget(zone)
    zone.resize(300, 300)
    zone.show()
    with qtbot.waitSignal(zone.fileChosen, timeout=1000) as blocker:
        qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)
    assert blocker.args[0] == chosen


def test_enter_key_opens_file_picker(qtbot, theme_manager, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(drop_zone, "ask_open_image", lambda parent, start="": tmp_path / "k.jpg")
    zone = DropZone(theme_manager)
    qtbot.addWidget(zone)
    with qtbot.waitSignal(zone.fileChosen, timeout=1000):
        qtbot.keyClick(zone, Qt.Key.Key_Return)


def test_cancelled_picker_emits_nothing(qtbot, theme_manager, monkeypatch) -> None:
    monkeypatch.setattr(drop_zone, "ask_open_image", lambda parent, start="": None)
    zone = DropZone(theme_manager)
    qtbot.addWidget(zone)
    with qtbot.assertNotEmitted(zone.fileChosen):
        zone.browse()


def test_multiple_mode_emits_every_dropped_file(qtbot, theme_manager, tmp_path: Path) -> None:
    zone = DropZone(theme_manager, multiple=True, title="Drop PDFs here", icon="file-text")
    qtbot.addWidget(zone)
    mime = mime_for(tmp_path / "a.pdf", tmp_path / "b.jpg", "https://example.org/c.pdf")
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    with qtbot.waitSignal(zone.filesChosen, timeout=1000) as blocker:
        zone.dropEvent(drop)
    assert blocker.args[0] == [tmp_path / "a.pdf", tmp_path / "b.jpg"]  # web links ignored
    assert zone.accessibleName() == "Drop PDFs here or click to browse"


def test_multiple_mode_picker(qtbot, theme_manager, monkeypatch, tmp_path: Path) -> None:
    chosen = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    monkeypatch.setattr(drop_zone, "ask_open_files", lambda parent, title, flt, start="": chosen)
    zone = DropZone(theme_manager, multiple=True)
    qtbot.addWidget(zone)
    with qtbot.waitSignal(zone.filesChosen, timeout=1000) as blocker:
        zone.browse()
    assert blocker.args[0] == chosen
