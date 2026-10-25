"""Run slow work off the UI thread.

Why: Qt draws the window on the main ("UI") thread. If that thread spends
two seconds compressing a photo, the window freezes and Windows may show
"Not responding". So slow work runs on Qt's thread pool, and results come
back to the UI thread as signals.

:class:`TaskRunner` also handles "latest result wins": when the user
changes the crop again before the last job finished, the old job is
cancelled and its late result is ignored.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from docly.core.errors import CancelledError, DoclyError
from docly.logger import get_logger

log = get_logger(__name__)

GENERIC_ERROR = "Something went wrong while processing. Details were saved to the log."


class CancelToken:
    """Thread-safe cancel flag. Calling it returns True once cancelled, so it
    can be passed straight to core functions as their ``cancel`` callback."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def __call__(self) -> bool:
        return self._event.is_set()


class _WorkerSignals(QObject):
    finished = Signal(int, object)  # job id, result
    failed = Signal(int, str)  # job id, user-facing message
    cancelled = Signal(int)


class Worker(QRunnable):
    """Runs ``fn(token)`` on a pool thread and reports back through signals."""

    def __init__(self, job_id: int, fn: Callable[[CancelToken], Any]) -> None:
        super().__init__()
        self.job_id = job_id
        self.fn = fn
        self.token = CancelToken()
        self.signals = _WorkerSignals()
        self.setAutoDelete(False)  # Python keeps the reference (see TaskRunner)

    def run(self) -> None:  # runs on the pool thread
        try:
            result = self.fn(self.token)
        except CancelledError:
            self.signals.cancelled.emit(self.job_id)
        except DoclyError as exc:
            self.signals.failed.emit(self.job_id, str(exc))
        except Exception:
            log.exception("Background job %s crashed", self.job_id)
            self.signals.failed.emit(self.job_id, GENERIC_ERROR)
        else:
            if self.token.cancelled:
                self.signals.cancelled.emit(self.job_id)
            else:
                self.signals.finished.emit(self.job_id, result)


class TaskRunner(QObject):
    """Runs one kind of job at a time; a new job replaces the previous one.

    Signals (always delivered on the UI thread):
        started(): a job began.
        finished(object): the latest job's result.
        failed(str): the latest job failed; message is safe to show.
        busyChanged(bool): whether a job is running.
    """

    started = Signal()
    finished = Signal(object)
    failed = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, pool: QThreadPool | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._next_id = 0
        self._current: int | None = None
        self._workers: dict[int, Worker] = {}

    @property
    def busy(self) -> bool:
        return self._current is not None

    def submit(self, fn: Callable[[CancelToken], Any]) -> int:
        """Start ``fn`` in the background, cancelling any job still running."""
        was_busy = self.busy
        self._cancel_current()
        self._next_id += 1
        job_id = self._next_id
        worker = Worker(job_id, fn)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        self._workers[job_id] = worker
        self._current = job_id
        self.started.emit()
        if not was_busy:
            self.busyChanged.emit(True)
        self._pool.start(worker)
        return job_id

    def cancel(self) -> None:
        """Ask the running job to stop; its result will be ignored."""
        was_busy = self.busy
        self._cancel_current()
        self._current = None
        if was_busy:
            self.busyChanged.emit(False)

    def _cancel_current(self) -> None:
        if self._current is not None:
            worker = self._workers.get(self._current)
            if worker is not None:
                worker.token.cancel()

    def wait(self, msecs: int = 30_000) -> bool:
        """Block until all jobs on the pool finish (used by tests)."""
        return self._pool.waitForDone(msecs)

    # ----- results (UI thread) -----------------------------------------
    def _on_finished(self, job_id: int, result: object) -> None:
        if self._settle(job_id):
            self.finished.emit(result)

    def _on_failed(self, job_id: int, message: str) -> None:
        if self._settle(job_id):
            self.failed.emit(message)

    def _on_cancelled(self, job_id: int) -> None:
        self._settle(job_id)

    def _settle(self, job_id: int) -> bool:
        """Forget the worker; return True if this was the current job."""
        self._workers.pop(job_id, None)
        if job_id != self._current:
            return False  # stale: a newer job replaced it
        self._current = None
        self.busyChanged.emit(False)
        return True
