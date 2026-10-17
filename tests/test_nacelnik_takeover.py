"""Tests for the nacelnik hard-stop: an explicit, deliberate operator
decision ("Заустави пријем пријава") that replaces the pure
cutoff_stalni date-gate for nacelnik appointment — modeled on the
existing "Предато РИК-у" pattern.

Covers:
  - WorkflowLog.nacelnik_takeover_ts / nacelnik_appointments round-trip,
    idempotency, revert.
  - GenerationLog to_dict/from_dict preserves the new fields.
  - append_nacelnik_takeover writes the audit event.
  - CollapsibleSection.set_locked blocks user-triggered toggle only.
  - CorrectionsTab: full takeover flow (confirm → generate template →
    export → unlock section → block Phase 2 imports), revert blocked
    once an appointment has been made.
  - Пошаљи/Извези auto-attach the takeover-time template, no file
    picker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.core.corrections import append_nacelnik_takeover, read_log
from biracki_odbor.core.generation_log import GenerationLog, WorkflowLog


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


# ── WorkflowLog / GenerationLog ──────────────────────────────────────


def test_workflow_log_takeover_initial_state() -> None:
    wl = WorkflowLog()
    assert wl.nacelnik_takeover_ts == 0
    assert wl.nacelnik_appointments == 0
    assert not wl.nacelnik_takeover_started()


def test_workflow_log_start_takeover_sets_timestamp() -> None:
    wl = WorkflowLog()
    wl.start_nacelnik_takeover()
    assert wl.nacelnik_takeover_ts > 0
    assert wl.nacelnik_takeover_started()


def test_workflow_log_start_takeover_idempotent() -> None:
    wl = WorkflowLog()
    wl.start_nacelnik_takeover()
    first = wl.nacelnik_takeover_ts
    wl.start_nacelnik_takeover()
    assert wl.nacelnik_takeover_ts == first


def test_workflow_log_record_appointment_increments() -> None:
    wl = WorkflowLog()
    wl.record_nacelnik_appointment()
    wl.record_nacelnik_appointment()
    wl.record_nacelnik_appointment(3)
    assert wl.nacelnik_appointments == 5


def test_workflow_log_revert_clears_both_fields() -> None:
    wl = WorkflowLog()
    wl.start_nacelnik_takeover()
    wl.record_nacelnik_appointment(2)
    wl.revert_nacelnik_takeover()
    assert wl.nacelnik_takeover_ts == 0
    assert wl.nacelnik_appointments == 0
    assert not wl.nacelnik_takeover_started()


def test_generation_log_round_trip_preserves_takeover_fields() -> None:
    gl = GenerationLog(election_uuid="u1")
    gl.stalni.start_nacelnik_takeover()
    gl.stalni.record_nacelnik_appointment(4)
    gl2 = GenerationLog.from_dict(gl.to_dict())
    assert gl2.stalni.nacelnik_takeover_ts == gl.stalni.nacelnik_takeover_ts
    assert gl2.stalni.nacelnik_appointments == 4


def test_generation_log_from_dict_legacy_defaults_to_zero() -> None:
    """Old generation_log.json files (pre-this-feature) have neither
    field — must default to 0/not-started, not crash."""
    from biracki_odbor.core.generation_log import _wl_from_dict
    wl = _wl_from_dict({})
    assert wl.nacelnik_takeover_ts == 0
    assert wl.nacelnik_appointments == 0


# ── append_nacelnik_takeover ──────────────────────────────────────────


def test_append_nacelnik_takeover_writes_event(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    append_nacelnik_takeover(log_path, "stalni")
    events = read_log(log_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "nacelnik_takeover"
    assert "stalni" in events[0]["note"]


def test_append_nacelnik_takeover_creates_parent_dirs(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "dir" / "audit.log"
    append_nacelnik_takeover(log_path, "stalni")
    assert log_path.exists()


# ── CollapsibleSection.set_locked ─────────────────────────────────────


def test_collapsible_section_locked_blocks_toggle(app) -> None:
    from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
    section = CollapsibleSection("Test", initially_expanded=False)
    try:
        section.set_locked(True)
        assert section.is_locked()
        section.toggle()
        assert not section.is_expanded(), "toggle() must no-op while locked"
    finally:
        section.deleteLater()


def test_collapsible_section_unlocked_allows_toggle(app) -> None:
    from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
    section = CollapsibleSection("Test", initially_expanded=False)
    try:
        section.set_locked(False)
        section.toggle()
        assert section.is_expanded()
    finally:
        section.deleteLater()


def test_collapsible_section_set_expanded_works_while_locked(app) -> None:
    """Programmatic control (set_expanded) must still work even while
    locked — only the user-facing toggle() is blocked."""
    from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
    section = CollapsibleSection("Test", initially_expanded=False)
    try:
        section.set_locked(True)
        section.set_expanded(True)
        assert section.is_expanded()
    finally:
        section.deleteLater()


def test_collapsible_section_arrow_and_toggle_button_disabled_when_locked(app) -> None:
    from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
    section = CollapsibleSection("Test")
    try:
        section.set_locked(True)
        assert not section._arrow.isEnabled()  # noqa: SLF001
        assert not section._btn_toggle.isEnabled()  # noqa: SLF001
        section.set_locked(False)
        assert section._arrow.isEnabled()  # noqa: SLF001
        assert section._btn_toggle.isEnabled()  # noqa: SLF001
    finally:
        section.deleteLater()


# ── CorrectionsTab: full takeover flow ────────────────────────────────


def test_takeover_button_disabled_until_cutoff_passes(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert not tab.btn_nacelnik_takeover.isEnabled()
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        assert tab.btn_nacelnik_takeover.isEnabled()
    finally:
        tab.deleteLater()


def test_takeover_confirm_generates_template_and_unlocks(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])  # empty slot

    # Simulate the operator toggling on and clicking Confirm.
    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)

    tab = CorrectionsTab(state)
    try:
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        assert tab.btn_nacelnik_takeover.isEnabled()

        tab._on_nacelnik_takeover()  # noqa: SLF001

        wl = state.generation_log.workflow("stalni")
        assert wl.nacelnik_takeover_started()
        assert not tab._nacelnik_section.is_locked()  # noqa: SLF001
        # Deliberately NOT auto-expanded — the takeover quick-action
        # button only exists while the box is collapsed, so forcing it
        # open here would immediately hide the Reopen quick-action too.
        assert not tab._nacelnik_section.is_expanded()  # noqa: SLF001
        assert not tab.btn_nacelnik_takeover.isVisibleTo(tab)
        assert tab.btn_nacelnik_takeover_revert.isVisibleTo(tab)

        internal = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        assert internal.exists()
        exported = Path(state.app_settings.default_files_dir) / "Начелник" / "nacelnik_sablion.xlsx"
        assert exported.exists()
    finally:
        tab.deleteLater()


# ── Demo mode: chief's takeover must not bypass the one-BM limit ─────


def test_takeover_in_demo_mode_only_covers_the_demo_bm(app, home, monkeypatch, tmp_path) -> None:
    """Field report: generate_party_files' demo-mode limit only ever
    restricted what parties could submit -- the chief's takeover pulled
    straight from the master's full empty-slot list across every BM, so
    a demo user could hand everything else to the chief and get
    fully-populated resenja for the whole municipality without a
    license. The chief's template must only ever cover the same single
    (lowest-numbered) BM the rest of demo mode is limited to."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from biracki_odbor.licensing.state import License, Mode
    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod

    state = AppState()
    state._oik.polling_stations = [  # noqa: SLF001
        PollingStation(bm_number=1, name="БМ 1"),
        PollingStation(bm_number=2, name="БМ 2"),
    ]
    state._license = License(mode=Mode.DEMO, reason="no_license_file")  # noqa: SLF001
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [
        _make_person(1, "Председник"),          # empty slot, demo BM
        _make_person(1, "Заменик председника"),  # empty slot, demo BM
        _make_person(2, "Председник"),          # empty slot, NOT the demo BM
    ])

    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)

    tab = CorrectionsTab(state)
    try:
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        tab._on_nacelnik_takeover()  # noqa: SLF001

        internal = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        # A freshly-generated template has empty (unfilled) input cells,
        # which read_nacelnik_xlsx's own "every slot must be filled"
        # validation rejects -- read the raw БМ column instead of the
        # strict reader, which is meant for completed submissions.
        import openpyxl
        wb = openpyxl.load_workbook(internal)
        ws = wb.active
        assert ws.cell(row=1, column=2).value == "БМ бр.", "column layout assumption broken"
        bm_numbers = {
            row[1].value for row in ws.iter_rows(min_row=3)  # col 2 = "БМ бр."
            if row[1].value is not None
        }
        wb.close()
        assert bm_numbers == {1}, (
            "chief's template must only cover BM 1 (the demo BM) in demo mode"
        )
    finally:
        tab.deleteLater()


