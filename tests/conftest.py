"""Test-session fixtures + Windows Qt-shutdown workaround.

The smoke tests in test_e2e.py construct top-level QWidgets
(MainWindow, Installer wizard, Uninstaller wizard). On Windows the
process occasionally exits with 0xC0000409 (STATUS_STACK_BUFFER_OVERRUN)
AFTER pytest already reports "all passed" — Qt's QApplication
destructor races with Python's gc reclaiming sip-wrapper objects
during interpreter shutdown, so a green test run still flips the CI
job red.

The pytest_sessionfinish hook below short-circuits Python's shutdown
sequence with os._exit() once pytest has decided the run is fully
green. We've already printed the summary, written any cached pyc
files, and run fixture finalizers by that point — the only remaining
work is destructors, which is exactly what's broken. Skipping them on
a passing session is the well-documented workaround in the
PySide6/PyQt6 ecosystem for this specific exit-code.

Limited to passing runs so that failures still flow through normal
shutdown (preserves coverage flushes, junitxml writes, etc., for the
case where the operator needs the full pytest exit-code semantics).
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _sandbox_home_documents(tmp_path, monkeypatch):
    """Prevent `AppState.files_dir()`'s fallback (`Path.home() / "Documents"`)
    from ever touching the real Documents folder in a test that doesn't
    explicitly set `default_files_dir`. Without this, any test that
    reaches `files_dir()`/`export_generated()` (button handlers,
    `_on_finished` callbacks, ...) silently creates real folders under
    the machine's actual Documents directory — found the hard way when
    a plain test run left empty "Извештаји"/"Странке (проширени)"/
    "Решења (проширени)" folders in the developer's real Documents.

    Tests that specifically exercise the real-fallback behavior itself
    (e.g. `test_app_state_files_dir.py`) can still monkeypatch
    `Path.home()` again inside the test body — same `monkeypatch`
    instance, so the later patch simply wins.
    """
    fake_home = tmp_path / "_fake_user_home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))


@pytest.fixture(scope="session", autouse=True)
def _qapp_session():
    """Singleton QApplication + best-effort widget teardown.

    Closes top-level widgets and drains the event queue so widgets
    are destroyed inside pytest's session teardown rather than
    during interpreter shutdown — reduces (but doesn't eliminate)
    the Qt-Python lifecycle race. The os._exit() in
    pytest_sessionfinish is the belt-and-suspenders fix.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
        except RuntimeError:
            # C++ side already deleted — ignore
            pass
    for _ in range(3):
        app.processEvents()
        gc.collect()


@pytest.fixture(autouse=True)
def _drain_qt_events_after_each_test():
    """Actually run each test's `widget.deleteLater()` calls before the
    next test starts, instead of leaving them queued for the rest of
    the whole session.

    `deleteLater()` only SCHEDULES destruction of the C++ QObject --
    nothing runs it until the event loop is pumped. Many tests across
    test_phase3*.py/test_izmene.py call it in a `finally:` block but
    never follow with `processEvents()` (confirmed: test_izmene.py has
    12 deleteLater() calls and 0 processEvents() calls), so those
    widgets stay fully alive, including their signal connections to
    the GLOBAL QApplication.focusChanged (added this session, for the
    preview's anchor-jump feature) -- every later test's focus changes
    anywhere then re-invoke ALL of them, cumulatively. That tracks
    exactly what CI showed: tests get progressively slower deeper into
    the suite (traced to a growing multi-second delay starting right
    after the phase3/izmene test files), and the final teardown
    destroying hundreds of accumulated instances at once is a far
    bigger event than the Windows Qt-shutdown race was ever tuned
    against.

    Draining per-test instead keeps each test's widgets' lifetime
    bounded to that test, the same as production usage (where exactly
    one Phase3Tab/IzmenaPanel exists at a time, never hundreds).

    Also closes+deletes any top-level widget still standing (MainWindow,
    Phase3Tab, ElectionSettingsTab, FilloutScreen, NewTemplateDialog, ...)
    -- the same safety net _qapp_session already applies, but every test
    instead of once at the very end of the session. Plenty of individual
    tests construct a top-level widget and never close+deleteLater() it
    themselves; each survivor keeps its whole child-widget tree (every
    QLineEdit/QComboBox/QPushButton inside it, plus Qt's own internal
    combobox/menu popups) reachable for the rest of the run.

    The QEventLoop spin (not just processEvents()) is load-bearing.
    Measured with a local memory profiler: with only close()+deleteLater()
    +processEvents() here (what this fixture used to do), live widgets
    still climbed to ~64,000 / ~3.4GB committed by ~80% through the suite
    -- processEvents() alone never drained them, no matter how many times
    it was called across however many tests. A QEventLoop().exec() spin
    (even a 0ms one) does drain them immediately, every test. Qt's
    DeferredDelete event is loop-level-gated: it's only delivered once
    the loop unwinds back to (or below) the nesting level it was posted
    at, and plain processEvents() doesn't change the loop level the way
    a real nested exec() does. That gating is why these specific events
    could sit queued for hundreds of tests. Confirmed via the same
    profiler: this version caps the peak at ~3,500 widgets / ~1GB
    committed for the whole suite, instead of the ~64,000/~3.4GB peak
    -- which was the actual MemoryError-then-abort root cause behind the
    CI job reporting exit code 1 a few seconds after a clean "N passed"."""
    yield
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    for _ in range(3):
        app.processEvents()
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()


# Captured by pytest_sessionfinish, replayed by pytest_unconfigure. Two
# hooks because the final "N passed" summary line is written by
# pytest_terminal_summary, which runs BETWEEN sessionfinish and
# unconfigure — so we have to wait until unconfigure to kill the
# process, or the summary never lands in the CI log.
_session_exitstatus: int | None = None


def pytest_sessionfinish(session, exitstatus):
    global _session_exitstatus
    _session_exitstatus = int(exitstatus)


def pytest_unconfigure(config):
    """Hard-exit after a passing run on Windows to dodge Qt's shutdown crash.

    Only applies when:
      - we're on Windows (the crash is Windows-specific),
      - the run was fully green (exitstatus == 0),
      - PySide6.QtWidgets has been imported (QApplication exists).

    Runs after pytest_terminal_summary so the "N passed" line still
    lands in the log.
    """
    if sys.platform != "win32":
        return
    if _session_exitstatus != 0:
        return
    if "PySide6.QtWidgets" not in sys.modules:
        return
    try:
        import faulthandler
        faulthandler.disable()
    except Exception:  # noqa: BLE001 — best-effort, never mask the exit
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 — best-effort, never mask the exit
        pass
    os._exit(0)
