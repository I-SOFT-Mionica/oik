"""Tests for spec-aware CorrectionsTab (Phase 2.5).

Pins the behaviour introduced when CorrectionsTab gained a ``spec``
parameter so both the stalni and prošireni workflows can share the
same tab class with their own master / log / audit paths and signals.

Covers:
  - Path helpers return spec-appropriate paths.
  - Cutoff label and audit button are present for stalni, absent for prosireni.
  - stalni tab connects to ``state.master_changed``; prosireni tab connects
    to ``state.prosireni_master_changed``.
  - The two signals are independent — emitting one does not reload the other
    workflow's tab (cross-contamination guard).
  - ``AppState.prosireni_master_changed`` exists and fires.
"""

from __future__ import annotations

import os

import pytest


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated app home directory."""
    h = tmp_path / "home"
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(h))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)
    return h


def _make_person(bm: int = 1, first: str = "Ана", last: str = "Анић",
                 jmbg: str = "0101990770010") -> "Person":
    from biracki_odbor.core.models import Person
    return Person(
        bm_number=bm, function="Председник", party="СНС",
        first_name=first, last_name=last, jmbg=jmbg,
        mesto="Уб", adresa="", telefon="", email="",
    )


def _write_master(path, persons, spec=None):
    """Write minimal master data so reload_from_master finds real data."""
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.config.oik import OikConstants
    path.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, OikConstants(), path, spec=spec)


# ── Path helper routing ───────────────────────────────────────────────────────


def test_stalni_tab_uses_stalni_paths(app, home) -> None:
    """CorrectionsTab(state) must route paths to the stalni directories."""
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab._master_path() == app_paths.master_path()
        assert tab._log_path() == app_paths.corrections_log_path()
        assert tab._audit_dir() == app_paths.audit_dir()
    finally:
        tab.deleteLater()


def test_prosireni_tab_uses_prosireni_paths(app, home) -> None:
    """CorrectionsTab(state, spec=PROSIRENI_SPEC) routes paths to prosireni directories."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        assert tab._master_path() == app_paths.master_path_for(PROSIRENI_SPEC)
        assert tab._log_path() == app_paths.corrections_log_path_for(PROSIRENI_SPEC)
        assert tab._audit_dir() == app_paths.audit_dir_for(PROSIRENI_SPEC)
        # Both workflows share one committee DB now (see core/master_io.py) --
        # the master PATH is deliberately the same; workflow separation
        # happens inside that shared file instead. Log/audit stay per-workflow.
        assert tab._master_path() == app_paths.master_path()
        assert tab._log_path() != app_paths.corrections_log_path()
    finally:
        tab.deleteLater()


# ── UI element presence ───────────────────────────────────────────────────────