def test_import_rejects_hand_edited_bm_outside_demo_limit(app, home, monkeypatch, tmp_path) -> None:
    """Defense-in-depth: the generated template only covers the demo BM,
    but its sheet protection isn't real security. If a demo user hand-
    edits the file to add a row for another BM, import must still
    reject it rather than silently appointing outside the demo limit."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.core.nacelnik_xlsx import export_nacelnik_template
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from biracki_odbor.licensing.state import License, Mode
    from tests.test_jmbg import VALID_SAMPLES
    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod
    import openpyxl

    state = AppState()
    state._oik.polling_stations = [  # noqa: SLF001
        PollingStation(bm_number=1, name="БМ 1"),
        PollingStation(bm_number=2, name="БМ 2"),
    ]
    state._license = License(mode=Mode.DEMO, reason="no_license_file")  # noqa: SLF001
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [
        _make_person(1, "Председник"),  # empty slot, demo BM
        _make_person(2, "Председник"),  # empty slot, NOT the demo BM
    ])

    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)

    tab = CorrectionsTab(state)
    try:
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        tab._on_nacelnik_takeover()  # noqa: SLF001

        # Simulate a hand-edited file: rebuild the template covering BOTH
        # BMs (bypassing the takeover's own restriction, as a tampered
        # file would) and fill in both rows completely.
        tampered = tmp_path / "tampered.xlsx"
        export_nacelnik_template(
            [p for p in tab.corrections.persons if not p.is_filled],
            {1: PollingStation(bm_number=1, name="БМ 1"),
             2: PollingStation(bm_number=2, name="БМ 2")},
            tampered,
        )
        wb = openpyxl.load_workbook(tampered)
        ws = wb.active
        for row_idx in (3, 4):
            ws.cell(row=row_idx, column=5, value="Име")
            ws.cell(row=row_idx, column=6, value="Презиме")
            ws.cell(row=row_idx, column=7, value=VALID_SAMPLES[row_idx - 3])
        wb.save(tampered)
        wb.close()

        from PySide6.QtWidgets import QMessageBox
        import unittest.mock as mock
        with mock.patch.object(QMessageBox, "critical") as m:
            tab.members_panel._import_from_path(str(tampered))  # noqa: SLF001

        m.assert_called_once()
        detail = m.call_args[0][2]
        assert "демо режиму" in detail
        # Nothing appointed -- the whole import is rejected, not just BM 2's row.
        assert all(not p.is_filled for p in tab.corrections.persons)
    finally:
        tab.deleteLater()


def test_takeover_revert_blocked_after_appointment(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QMessageBox

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **kw: warned.append(True),
    )

    tab = CorrectionsTab(state)
    try:
        wl = state.generation_log.workflow("stalni")
        wl.start_nacelnik_takeover()
        wl.record_nacelnik_appointment()
        state.save_generation_log()
        tab._update_nacelnik_takeover_ui()  # noqa: SLF001

        assert not tab.btn_nacelnik_takeover_revert.isVisibleTo(tab), (
            "revert must hide once an appointment has been made"
        )

        # Direct call defense-in-depth check (even if somehow triggered).
        tab._on_nacelnik_takeover_revert()  # noqa: SLF001
        assert warned
        assert wl.nacelnik_takeover_started(), "must remain active — revert refused"
    finally:
        tab.deleteLater()


def test_takeover_revert_allowed_before_any_appointment(app, home, monkeypatch, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QMessageBox

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)

    tab = CorrectionsTab(state)
    try:
        wl = state.generation_log.workflow("stalni")
        wl.start_nacelnik_takeover()
        state.save_generation_log()
        tab._update_nacelnik_takeover_ui()  # noqa: SLF001
        assert tab.btn_nacelnik_takeover_revert.isVisibleTo(tab)

        tab._on_nacelnik_takeover_revert()  # noqa: SLF001

        assert not wl.nacelnik_takeover_started()
        assert tab._nacelnik_section.is_locked()  # noqa: SLF001
        assert tab.btn_nacelnik_takeover.isVisibleTo(tab)
    finally:
        tab.deleteLater()


def test_appointment_increments_counter(app, home, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation, FUNCTIONS
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QDialog

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])

    tab = CorrectionsTab(state)
    try:
        wl = state.generation_log.workflow("stalni")
        wl.start_nacelnik_takeover()
        state.save_generation_log()
        tab._update_nacelnik_takeover_ui()  # noqa: SLF001

        panel = tab.members_panel
        panel.table.selectRow(0)
        from unittest.mock import patch
        from biracki_odbor.gui.tabs.corrections import _PersonEditDialog
        with patch.object(_PersonEditDialog, "exec", return_value=QDialog.Accepted), \
             patch.object(_PersonEditDialog, "values", return_value={"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"}), \
             patch.object(_PersonEditDialog, "note", return_value=""):
            panel._on_nacelnik_appoint()  # noqa: SLF001

        assert wl.nacelnik_appointments == 1
    finally:
        tab.deleteLater()


# ── Пошаљи/Извези auto-attach (no file picker) ────────────────────────


def test_nacelnik_send_email_no_template_shows_warning_not_dialog(app, home, monkeypatch, tmp_path) -> None:
    """No template generated yet (takeover never happened) — must warn
    the operator, never open a file picker asking them to find one."""
    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from biracki_odbor.integrations import email_client as ec_mod

    dialog_calls = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *a, **kw: dialog_calls.append(True) or ("", ""),
    )
    monkeypatch.setattr(ec_mod, "any_available", lambda: True)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warned.append(True))

    state = AppState()
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])
    tab = CorrectionsTab(state)
    try:
        panel = tab.members_panel
        panel._on_nacelnik_send_email()  # noqa: SLF001
        assert not dialog_calls, "must never open a file picker for Пошаљи"
        assert warned, "must warn that no template exists yet"
    finally:
        tab.deleteLater()


def test_nacelnik_send_email_regenerates_stale_template(app, home, monkeypatch, tmp_path) -> None:
    """Field report: once a template was generated at takeover time, every
    later Пошаљи just re-attached that same file forever -- so a template
    generated before some later improvement to export_nacelnik_template()
    (JMBG validation, etc.) stayed stuck looking exactly as it did back
    then no matter how much the generator itself improved since. Пошаљи
    must regenerate fresh from the CURRENT generator every time, not
    reattach whatever is sitting on disk -- simulated here by corrupting
    the real post-takeover template to stand in for "a stale pre-fix
    file" and confirming what actually gets attached is a fresh, valid
    xlsx, not that stale content."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    from biracki_odbor.integrations import email_client as ec_mod

    dialog_calls = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *a, **kw: dialog_calls.append(True) or ("", ""),
    )
    monkeypatch.setattr(ec_mod, "any_available", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("chief@example.rs", True))
    attached = []
    monkeypatch.setattr(
        ec_mod, "create_drafts",
        lambda drafts, **kw: attached.append(drafts[0].attachment) or [
            type("R", (), {"ok": True})()
        ],
    )

    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])
    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)
    tab = CorrectionsTab(state)
    try:
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        tab._on_nacelnik_takeover()  # noqa: SLF001

        template = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        # Stand in for "generated under an older, less-validated version
        # of export_nacelnik_template" -- re-stamp its fingerprint too so
        # this is "stale content the app itself wrote a while ago", not
        # "tampered outside the app" (a different, already-covered case
        # in test_nacelnik_integrity.py).
        template.write_bytes(b"stale pre-fix xlsx content, no JMBG column at all")
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(template)

        tab.members_panel._on_nacelnik_send_email()  # noqa: SLF001

        assert not dialog_calls, "must never open a file picker for Пошаљи"
        assert attached == [template]
        assert template.read_bytes() != b"stale pre-fix xlsx content, no JMBG column at all", (
            "must regenerate the file fresh, not re-attach the stale one"
        )
        import openpyxl
        wb = openpyxl.load_workbook(template)
        header = [c.value for c in next(wb.active.iter_rows(min_row=1, max_row=1))]
        wb.close()
        assert "Провера" in header, "regenerated file must have the current JMBG-validation column"
    finally:
        tab.deleteLater()


