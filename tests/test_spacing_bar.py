"""Tests for gui.widgets.spacing_bar.DocumentSpacingBar.

Field report: rapid-fire valueChanged ticks while typing into Пре/После
each synchronously called _save(), which (via the `changed` signal)
triggers a full paginated-preview page re-render on every keystroke --
the actual cause of a reported UI lag (much worse on slower hardware)
and, plausibly, of the fields sometimes painting blank (the heavy
rebuild running reentrantly inside the spinbox's own valueChanged
handling). Saves are now debounced; editingFinished still flushes
immediately so blur/tab-away never drops the last keystroke.
"""
from __future__ import annotations

from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.spacing_bar import BLOCK_TITLE, DocumentSpacingBar


def _make_bar() -> DocumentSpacingBar:
    state = AppState()
    bar = DocumentSpacingBar(state)
    bar.cb_block.setCurrentIndex(bar.cb_block.findData(BLOCK_TITLE))
    return bar


def test_rapid_typing_does_not_save_immediately():
    bar = _make_bar()
    changed_count = 0
    bar.changed.connect(lambda: None)  # keep signal alive for count below
    counts = []
    bar.changed.connect(lambda: counts.append(1))

    original = bar.state.oik.document_format.title_before_pt
    # Simulate several rapid keystrokes changing the value.
    for v in (1, 12, 5):
        bar.sb_before.setValue(v)

    assert bar._save_timer.isActive(), "debounce timer should be pending, not fired yet"
    assert bar.state.oik.document_format.title_before_pt == original, (
        "value must not be persisted until the debounce window elapses"
    )
    assert counts == [], "changed must not fire until the debounce window elapses"


def test_editing_finished_flushes_pending_save_immediately():
    bar = _make_bar()
    bar.sb_before.setValue(12)
    assert bar._save_timer.isActive()

    bar.sb_before.editingFinished.emit()

    assert not bar._save_timer.isActive(), "flush must cancel the pending timer"
    assert bar.state.oik.document_format.title_before_pt == 12.0


def test_debounced_save_eventually_applies():
    bar = _make_bar()
    bar.sb_before.setValue(7)
    assert bar._save_timer.isActive()

    # Fire the timeout directly rather than sleeping out the real delay --
    # same code path the real QTimer would invoke once it elapses.
    bar._save_timer.timeout.emit()

    assert bar.state.oik.document_format.title_before_pt == 7.0
