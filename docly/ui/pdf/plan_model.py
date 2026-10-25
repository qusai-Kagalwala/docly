"""The arranged pages, as a Qt list model with undo/redo.

Desktop concept — *model/view*: Qt separates the data (a "model") from the
widget that draws it (a "view"). :class:`PlanModel` holds the page plan
(a list of :class:`~docly.core.pdf_ops.PageRef`); the thumbnail grid is a
view of it. When the plan changes, the model tells every view to redraw.

Desktop concept — *undo stack*: every change is pushed onto a
``QUndoStack`` as a command that knows how to undo itself. Here each
command simply remembers the whole plan before and after (plans are tiny
lists of numbers, so this is cheap and impossible to get subtly wrong).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from docly.core.pdf_ops import PageRef

#: Custom data roles the delegate reads.
PAGE_REF_ROLE = Qt.ItemDataRole.UserRole + 1

ModelIndex = QModelIndex | QPersistentModelIndex


class _PlanChange(QUndoCommand):
    """Swap the whole plan between two snapshots."""

    def __init__(
        self,
        model: PlanModel,
        text: str,
        before: list[PageRef],
        after: list[PageRef],
        select_before: list[int],
        select_after: list[int],
    ) -> None:
        super().__init__(text)
        self._model = model
        self._before = before
        self._after = after
        self._select_before = select_before
        self._select_after = select_after

    def redo(self) -> None:
        self._model._replace(self._after, self._select_after)

    def undo(self) -> None:
        self._model._replace(self._before, self._select_before)


class PlanModel(QAbstractListModel):
    """The pages of the output, in order.

    Every editing method takes *rows* (positions in the plan) and is
    undoable. Each emits :attr:`selectionWanted` with the rows that should
    be selected afterwards (the moved, turned or copied pages).

    Signals:
        planChanged(): the plan changed (any edit, undo or redo).
        selectionWanted(object): list of rows to select after an edit.
    """

    planChanged = Signal()
    selectionWanted = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plan: list[PageRef] = []
        self.undo_stack = QUndoStack(self)

    # ----- Qt model API -------------------------------------------------
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._plan)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._plan):
            return None
        ref = self._plan[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return str(index.row() + 1)
        if role == PAGE_REF_ROLE:
            return ref
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"Page {index.row() + 1}"
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled
        return base | Qt.ItemFlag.ItemIsDropEnabled

    # ----- reading ------------------------------------------------------
    @property
    def plan(self) -> list[PageRef]:
        """A copy of the current plan."""
        return list(self._plan)

    def __len__(self) -> int:
        return len(self._plan)

    def ref(self, row: int) -> PageRef:
        return self._plan[row]

    def sources_used(self) -> list[int]:
        """Source indexes that still have at least one page, in first-use order."""
        seen: dict[int, None] = {}
        for ref in self._plan:
            seen.setdefault(ref.source, None)
        return list(seen)

    def pages_from(self, source: int) -> int:
        return sum(1 for ref in self._plan if ref.source == source)

    # ----- editing (all undoable) -----------------------------------------
    def reset(self, plan: Sequence[PageRef] = ()) -> None:
        """Start over with ``plan``; clears undo history."""
        self.undo_stack.clear()
        self._replace(list(plan), [])

    def append(self, refs: Sequence[PageRef], row: int | None = None, text: str = "Add pages") -> None:
        """Insert pages at ``row`` (default: the end)."""
        if not refs:
            return
        at = len(self._plan) if row is None else max(0, min(row, len(self._plan)))
        after = self._plan[:at] + list(refs) + self._plan[at:]
        self._push(text, after, list(range(at, at + len(refs))))

    def move(self, rows: Iterable[int], dest: int) -> None:
        """Move ``rows`` (kept in their order) so they start before ``dest``.

        ``dest`` is a position in the *current* plan (0 … len); it is the
        gap the user dropped into.
        """
        chosen = self._valid(rows)
        if not chosen:
            return
        dest = max(0, min(dest, len(self._plan)))
        moving = [self._plan[r] for r in chosen]
        keep = [ref for r, ref in enumerate(self._plan) if r not in set(chosen)]
        at = dest - sum(1 for r in chosen if r < dest)
        after = keep[:at] + moving + keep[at:]
        if after == self._plan:
            return
        text = "Move page" if len(chosen) == 1 else f"Move {len(chosen)} pages"
        self._push(text, after, list(range(at, at + len(moving))))

    def rotate(self, rows: Iterable[int], angle: int) -> None:
        """Turn pages clockwise by ``angle`` (90, -90 or 180)."""
        chosen = self._valid(rows)
        if not chosen or angle % 90:
            return
        after = list(self._plan)
        for r in chosen:
            ref = after[r]
            after[r] = PageRef(ref.source, ref.page, (ref.rotate + angle) % 360)
        word = "left" if angle % 360 == 270 else "right" if angle % 360 == 90 else "around"
        self._push(f"Turn {_count(chosen)} {word}", after, chosen)

    def delete(self, rows: Iterable[int]) -> bool:
        """Remove pages. Refuses (returns False) to delete every page."""
        chosen = self._valid(rows)
        if not chosen:
            return True
        if len(chosen) == len(self._plan):
            return False
        gone = set(chosen)
        after = [ref for r, ref in enumerate(self._plan) if r not in gone]
        next_row = min(chosen[0], len(after) - 1)
        self._push(f"Delete {_count(chosen)}", after, [next_row])
        return True

    def duplicate(self, rows: Iterable[int]) -> None:
        """Insert a copy of the pages right after the last one chosen."""
        chosen = self._valid(rows)
        if not chosen:
            return
        at = chosen[-1] + 1
        copies = [self._plan[r] for r in chosen]
        after = self._plan[:at] + copies + self._plan[at:]
        self._push(f"Duplicate {_count(chosen)}", after, list(range(at, at + len(copies))))

    def remove_source(self, source: int, name: str = "file") -> None:
        """Remove every page that came from ``source``."""
        after = [ref for ref in self._plan if ref.source != source]
        if len(after) != len(self._plan):
            self._push(f"Remove {name}", after, [])

    # ----- internals ------------------------------------------------------
    def _valid(self, rows: Iterable[int]) -> list[int]:
        return sorted({r for r in rows if 0 <= r < len(self._plan)})

    def _push(self, text: str, after: list[PageRef], select_after: list[int]) -> None:
        self.undo_stack.push(_PlanChange(self, text, list(self._plan), after, [], select_after))

    def _replace(self, plan: list[PageRef], select: list[int]) -> None:
        self.beginResetModel()
        self._plan = list(plan)
        self.endResetModel()
        self.planChanged.emit()
        self.selectionWanted.emit([r for r in select if 0 <= r < len(self._plan)])


def _count(rows: Sequence[int]) -> str:
    return "page" if len(rows) == 1 else f"{len(rows)} pages"
