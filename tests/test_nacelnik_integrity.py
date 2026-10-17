"""Integration tests for nacelnik_sablion.xlsx integrity wiring.

The chief's takeover template is written exactly once (at "Заустави
пријем пријава" time) and re-used by Export/Send from then on — this
covers the fingerprint being recorded at that write, and both re-use
sites detecting an out-of-band change and refusing to proceed (in
particular: Send must never mail out a document we can't verify)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(h))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)
    return h


def _make_person(bm: int, fn: str, *, party: str = "СНС", filled: bool = False):
    from biracki_odbor.core.models import Person
    if filled:
        return Person(
            bm_number=bm, function=fn, party=party,
            first_name="Ана", last_name="Анић", jmbg="1605991774818",
        )
    return Person(bm_number=bm, function=fn, party=party)


def _write_master(path, persons):
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.config.oik import OikConstants
    path.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, OikConstants(), path)


def _take_over(state, tab, monkeypatch, tmp_path):
    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod
    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)
    state.election.election.dates.cutoff_stalni = "2020-01-01"
    state.election_changed.emit()
    tab._on_nacelnik_takeover()  # noqa: SLF001


def test_takeover_records_verified_fingerprint(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core import file_integrity
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    tab = CorrectionsTab(state)
    try:
        _take_over(state, tab, monkeypatch, tmp_path)
        internal = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        assert file_integrity.has_verified_copy(internal)
    finally:
        tab.deleteLater()


def test_export_blocks_and_restores_on_tampered_file(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    import unittest.mock as mock
    from PySide6.QtWidgets import QMessageBox

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    popen_calls = []
    monkeypatch.setattr(
        "subprocess.Popen", lambda cmd, **kw: popen_calls.append(list(cmd)),
    )

    tab = CorrectionsTab(state)
    try:
        _take_over(state, tab, monkeypatch, tmp_path)
        internal = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        internal.write_bytes(b"tampered outside the app")

        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            tab.members_panel._on_nacelnik_export()  # noqa: SLF001

        # Restore accepted -> the retry (_on_nacelnik_export again)
        # regenerates the template fresh from the CURRENT generator
        # (see _regenerate_nacelnik_template) rather than just
        # reusing whatever the restore put back, so the result isn't
        # byte-identical to the pre-tamper content -- it's a brand
        # new, valid, current-shape file. Confirm it's a well-formed,
        # current-shape workbook rather than asserting byte equality.
        import openpyxl
        wb = openpyxl.load_workbook(internal)
        header = [c.value for c in next(wb.active.iter_rows(min_row=1, max_row=1))]
        wb.close()
        assert "Провера" in header
        from biracki_odbor.core import file_integrity
        assert file_integrity.has_verified_copy(internal)
    finally:
        tab.deleteLater()


def test_send_email_refuses_on_tampered_file(app, home, monkeypatch, tmp_path) -> None:
    """The critical guard: must never mail the chief a document that
    fails integrity verification."""
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    import biracki_odbor.integrations.email_client as ec_mod
    import unittest.mock as mock
    from PySide6.QtWidgets import QMessageBox

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    tab = CorrectionsTab(state)
    try:
        _take_over(state, tab, monkeypatch, tmp_path)
        internal = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        internal.write_bytes(b"tampered outside the app")

        # Decline the "restore?" offer too — either way, no draft may
        # be created for a file that failed verification.
        with mock.patch.object(ec_mod, "any_available", return_value=True), \
             mock.patch.object(ec_mod, "create_drafts") as mock_create, \
             mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
            tab.members_panel._on_nacelnik_send_email()  # noqa: SLF001
            mock_create.assert_not_called()
    finally:
        tab.deleteLater()


def test_export_ok_when_not_tampered(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    # _on_nacelnik_export() opens the export folder in a real Explorer
    # window on success (subprocess.Popen(["explorer", ...])) — capture
    # instead of letting a real window pop up and stay open every test run.
    popen_calls = []
    monkeypatch.setattr(
        "subprocess.Popen", lambda cmd, **kw: popen_calls.append(list(cmd)),
    )

    tab = CorrectionsTab(state)
    try:
        _take_over(state, tab, monkeypatch, tmp_path)
        tab.members_panel._on_nacelnik_export()  # noqa: SLF001 — must not raise/block
        exported = Path(state.app_settings.default_files_dir) / "Начелник" / "nacelnik_sablion.xlsx"
        assert exported.exists()
    finally:
        tab.deleteLater()