def test_nacelnik_export_regenerates_stale_template_no_dialog(app, home, monkeypatch, tmp_path) -> None:
    """Same fix as Пошаљи above, for Извези."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    from PySide6.QtWidgets import QFileDialog
    import biracki_odbor.gui.dialogs.confirm_dialog as confirm_dialog_mod

    dialog_calls = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **kw: dialog_calls.append(True) or ("", ""),
    )
    popen_calls = []
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )
    monkeypatch.setattr(confirm_dialog_mod, "confirm_with_toggle", lambda *a, **kw: True)

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    _write_master(app_paths.master_path(), [_make_person(1, "Председник")])
    tab = CorrectionsTab(state)
    try:
        state.election.election.dates.cutoff_stalni = "2020-01-01"
        state.election_changed.emit()
        tab._on_nacelnik_takeover()  # noqa: SLF001

        template = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        template.write_bytes(b"stale pre-fix xlsx content, no JMBG column at all")
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(template)

        tab.members_panel._on_nacelnik_export()  # noqa: SLF001

        assert not dialog_calls, "must never open a save-file dialog for Извези"
        exported_dir = Path(state.app_settings.default_files_dir) / "Начелник"
        exported = exported_dir / "nacelnik_sablion.xlsx"
        assert exported.exists()
        assert exported.read_bytes() != b"stale pre-fix xlsx content, no JMBG column at all", (
            "must export a freshly regenerated file, not the stale one"
        )
        assert popen_calls == [["explorer", str(exported_dir)]], (
            "Извези must open the export folder, not just report the path in a banner"
        )
    finally:
        tab.deleteLater()


# ── Phase 2 import block ───────────────────────────────────────────────


def test_phase2_imports_disabled_after_takeover(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    state = AppState()
    tab = Phase2Tab(state)
    try:
        assert tab.btn_import.isEnabled()

        state.generation_log.workflow("stalni").start_nacelnik_takeover()
        state.generation_log_changed.emit()

        assert not tab.btn_import.isEnabled()
        assert not tab.btn_import_outlook.isEnabled()
    finally:
        tab.deleteLater()


def test_phase2_imports_reenabled_after_revert(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    state = AppState()
    wl = state.generation_log.workflow("stalni")
    wl.start_nacelnik_takeover()
    tab = Phase2Tab(state)
    try:
        assert not tab.btn_import.isEnabled()
        wl.revert_nacelnik_takeover()
        state.generation_log_changed.emit()
        assert tab.btn_import.isEnabled()
    finally:
        tab.deleteLater()
