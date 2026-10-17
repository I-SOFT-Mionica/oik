"""Generic QThread-backed worker for running blocking core operations.

Each tab needs to call a long-running core function (generate party
files, aggregate, build docx, fetch inbox messages) without freezing
the GUI. This helper wraps the call in a QThread and forwards
progress/completion to the caller via `progress`/`finished`/`failed`
signals.

Those three signals are emitted from a `QTimer` polling `Worker`'s plain
attributes on the GUI thread — NOT emitted directly from the background
thread. Packaged (PyInstaller) builds have been observed to silently
drop signals emitted cross-thread even though the wrapped operation
completes normally underneath (confirmed via the in-app updater's
`DownloadWorker`: a partial file kept growing on disk for the full
transfer while the connected GUI slot never fired once). Polling
sidesteps that entirely, since every `emit()` call here happens on the
same thread as the receiver — no cross-thread delivery involved.

This means the public contract callers rely on (`worker.progress`,
`worker.finished`, `worker.failed`, same signatures as before) is
unchanged — no call site needs to be touched.

A stall timeout abandons the wait (and emits `failed`) if the wrapped
function goes quiet for too long. This does NOT forcibly kill the
underlying Python/OS thread — there is no safe way to interrupt a
thread blocked in a syscall, and QThread.terminate() is explicitly
unsafe (can corrupt state, leave file handles / locks dangling). It
detaches the GUI from a hung operation so the operator gets a real
error instead of a progress bar that spins forever with no way to
tell a stall from a slow operation. Configurable via
`AppSettings.worker_stall_timeout_seconds` (Поставке ОИК → Систем),
180s by default; 0 disables it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal


log = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 150
DEFAULT_STALL_TIMEOUT_SECONDS = 180


class Worker(QObject):
    progress = Signal(str, int, int)   # label, current, total
    finished = Signal(object)          # result object
    failed = Signal(str)               # error message

    def __init__(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.done = False
        self.result: Any = None
        self.error: str | None = None
        self.progress_state: tuple[str, int, int] | None = None
        self.last_activity_at = 0.0

    def run(self) -> None:
        self.last_activity_at = time.monotonic()
        try:
            import inspect
            try:
                params = inspect.signature(self._fn).parameters
                if "progress" in params:
                    self._kwargs["progress"] = self._record_progress
            except (TypeError, ValueError):
                pass
            self.result = self._fn(*self._args, **self._kwargs)
        except Exception as e:  # surface every error to the GUI; never crash silently
            self.error = str(e)
        finally:
            self.done = True

    def _record_progress(self, label: str, current: int, total: int) -> None:
        self.progress_state = (label, current, total)
        self.last_activity_at = time.monotonic()


def _default_stall_timeout() -> float:
    """Read the operator's configured stall timeout straight from disk.

    `Worker` is intentionally decoupled from `AppState` (used from
    contexts that don't carry one), so this reads `app_settings.json`
    directly rather than requiring every call site to thread the value
    through. Cheap — worker launches are human-triggered, long-running
    operations, never a tight loop.
    """
    try:
        from biracki_odbor import app_paths
        from biracki_odbor.config import settings as settings_mod
        value = settings_mod.load(app_paths.app_settings_path()).worker_stall_timeout_seconds
        return float(value)
    except Exception:
        return float(DEFAULT_STALL_TIMEOUT_SECONDS)


def start_worker(
    parent, fn: Callable[..., Any], *args,
    stall_timeout: float | None = None, **kwargs,
) -> tuple[Worker, QThread]:
    """Launch fn in a background thread. Returns (worker, thread).

    Caller is expected to connect worker.finished / worker.failed / worker.progress
    to slots before this returns control to the event loop — same contract
    as always. `stall_timeout` (seconds): abandon the wait and emit `failed`
    if the wrapped function reports no progress and doesn't finish within
    this window. Pass 0 to disable. Defaults to the operator's configured
    `AppSettings.worker_stall_timeout_seconds`.
    """
    thread = QThread(parent)
    worker = Worker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()

    if stall_timeout is None:
        stall_timeout = _default_stall_timeout()

    fn_name = getattr(fn, "__qualname__", str(fn))
    timer = QTimer(parent)
    timer.setInterval(_POLL_INTERVAL_MS)
    # Pin the timer's Python-side lifetime to `thread`, which every call
    # site already holds a reference to (`self._worker, self._thread =
    # start_worker(...)`) — independent of whether `parent` was given a
    # real QObject. Without this, a parent-less timer is only reachable
    # through the _poll closure's own reference cycle, which CPython's
    # cyclic GC can collect at an unpredictable time, silently stopping
    # the poll before the task ever reports completion.
    thread._poll_timer = timer  # type: ignore[attr-defined]

    def _poll() -> None:
        if worker.progress_state is not None:
            state = worker.progress_state
            worker.progress_state = None
            worker.progress.emit(*state)

        if worker.done:
            timer.stop()
            thread.quit()
            if worker.error is not None:
                worker.failed.emit(worker.error)
            else:
                worker.finished.emit(worker.result)
            return

        if stall_timeout and (time.monotonic() - worker.last_activity_at) > stall_timeout:
            timer.stop()
            log.error(
                "worker stalled: %s produced no progress for %.0fs — abandoning wait",
                fn_name, stall_timeout,
            )
            thread.quit()
            worker.failed.emit(
                f"Радња је прекинута — нема одзива {int(stall_timeout)} секунди."
            )
            return

    timer.timeout.connect(_poll)
    timer.start()

    return worker, thread
