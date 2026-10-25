"""Tests for the icon capsules, banners, status tiles and the batch status delegate."""

from __future__ import annotations

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from docly.ui.qss import derived_colors
from docly.ui.widgets.status_badge import Banner, IconText, StatusBadge, StatusDelegate, StatusIcon, kind_colour


def test_badge_shows_word_and_kind(qtbot, theme_manager) -> None:
    badge = StatusBadge(theme_manager, "success", "Ready")
    qtbot.addWidget(badge)
    assert badge.text() == "Ready" and badge.kind == "success"
    assert badge.property("kind") == "success"
    assert not badge.icon.pixmap().isNull()
    badge.set_status("danger", "Failed")
    assert badge.text() == "Failed" and badge.property("kind") == "danger"
    assert badge.accessibleName() == "Failed"


def test_working_badge_uses_warning_tint_and_does_not_spin_when_motion_is_off(qtbot, theme_manager) -> None:
    badge = StatusBadge(theme_manager, "working", "Working")
    qtbot.addWidget(badge)
    assert badge.property("kind") == "warning"
    assert badge._spin.state() != badge._spin.State.Running  # tests run with reduced motion


def test_banner_keeps_text_and_kind(qtbot, theme_manager) -> None:
    banner = Banner(theme_manager)
    qtbot.addWidget(banner)
    banner.show()  # parent shown; the banner itself starts hidden
    banner.hide()
    assert banner.isHidden()
    banner.show_message("Couldn't read it", "danger")
    assert banner.isVisible() and banner.text() == "Couldn't read it" and banner.kind == "danger"
    banner.show_message("Heads up", "warning")
    assert banner.property("kind") == "warning"


def test_status_icon_hides_without_kind(qtbot, theme_manager) -> None:
    icon = StatusIcon(theme_manager)
    qtbot.addWidget(icon)
    icon.set_kind("success")
    assert not icon.isHidden() and icon.kind == "success"
    icon.set_kind("")
    assert icon.isHidden()


def test_icon_text_tints_problems(qtbot, theme_manager) -> None:
    row = IconText(theme_manager, "danger", "Size: 10 KB")
    qtbot.addWidget(row)
    assert row.label.property("tone") == "danger" and row.text() == "Size: 10 KB"
    assert IconText(theme_manager, "success", "ok").label.property("tone") is None


def test_kind_colours_follow_theme(theme_manager) -> None:
    colours = derived_colors(theme_manager.tokens)
    assert kind_colour(theme_manager.tokens, "success") == colours["success_text"]
    assert kind_colour(theme_manager.tokens, "anything") == colours["accent_text"]


def test_delegate_paints_capsules_and_keeps_text(qtbot, theme_manager) -> None:
    table = QTableWidget(3, 1)
    qtbot.addWidget(table)
    table.setItemDelegateForColumn(0, StatusDelegate(theme_manager, {"Ready": "success", "Failed": "danger"}, table))
    for row, word in enumerate(("Ready", "Failed", "Waiting")):
        table.setItem(row, 0, QTableWidgetItem(word))
    table.show()
    assert not table.grab().isNull()  # paints without errors
    assert table.item(0, 0).text() == "Ready"
    delegate = table.itemDelegateForColumn(0)
    hint = delegate.sizeHint(_option(table), table.model().index(0, 0))
    assert hint.width() > 40


def _option(table: QTableWidget):  # noqa: ANN202
    from PySide6.QtWidgets import QStyleOptionViewItem

    option = QStyleOptionViewItem()
    option.initFrom(table)
    return option