def test_stalni_tab_has_cutoff_label_and_audit_button(app, home) -> None:
    """Stalni workflow needs both the cutoff-date label and the audit button."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab.lbl_cutoff is not None, "stalni tab must have a cutoff label"
        assert tab.btn_audit is not None, "stalni tab must have an audit button"
    finally:
        tab.deleteLater()


def test_prosireni_tab_hides_cutoff_label_and_audit_button(app, home) -> None:
    """Prosireni has no stalni cutoff date and no party-level audit trail."""
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        assert tab.lbl_cutoff is None, "prosireni tab must not have a cutoff label"
        assert tab.btn_audit is None, "prosireni tab must not have an audit button"
    finally:
        tab.deleteLater()


def test_export_master_button_exists_for_both_workflows_and_toggles_with_file(app, home) -> None:
    """Export button (bottom action bar, matching Tab 1/2's convention)
    must exist for both stalni and prosireni, and reflect whether the
    consolidated table actually exists on disk.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab.btn_export_master is not None
        assert not tab.btn_export_master.isEnabled()
        _write_master(app_paths.master_path(), [_make_person()])
        tab.reload_from_master()
        assert tab.btn_export_master.isEnabled()
    finally:
        tab.deleteLater()

    state2 = AppState()
    prosireni_tab = CorrectionsTab(state2, spec=PROSIRENI_SPEC)
    try:
        assert prosireni_tab.btn_export_master is not None
    finally:
        prosireni_tab.deleteLater()


# ── Signal wiring: stalni ────────────────────────────────────────────────────


def test_stalni_tab_reloads_on_master_changed(app, home) -> None:
    """state.master_changed must trigger reload in the stalni CorrectionsTab."""
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab._persons == []  # no master file yet

        # Create a stalni master after the tab is already constructed.
        _write_master(app_paths.master_path(), [_make_person()])

        # Emitting master_changed should cause the tab to reload from disk.
        state.master_changed.emit()
        assert len(tab._persons) == 1
        assert tab._persons[0].first_name == "Ана"
    finally:
        tab.deleteLater()


def test_prosireni_master_changed_does_not_reload_stalni_tab(app, home) -> None:
    """state.prosireni_master_changed must NOT trigger reload in the stalni tab.

    Cross-contamination guard: emitting the wrong signal must be a no-op.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)  # stalni (no spec)
    try:
        # Write stalni master but signal with prosireni signal — must not reload.
        _write_master(app_paths.master_path(), [_make_person()])
        state.prosireni_master_changed.emit()
        assert tab._persons == [], (
            "stalni tab must not reload on prosireni_master_changed"
        )
    finally:
        tab.deleteLater()


# ── Signal wiring: prosireni ─────────────────────────────────────────────────


def test_prosireni_tab_reloads_on_prosireni_master_changed(app, home) -> None:
    """state.prosireni_master_changed must trigger reload in the prosireni tab."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        assert tab._persons == []

        _write_master(app_paths.master_path_for(PROSIRENI_SPEC), [_make_person()], spec=PROSIRENI_SPEC)

        state.prosireni_master_changed.emit()
        assert len(tab._persons) == 1
        assert tab._persons[0].first_name == "Ана"
    finally:
        tab.deleteLater()


def test_stalni_master_changed_does_not_reload_prosireni_tab(app, home) -> None:
    """state.master_changed must NOT trigger reload in the prosireni tab."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        _write_master(app_paths.master_path_for(PROSIRENI_SPEC), [_make_person()], spec=PROSIRENI_SPEC)
        # Use the wrong signal (stalni) — must be a no-op for the prosireni tab.
        state.master_changed.emit()
        assert tab._persons == [], (
            "prosireni tab must not reload on stalni master_changed"
        )
    finally:
        tab.deleteLater()


# ── Master isolation ──────────────────────────────────────────────────────────


def test_stalni_and_prosireni_masters_are_independent(app, home) -> None:
    """Writing data to the prosireni master must not affect the stalni tab.

    Regression guard for the case where both tabs share a home directory
    but each workflow's data lives in its own subdirectory.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    stalni_tab = CorrectionsTab(state)
    prosireni_tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        # Only prosireni master exists.
        _write_master(app_paths.master_path_for(PROSIRENI_SPEC), [_make_person()], spec=PROSIRENI_SPEC)

        state.prosireni_master_changed.emit()
        assert len(prosireni_tab._persons) == 1
        # Stalni tab must remain empty — it has no master, and its signal
        # (master_changed) was never emitted.
        assert stalni_tab._persons == []
    finally:
        stalni_tab.deleteLater()
        prosireni_tab.deleteLater()


# ── §21: nacelnik section (base-tab-level, cutoff-gated) ─────────────────────


def test_nacelnik_section_exists_for_stalni_not_prosireni(app, home) -> None:
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab._nacelnik_section is not None
        assert tab._nacelnik_section.is_expanded() is False, (
            "must be collapsed by default per §21"
        )
    finally:
        tab.deleteLater()

    state2 = AppState()
    prosireni_tab = CorrectionsTab(state2, spec=PROSIRENI_SPEC)
    try:
        assert prosireni_tab._nacelnik_section is None
    finally:
        prosireni_tab.deleteLater()


def test_nacelnik_section_visible_regardless_of_active_inner_subtab(app, home) -> None:
    """§21 requirement: reachable from the base tab, not just Сви чланови."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        tab.inner.setCurrentWidget(tab.conflicts_panel)
        assert tab._nacelnik_section.isVisibleTo(tab)
    finally:
        tab.deleteLater()


def test_nacelnik_buttons_disabled_until_takeover_not_just_cutoff(app, home) -> None:
    """A past cutoff_stalni alone must NOT unlock the appointment
    buttons — only the operator's explicit "Stop accepting submissions"
    click (WorkflowLog.start_nacelnik_takeover) does. This was the
    whole point of replacing the pure date-gate."""
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    _write_master(app_paths.master_path(), [_make_person()])
    tab = CorrectionsTab(state)
    try:
        panel = tab.members_panel
        panel.table.selectRow(0)  # the one row from _write_master
        assert not panel.btn_nacelnik.isEnabled()
        assert not panel.btn_nacelnik_export.isEnabled()
        assert not panel.btn_nacelnik_send.isEnabled()
        assert not panel.btn_nacelnik_inbox.isEnabled()
        assert not panel.btn_nacelnik_import.isEnabled()

        # A past cutoff alone changes nothing for the appointment
        # buttons — it only unlocks the takeover button itself.
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        assert not panel.btn_nacelnik_export.isEnabled()
        assert tab.btn_nacelnik_takeover.isEnabled(), (
            "the takeover button itself unlocks once the cutoff has passed"
        )

        # Only the explicit takeover declaration unlocks the appointment
        # buttons — mirrors "Предато РИК-у", not a date comparison.
        state.generation_log.workflow("stalni").start_nacelnik_takeover()
        state.generation_log_changed.emit()
        assert panel.btn_nacelnik_export.isEnabled()
        assert panel.btn_nacelnik_send.isEnabled()
        assert panel.btn_nacelnik_inbox.isEnabled()
        assert panel.btn_nacelnik_import.isEnabled()
        assert not tab.btn_nacelnik_takeover.isVisible()
    finally:
        tab.deleteLater()


def test_nacelnik_takeover_button_disabled_before_cutoff(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert not tab.btn_nacelnik_takeover.isEnabled(), (
            "no cutoff configured — must stay disabled"
        )
        state.election.election.dates.cutoff_stalni = "2099-01-01"
        state.election_changed.emit()
        assert not tab.btn_nacelnik_takeover.isEnabled(), "future cutoff — still disabled"
    finally:
        tab.deleteLater()


def test_nacelnik_section_locked_until_takeover(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert tab._nacelnik_section.is_locked()
        state.generation_log.workflow("stalni").start_nacelnik_takeover()
        state.generation_log_changed.emit()
        assert not tab._nacelnik_section.is_locked()
    finally:
        tab.deleteLater()


# ── AppState.prosireni_master_changed ────────────────────────────────────────


def test_app_state_prosireni_master_changed_signal_exists_and_fires(app, home) -> None:
    """AppState must expose prosireni_master_changed and it must fire when emitted."""
    from biracki_odbor.gui.app_state import AppState

    state = AppState()
    fired = []
    state.prosireni_master_changed.connect(lambda: fired.append(True))

    assert fired == []
    state.prosireni_master_changed.emit()
    assert fired == [True]

    # A second emit adds a second entry (not deduplicated).
    state.prosireni_master_changed.emit()
    assert fired == [True, True]
