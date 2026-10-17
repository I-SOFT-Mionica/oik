"""Tests for §22 — "Compose reply email" + "Export errors" in Phase 2.

Lives right under the error table there (not in Корекције → Сви чланови)
since that's where party files are imported and checked — the
"return to sender" loop belongs at the point of detection.

Covers: grouping flagged persons by party, resolving each party's email
(party_contacts) and originally-submitted file (popunjeni_cache), one
draft per party with the error list in the body, the reply_email_sent
audit event, and the errors-only Excel export.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_state(tmp_path):
    from biracki_odbor.config.election import PartyContact
    from biracki_odbor.gui.app_state import AppState

    state = AppState()
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    state.election.election_uuid = "election-uuid-1"
    state.election.party_full_names = {"СНС": "Странка А", "СПС": "Странка Б"}
    state.election.party_contacts = {
        "СНС": PartyContact(email="sns@example.rs"),
        # СПС deliberately has no contact — exercises the skip path.
    }
    return state


def _seed_submission(tmp_path, election_uuid: str, party: str, filename: str) -> Path:
    from biracki_odbor.core import popunjeni_cache

    file = tmp_path / filename
    file.write_bytes(b"dummy xlsx")
    entry = popunjeni_cache.CacheEntry(
        mtime_ns=file.stat().st_mtime_ns, size=file.stat().st_size,
        party=party, received_time_iso="2026-07-10T09:00:00Z",
    )
    data = popunjeni_cache.load(election_uuid=election_uuid)
    data.election_uuid = election_uuid
    data.entries[str(file)] = entry
    popunjeni_cache.save(data)
    return file


def _report_with_errors(persons):
    from biracki_odbor.core.models import Issue, ValidationReport

    report = ValidationReport()
    for p in persons:
        report.add(Issue(
            code="JMBG_BAD_CHECKSUM",
            message_sr=f"ЈМБГ '{p.jmbg}' не пролази MOD 11 проверу.",
            severity="error",
            detail=p.jmbg,
        ))
    return report


def _result_with_errors(persons, report):
    from pathlib import Path as _Path
    from biracki_odbor.core.phase2_aggregate import Phase2Result
    return Phase2Result(
        persons=persons, master_path=_Path("unused.xlsx"),
        report=report, files_processed=len(persons),
    )


def test_reply_email_drafts_one_per_party_with_attachment_and_body(app, tmp_path) -> None:
    from biracki_odbor.core.corrections import read_log
    from biracki_odbor.core.models import Person
    from biracki_odbor import app_paths
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab
    import biracki_odbor.integrations.email_client as ec_mod

    state = _make_state(tmp_path)
    sns_file = _seed_submission(tmp_path, state.election.election_uuid, "СНС", "sns.xlsx")

    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="1605991774818"),
        Person(bm_number=2, function="Члан 1", party="СПС",
               first_name="Пера", last_name="Перић", jmbg="2706994779807"),
    ]
    report = _report_with_errors(persons)
    result = _result_with_errors(persons, report)

    tab = Phase2Tab(state)
    try:
        tab._on_finished(result)  # noqa: SLF001

        assert tab.btn_reply_email.isEnabled()

        captured_drafts = []

        def _fake_create_drafts(drafts, **kw):
            from biracki_odbor.integrations.email_client import DraftResult
            captured_drafts.extend(drafts)
            return [DraftResult(spec=d, ok=True) for d in drafts]

        import unittest.mock as mock
        with mock.patch.object(ec_mod, "any_available", return_value=True), \
             mock.patch.object(ec_mod, "create_drafts", side_effect=_fake_create_drafts):
            tab._on_compose_reply_email()  # noqa: SLF001

        # Only СНС has both an email and a submitted file — СПС is skipped.
        assert len(captured_drafts) == 1
        draft = captured_drafts[0]
        assert draft.to == "sns@example.rs"
        assert draft.attachment == sns_file
        assert "1605991774818" in draft.body
        assert "MOD 11" in draft.body

        events = read_log(app_paths.corrections_log_path())
        reply_events = [e for e in events if e["event_type"] == "reply_email_sent"]
        assert len(reply_events) == 1
        assert "СНС" in reply_events[0]["note"]
    finally:
        tab.deleteLater()


def test_reply_email_skips_party_without_contact_or_file(app, tmp_path) -> None:
    """Sanity on the skip paths themselves — already exercised above,
    pinned separately so a future change can't silently start drafting
    for parties with no email/file without a test noticing."""
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab
    import biracki_odbor.integrations.email_client as ec_mod

    state = _make_state(tmp_path)
    # No submission seeded for either party this time.
    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="1605991774818"),
    ]
    report = _report_with_errors(persons)
    result = _result_with_errors(persons, report)

    tab = Phase2Tab(state)
    try:
        tab._on_finished(result)  # noqa: SLF001

        import unittest.mock as mock
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(ec_mod, "any_available", return_value=True), \
             mock.patch.object(ec_mod, "create_drafts") as mock_create, \
             mock.patch.object(QMessageBox, "warning") as mock_warning:
            tab._on_compose_reply_email()  # noqa: SLF001
            mock_create.assert_not_called()
            # No party ends up with both an email and a file on record
            # here (no submission seeded) — the "No drafts created"
            # QMessageBox must be the (stubbed) one firing, not a real
            # modal blocking the test run.
            mock_warning.assert_called_once()
    finally:
        tab.deleteLater()


def test_export_errors_writes_only_flagged_rows(app, tmp_path, monkeypatch) -> None:
    from biracki_odbor.core.master_io import _read_legacy_xlsx_master
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab
    from PySide6.QtWidgets import QFileDialog

    state = _make_state(tmp_path)
    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="1605991774818"),
        Person(bm_number=2, function="Члан 1", party="СПС",
               first_name="Пера", last_name="Перић", jmbg="2706994779807"),
    ]
    # Only the first person has an error.
    report = _report_with_errors(persons[:1])
    result = _result_with_errors(persons, report)

    out_path = tmp_path / "errors_export.xlsx"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **kw: (str(out_path), ""),
    )

    tab = Phase2Tab(state)
    try:
        tab._on_finished(result)  # noqa: SLF001

        assert tab.btn_export_errors.isEnabled()
        tab._on_export_errors()  # noqa: SLF001

        exported = _read_legacy_xlsx_master(out_path)
        assert len(exported) == 1
        assert exported[0].jmbg == "1605991774818"
    finally:
        tab.deleteLater()


def test_reply_email_and_export_buttons_disabled_without_errors(app, tmp_path) -> None:
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    state = _make_state(tmp_path)
    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="1605991774818"),
    ]
    from biracki_odbor.core.models import ValidationReport
    result = _result_with_errors(persons, ValidationReport())

    tab = Phase2Tab(state)
    try:
        assert not tab.btn_reply_email.isEnabled()
        assert not tab.btn_export_errors.isEnabled()

        tab._on_finished(result)  # noqa: SLF001

        assert not tab.btn_reply_email.isEnabled()
        assert not tab.btn_export_errors.isEnabled()
    finally:
        tab.deleteLater()
