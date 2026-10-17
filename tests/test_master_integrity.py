"""Integration tests for the master.xlsx (zbirana_tabela.xlsx) integrity
wiring — write=verify records a fingerprint, reads with verify=True
detect out-of-band tampering, CorrectionsTab owns the interactive
restore dialog, Phase3Tab stays passive (blocked, not popping a second
dialog) and — critically — refuses to send decision e-mails built from
unverified data."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "", raising=False)
    yield


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    from tests.test_phase1 import _make_oik
    from tests.test_phase3 import _make_election

    state = AppState()
    state._oik = _make_oik(2)  # noqa: SLF001
    state._election = _make_election()  # noqa: SLF001
    return state


def _seed_master(state, tmp_path) -> Path:
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.core.models import Person
    from biracki_odbor import app_paths

    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="1605991774818",
               email="ana@example.rs"),
    ]
    master = app_paths.master_path()
    write_master(persons, state.oik, master, verify=True)
    return master


def test_write_master_verify_records_fingerprint(tmp_path: Path) -> None:
    from biracki_odbor.core import file_integrity
    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    assert file_integrity.has_verified_copy(master)


def test_read_master_verify_passes_after_legitimate_write(tmp_path: Path) -> None:
    from biracki_odbor.core.master_io import read_master
    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    persons = read_master(master, verify=True)  # must not raise
    assert len(persons) == 1


def test_read_master_verify_raises_on_out_of_band_change(tmp_path: Path) -> None:
    from biracki_odbor.core.master_io import read_master
    from biracki_odbor.core.file_integrity import IntegrityMismatchError
    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)

    master.write_bytes(master.read_bytes() + b"\x00tampered")

    with pytest.raises(IntegrityMismatchError):
        read_master(master, verify=True)


def test_corrections_tab_reload_blocks_and_offers_restore(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    import unittest.mock as mock
    from PySide6.QtWidgets import QMessageBox

    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    good_content = master.read_bytes()

    # Construct on a CLEAN master first — CorrectionsTab.__init__ calls
    # reload_from_master() itself, unconditionally, before this test's
    # mock is active. Tampering before construction let a real, unmocked
    # QMessageBox fire from inside __init__ — hung this exact test for
    # ~6 hours in CI (no human there to click it) until forcibly
    # cancelled; reproduced locally too once looked for directly.
    tab = CorrectionsTab(state)
    try:
        master.write_bytes(b"tampered outside the app")
        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            tab.reload_from_master()
        # Restore accepted -> content back to the verified snapshot and
        # the tab re-loaded persons from it.
        assert master.read_bytes() == good_content
        assert len(tab._persons) == 1  # noqa: SLF001
    finally:
        tab.deleteLater()


def test_phase3_tab_blocks_without_popping_its_own_dialog(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    import unittest.mock as mock
    from PySide6.QtWidgets import QMessageBox

    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    master.write_bytes(b"tampered outside the app")

    tab = Phase3Tab(state)
    try:
        with mock.patch.object(QMessageBox, "warning") as mock_warning, \
             mock.patch.object(QMessageBox, "critical") as mock_critical:
            tab._refresh_preflight()  # noqa: SLF001 — must not raise
            mock_warning.assert_not_called()
            mock_critical.assert_not_called()
        assert not tab.btn_run.isEnabled()
        assert tab._master_integrity_error is not None  # noqa: SLF001
    finally:
        tab.deleteLater()


def test_phase3_run_is_a_safe_noop_when_master_is_tampered(app, tmp_path) -> None:
    """Defensive backstop: even if _run() is reached despite btn_run being
    disabled, it must not crash or generate decisions from bad data."""
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    master.write_bytes(b"tampered outside the app")

    tab = Phase3Tab(state)
    try:
        tab._run()  # noqa: SLF001 — must not raise
    finally:
        tab.deleteLater()


def test_send_decisions_refuses_on_tampered_master(app, tmp_path) -> None:
    """The most important guard: must never send official decision
    e-mails built from data we can't currently verify."""
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    import biracki_odbor.integrations.email_client as ec_mod
    import unittest.mock as mock

    state = _make_state(tmp_path)
    master = _seed_master(state, tmp_path)
    master.write_bytes(b"tampered outside the app")

    tab = Phase3Tab(state)
    try:
        with mock.patch.object(ec_mod, "create_drafts") as mock_create:
            tab._on_send_resenja_to_members()  # noqa: SLF001
            mock_create.assert_not_called()
    finally:
        tab.deleteLater()


def test_phase2_on_finished_records_verified_copy(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab
    from biracki_odbor.core.phase2_aggregate import Phase2Result
    from biracki_odbor.core.models import Person, ValidationReport
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.core import file_integrity
    from biracki_odbor import app_paths

    state = _make_state(tmp_path)
    master = app_paths.master_path()
    persons = [Person(bm_number=1, function="Председник", party="СНС")]
    write_master(persons, state.oik, master)  # NOT verified yet — simulates a pre-feature write
    assert not file_integrity.has_verified_copy(master)

    result = Phase2Result(persons=persons, master_path=master, report=ValidationReport(), files_processed=1)

    tab = Phase2Tab(state)
    try:
        tab._on_finished(result)  # noqa: SLF001
        assert file_integrity.has_verified_copy(master)
    finally:
        tab.deleteLater()
