"""RIK-submission lockdown: once decisions are submitted (izmena_mode),
Templates/Aggregation (Phase 1/2) are no longer needed for the rest of
the cycle and should be disabled the same way Decisions already was.

Covers both стални (MainWindow.tabs) and проширени (ProsireniWorkspace.tabs).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import _release_info
    # Documented opt-out: empty GITHUB_REPO disables the updater so tests
    # don't spawn a network-bound QThread that outlives them.
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_app():
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.gui.style import apply_global_style
    app = QApplication.instance() or QApplication([])
    apply_global_style(app)
    return app


def _teardown_main_window(app, w) -> None:
    """MainWindow schedules an immediate auto-backup check
    (QTimer.singleShot(0, ...)) plus an hourly repeating timer on
    construction. Left unstopped/undrained, these stay queued against
    this test's (about-to-be-deleted) tmp_path home and fire later,
    during whichever future test first pumps the event loop in a
    sustained way — seen causing a real CI failure in
    tests/test_updates.py, far later down the suite."""
    w._auto_backup_timer.stop()
    w.deleteLater()
    app.processEvents()


def _seed_template():
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import Allocation, PollingStation
    from biracki_odbor.core.template import build_blank_template
    stations = [PollingStation(bm_number=1, name="Школа А")]
    template_path = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
    build_blank_template(
        template_path, stations=stations,
        allocations=[Allocation(bm_number=1, function="Председник", party="СНС")],
    )
    return stations


def test_stalni_tabs_0_and_1_disabled_once_izmena_mode() -> None:
    app = _make_app()
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.main_window import MainWindow

    stations = _seed_template()
    state = AppState()
    state.oik.polling_stations = stations
    state.save_oik()
    gl = state.generation_log
    gl.record_phase("stalni", "phase1")
    gl.record_phase("stalni", "phase2")
    gl.record_phase("stalni", "phase3")
    state.save_generation_log()

    w = MainWindow()
    try:
        # Preconditions met, not yet submitted -- 0/1 stay enabled.
        assert w.tabs.isTabEnabled(0)
        assert w.tabs.isTabEnabled(1)

        # MainWindow() built its OWN AppState internally (separate object
        # from `state` above, though it read the same persisted files at
        # construction time) -- the live update must go through w.state so
        # its own generation_log_changed connection actually fires.
        w.state.generation_log.stalni.submit_to_rik()
        w.state.save_generation_log()

        assert not w.tabs.isTabEnabled(0)
        assert not w.tabs.isTabEnabled(1)
        # Корекције (2) stays available -- that's the amendment mechanism.
        assert w.tabs.isTabEnabled(2)
    finally:
        _teardown_main_window(app, w)


def test_stalni_current_tab_moves_off_disabled_tab() -> None:
    app = _make_app()
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.main_window import MainWindow

    stations = _seed_template()
    state = AppState()
    state.oik.polling_stations = stations
    state.save_oik()
    gl = state.generation_log
    gl.record_phase("stalni", "phase1")
    gl.record_phase("stalni", "phase2")
    gl.record_phase("stalni", "phase3")
    state.save_generation_log()

    w = MainWindow()
    try:
        w.stack.setCurrentIndex(1)  # SECTION_STALNI, per _go_to_corrections
        w.tabs.setCurrentIndex(0)  # sitting on the tab about to be disabled

        w.state.generation_log.stalni.submit_to_rik()
        w.state.save_generation_log()

        # Must not be left selected on a disabled tab.
        assert w.tabs.isTabEnabled(w.tabs.currentIndex())
        assert w.tabs.currentIndex() not in (0, 1)
    finally:
        _teardown_main_window(app, w)


def test_prosireni_tabs_0_1_3_disabled_once_izmena_mode() -> None:
    app = _make_app()
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = AppState()
    gl = state.generation_log
    gl.record_phase("prosireni", "phase1")
    gl.record_phase("prosireni", "phase2")
    gl.record_phase("prosireni", "phase3")
    state.save_generation_log()

    ws = ProsireniWorkspace(state)
    try:
        assert ws.tabs.isTabEnabled(0)
        assert ws.tabs.isTabEnabled(1)
        assert ws.tabs.isTabEnabled(3)

        gl.prosireni.submit_to_rik()
        state.save_generation_log()

        assert not ws.tabs.isTabEnabled(0)
        assert not ws.tabs.isTabEnabled(1)
        assert not ws.tabs.isTabEnabled(3)
        assert ws.tabs.isTabEnabled(2)  # Корекције stays available
        assert ws.tabs.isTabEnabled(4)  # Измене unlocks
    finally:
        ws.deleteLater()
        app.processEvents()


def test_prosireni_current_tab_moves_off_disabled_tab() -> None:
    app = _make_app()
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = AppState()
    gl = state.generation_log
    gl.record_phase("prosireni", "phase1")
    gl.record_phase("prosireni", "phase2")
    gl.record_phase("prosireni", "phase3")
    state.save_generation_log()

    ws = ProsireniWorkspace(state)
    try:
        ws.tabs.setCurrentIndex(1)

        gl.prosireni.submit_to_rik()
        state.save_generation_log()

        assert ws.tabs.isTabEnabled(ws.tabs.currentIndex())
        assert ws.tabs.currentIndex() not in (0, 1, 3)
    finally:
        ws.deleteLater()
        app.processEvents()
