"""Tests for the undoable page plan model."""

from __future__ import annotations

import pytest

from docly.core.pdf_ops import PageRef
from docly.ui.pdf.plan_model import PAGE_REF_ROLE, PlanModel


def pages(model: PlanModel) -> list[str]:
    """Plan as compact strings: 'a1' = source 0 page 0, 'b2r90' = source 1 page 1 turned 90°."""
    out = []
    for ref in model.plan:
        text = f"{'abc'[ref.source]}{ref.page + 1}"
        out.append(text + (f"r{ref.rotate}" if ref.rotate else ""))
    return out


@pytest.fixture
def model(qapp) -> PlanModel:
    m = PlanModel()
    m.reset([PageRef(0, i) for i in range(5)])
    return m


def test_reset_has_no_undo(model: PlanModel) -> None:
    assert pages(model) == ["a1", "a2", "a3", "a4", "a5"]
    assert not model.undo_stack.canUndo()
    assert model.rowCount() == 5
    assert model.data(model.index(2)) == "3"
    assert model.data(model.index(2), PAGE_REF_ROLE) == PageRef(0, 2)


@pytest.mark.parametrize(
    ("rows", "dest", "expected"),
    [
        ([0], 3, ["a2", "a3", "a1", "a4", "a5"]),  # drop into gap before a4
        ([4], 0, ["a5", "a1", "a2", "a3", "a4"]),
        ([0, 2], 5, ["a2", "a4", "a5", "a1", "a3"]),  # to the end, order kept
        ([3, 1], 0, ["a2", "a4", "a1", "a3", "a5"]),  # rows are sorted first
        ([1, 2], 4, ["a1", "a4", "a2", "a3", "a5"]),
    ],
)
def test_move(model: PlanModel, rows, dest, expected) -> None:
    model.move(rows, dest)
    assert pages(model) == expected
    model.undo_stack.undo()
    assert pages(model) == ["a1", "a2", "a3", "a4", "a5"]
    model.undo_stack.redo()
    assert pages(model) == expected


def test_move_onto_itself_is_not_an_edit(model: PlanModel) -> None:
    model.move([2], 2)
    model.move([2], 3)
    assert not model.undo_stack.canUndo()


def test_move_selects_moved_pages(qtbot, model: PlanModel) -> None:
    with qtbot.waitSignal(model.selectionWanted) as blocker:
        model.move([0, 1], 5)
    assert blocker.args[0] == [3, 4]


def test_rotate_adds_up_and_wraps(model: PlanModel) -> None:
    model.rotate([1], 90)
    model.rotate([1, 2], -90)
    assert pages(model) == ["a1", "a2", "a3r270", "a4", "a5"]
    model.rotate([2], 90)
    assert pages(model)[2] == "a3"
    assert model.undo_stack.undoText() == "Turn page right"
    model.rotate([0], 45)  # ignored
    assert pages(model)[0] == "a1"


def test_delete_keeps_at_least_one_page(model: PlanModel) -> None:
    assert model.delete([1, 3])
    assert pages(model) == ["a1", "a3", "a5"]
    assert not model.delete([0, 1, 2])
    assert len(model) == 3
    model.undo_stack.undo()
    assert len(model) == 5


def test_duplicate_inserts_after_last_selected(model: PlanModel) -> None:
    model.duplicate([0, 2])
    assert pages(model) == ["a1", "a2", "a3", "a1", "a3", "a4", "a5"]


def test_append_and_insert(model: PlanModel) -> None:
    model.append([PageRef(1, 0), PageRef(1, 1)], row=1)
    assert pages(model)[:4] == ["a1", "b1", "b2", "a2"]
    model.append([PageRef(2, 0)])
    assert pages(model)[-1] == "c1"
    assert model.sources_used() == [0, 1, 2]
    assert model.pages_from(1) == 2


def test_remove_source(model: PlanModel) -> None:
    model.append([PageRef(1, 0)], row=0)
    model.remove_source(1, "cert.pdf")
    assert model.sources_used() == [0]
    assert model.undo_stack.undoText() == "Remove cert.pdf"
    model.undo_stack.undo()
    assert pages(model)[0] == "b1"


def test_invalid_rows_are_ignored(model: PlanModel) -> None:
    model.rotate([99, -1], 90)
    model.duplicate([])
    assert not model.undo_stack.canUndo()


def test_plan_changed_signal(qtbot, model: PlanModel) -> None:
    with qtbot.waitSignal(model.planChanged):
        model.rotate([0], 180)
    with qtbot.waitSignal(model.planChanged):
        model.undo_stack.undo()
