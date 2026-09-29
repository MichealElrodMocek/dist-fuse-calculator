"""The open feeder plus undo history, derived topology and study results.

Every edit goes through :meth:`Document.edit` (or a drag checkpoint), which
snapshots the model for undo, recomputes topology, re-runs the study when
auto-run is on, and emits ``changed`` so the views can refresh.
"""

from __future__ import annotations

import traceback
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from fusecalc.engine import ProtectionEngine, StudyContext, StudyResults, build_context
from fusecalc.model import Feeder, new_feeder

UNDO_LIMIT = 200


class Document(QObject):
    changed = Signal()  # model edited in place
    reset = Signal()  # model replaced wholesale (new/open/undo/redo)
    results_changed = Signal()
    title_changed = Signal()

    def __init__(self, engine: ProtectionEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.feeder: Feeder = new_feeder()
        self.path: Path | None = None
        self.dirty = False
        self.auto_run = True
        self.context: StudyContext = build_context(self.feeder)
        self.results: StudyResults | None = None
        self.results_error: str | None = None
        self.results_stale = False
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._refresh()

    # ------------------------------------------------------------ editing

    @contextmanager
    def edit(self):
        """``with doc.edit() as feeder:`` - one undoable change."""
        before = self.feeder.to_dict()
        try:
            yield self.feeder
        except Exception:
            self.feeder = Feeder.from_dict(before)
            self._refresh()
            self.reset.emit()
            self.results_changed.emit()
            raise
        self._record(before)

    def checkpoint(self) -> dict:
        """Snapshot taken before a drag; pass back to :meth:`commit_checkpoint`."""
        return self.feeder.to_dict()

    def commit_checkpoint(self, before: dict) -> None:
        if before != self.feeder.to_dict():
            self._record(before)

    def _record(self, before: dict) -> None:
        self._undo.append(before)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._set_dirty(True)
        self._refresh()
        self.changed.emit()
        self.results_changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.feeder.to_dict())
            self._replace(Feeder.from_dict(self._undo.pop()))

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.feeder.to_dict())
            self._replace(Feeder.from_dict(self._redo.pop()))

    def _replace(self, feeder: Feeder, clean: bool = False) -> None:
        self.feeder = feeder
        self._set_dirty(not clean)
        self._refresh()
        self.reset.emit()
        self.results_changed.emit()

    # --------------------------------------------------------------- files

    def new(self) -> None:
        self.path = None
        self._undo.clear()
        self._redo.clear()
        self._replace(new_feeder(), clean=True)

    def open(self, path: str | Path, as_template: bool = False) -> None:
        """Load a feeder. ``as_template`` (used for examples) leaves it untitled
        so Save asks for a new file instead of overwriting the original."""
        feeder = Feeder.load(path)
        self.path = None if as_template else Path(path)
        self._undo.clear()
        self._redo.clear()
        self._replace(feeder, clean=True)

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("No file name")
        self.feeder.save(target)
        self.path = target
        self._set_dirty(False)

    def display_name(self) -> str:
        return self.path.name if self.path else self.feeder.name

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.title_changed.emit()

    # --------------------------------------------------------------- study

    def _refresh(self) -> None:
        """Recompute topology (and results if auto-run). Emits nothing: callers
        emit changed/reset first so views sync their items before results land."""
        self.context = build_context(self.feeder)
        if self.auto_run:
            self._compute_results()
        else:
            self.results_stale = True

    def _compute_results(self) -> None:
        # The engine gets its own copy so a bug there can't corrupt the drawing.
        try:
            self.results = self.engine.run(build_context(self.feeder.copy()))
            self.results_error = None
        except Exception:
            self.results = None
            self.results_error = traceback.format_exc()
        self.results_stale = False

    def run_study(self) -> None:
        self._compute_results()
        self.results_changed.emit()

    def set_auto_run(self, on: bool) -> None:
        self.auto_run = on
        if on:
            self.run_study()
