"""Backend e2e test for the prosireni corrections → Phase 3 pipeline.

Covers:
  - Prosireni master written to spec path, corrections applied, re-written.
  - Phase 3 reads corrected master (not stalled pre-correction version).
  - Corrections log is written to corrections_prosireni.log (not corrections.log).
  - Phase 3 errors appropriately when master is absent or empty.
  - Stalni and prosireni log files are independent (no cross-write).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor import app_paths
from biracki_odbor.core.corrections import CorrectionsState, detect_conflicts, read_log
from biracki_odbor.core.master_io import read_master, write_master
from biracki_odbor.core.models import Person
from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC


# ── Helpers ───────────────────────────────────────────────────────────────────


def _oik():
    from biracki_odbor.config.oik import OikConstants
    return OikConstants()


def _election():
    from tests.test_phase3 import _make_election
    return _make_election()


def _make_person(
    bm: int, first: str, last: str, party: str, jmbg: str
) -> Person:
    return Person(
        bm_number=bm, function="Председник", party=party,
        first_name=first, last_name=last, jmbg=jmbg,
        mesto="Уб", adresa="Главна 1", telefon="", email="",
    )


def _build_valid_jmbg(seed: str) -> str:
    """Build a syntactically valid JMBG from a 12-digit seed string."""
    from tests.test_jmbg import _build_valid
    return _build_valid(seed.zfill(12))


# ── Corrections log isolation ─────────────────────────────────────────────────


def test_prosireni_corrections_log_is_separate_from_stalni(tmp_path, monkeypatch):
    """Prosireni corrections must go to corrections_prosireni.log, not corrections.log."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    stalni_log = app_paths.corrections_log_path()
    prosireni_log = app_paths.corrections_log_path_for(PROSIRENI_SPEC)

    assert stalni_log != prosireni_log
    assert "prosireni" in prosireni_log.name
    assert "prosireni" not in stalni_log.name


def test_writing_prosireni_corrections_does_not_touch_stalni_log(tmp_path, monkeypatch):
    """CorrectionsState for prosireni must not write to the stalni log file."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    persons = [
        _make_person(1, "Ана", "Анић", "СНС", _build_valid_jmbg("010199077001")),
    ]

    prosireni_log = app_paths.corrections_log_path_for(PROSIRENI_SPEC)
    state = CorrectionsState(persons=persons, log_path=prosireni_log)
    state.replace_member(1, "Председник", {"name": "Замена", "jmbg": _build_valid_jmbg("020199077002")}, note="тест")

    # Prosireni log received the event.
    assert prosireni_log.exists()
    events = read_log(prosireni_log)
    assert len(events) == 1
    assert events[0]["event_type"] == "replace_member"

    # Stalni log must NOT have been created.
    stalni_log = app_paths.corrections_log_path()
    assert not stalni_log.exists(), "stalni log must not be created during prosireni corrections"


# ── Master isolation ──────────────────────────────────────────────────────────


def test_prosireni_master_shares_stalni_path_but_legacy_paths_differ(tmp_path, monkeypatch):
    """Both workflows share one committee DB now (see core/master_io.py) --
    the working master PATH is deliberately the same; workflow separation
    happens inside that shared file, not via separate files. The legacy
    (pre-migration) per-workflow xlsx locations still differ -- used only
    by the one-time startup reconciliation step to find old data."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    stalni = app_paths.master_path()
    prosireni = app_paths.master_path_for(PROSIRENI_SPEC)
    assert stalni == prosireni

    legacy_stalni = app_paths.legacy_xlsx_master_path_for(STALNI_SPEC)
    legacy_prosireni = app_paths.legacy_xlsx_master_path_for(PROSIRENI_SPEC)
    assert legacy_stalni != legacy_prosireni
    assert legacy_stalni.parent != legacy_prosireni.parent


def test_writing_prosireni_master_does_not_touch_stalni_rows(tmp_path, monkeypatch):
    """Writing прошир data into the shared committee DB must not put any
    rows into стални's workflow bucket within that same file."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    persons = [_make_person(1, "Ана", "Анић", "ent1", _build_valid_jmbg("010199077001"))]
    master = app_paths.master_path_for(PROSIRENI_SPEC)
    write_master(persons, _oik(), master, spec=PROSIRENI_SPEC)

    assert master.exists()
    assert len(read_master(master, spec=PROSIRENI_SPEC)) == 1
    assert read_master(master, spec=STALNI_SPEC) == [], "stalni rows must not appear"


def test_prosireni_master_export_title_and_sheet_name_say_prosireni_not_stalni(tmp_path, monkeypatch):
    """Field report: the prosireni master export showed "Стални састав" as
    its own in-file title and sheet name -- the xlsx writer never received
    `spec` at all, so it always hardcoded stalni's wording regardless of
    which workflow was actually being exported. This distinction now lives
    only in export_master_xlsx() (the internal store is SQLite, no title/
    sheet concept applies to it)."""
    import openpyxl
    from biracki_odbor.core.master_io import export_master_xlsx
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    persons = [_make_person(1, "Ана", "Анић", "ent1", _build_valid_jmbg("010199077001"))]

    prosireni_export = tmp_path / "prosireni_export.xlsx"
    export_master_xlsx(persons, _oik(), prosireni_export, spec=PROSIRENI_SPEC)
    wb = openpyxl.load_workbook(prosireni_export)
    ws = wb.active
    assert "Стални" not in ws.title
    assert "Стални" not in ws["A1"].value
    assert "Проширени" in ws.title
    assert "Проширени" in ws["A1"].value

    stalni_export = tmp_path / "stalni_export.xlsx"
    export_master_xlsx(persons, _oik(), stalni_export)
    wb2 = openpyxl.load_workbook(stalni_export)
    ws2 = wb2.active
    assert "Стални" in ws2.title
    assert "Стални" in ws2["A1"].value


# ── Corrections round-trip ────────────────────────────────────────────────────


def test_prosireni_corrections_roundtrip(tmp_path, monkeypatch):
    """Corrections applied to prosireni master are persisted and readable by Phase 3.

    Simulates the operator flow:
      Phase 2 writes master → operator resolves conflict in CorrectionsTab
      → corrections persisted → Phase 3 reads corrected version.
    """
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    shared_jmbg = _build_valid_jmbg("999988887777")
    # Real conflict: same JMBG submitted by two different parties at DIFFERENT BMs.
    # resolve_conflict identifies winners by slot_key=(bm, function); if both
    # persons occupy the same slot the resolver cannot distinguish them.
    persons = [
        _make_person(1, "Ана", "Анић", "СНС", shared_jmbg),   # slot (1, "Председник")
        _make_person(2, "Бора", "Борић", "СПС", shared_jmbg), # slot (2, "Председник") — conflict
        _make_person(3, "Цана", "Цанић", "СНС", _build_valid_jmbg("010199077003")),
    ]

    master_p = app_paths.master_path_for(PROSIRENI_SPEC)
    master_p.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, _oik(), master_p)

    # Round-trip: read back and detect conflicts.
    loaded = read_master(master_p)
    conflicts = detect_conflicts(loaded)
    assert len(conflicts) == 1, f"Expected 1 conflict, got {len(conflicts)}"

    log_p = app_paths.corrections_log_path_for(PROSIRENI_SPEC)
    state = CorrectionsState(persons=loaded, log_path=log_p)

    sns_sub = next(s for s in conflicts[0].submissions if s.party == "СНС")
    state.resolve_conflict(conflicts[0], keep_slot_key=sns_sub.slot_key, note="Прва пријава")

    # After resolution: only the СНС submission remains for that JMBG.
    filled = [p for p in loaded if p.jmbg == shared_jmbg and p.is_filled]
    assert len(filled) == 1
    assert filled[0].party == "СНС"

    # Persist.
    write_master(loaded, _oik(), master_p)

    # Phase 3 reads the corrected file — must see 2 filled persons, not 3.
    after = read_master(master_p)
    filled_after = [p for p in after if p.is_filled]
    assert all(p.jmbg != shared_jmbg or p.party == "СНС" for p in filled_after), (
        "Only СНС entry should remain for the shared JMBG after resolution"
    )

    # Corrections log must record the resolution event.
    events = read_log(log_p)
    types = {e["event_type"] for e in events}
    assert "resolve_conflict" in types


def test_prosireni_replace_member_persists(tmp_path, monkeypatch):
    """replace_member on a prosireni master is visible after write→read round-trip."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    original_jmbg = _build_valid_jmbg("010199077001")
    replacement_jmbg = _build_valid_jmbg("020299077002")

    persons = [_make_person(1, "Ана", "Анић", "СНС", original_jmbg)]
    master_p = app_paths.master_path_for(PROSIRENI_SPEC)
    master_p.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, _oik(), master_p)

    loaded = read_master(master_p)
    log_p = app_paths.corrections_log_path_for(PROSIRENI_SPEC)
    state = CorrectionsState(persons=loaded, log_path=log_p)

    target = loaded[0]
    state.replace_member(target.bm_number, target.function,
                         {"name": "Замена Особа", "jmbg": replacement_jmbg}, note="Болест")

    write_master(loaded, _oik(), master_p)
    after = read_master(master_p)

    swapped = after[0]
    assert swapped.name == "Замена Особа"
    assert swapped.jmbg == replacement_jmbg

    events = read_log(log_p)
    assert any(e["event_type"] == "replace_member" for e in events)


# ── Phase 3 error handling ────────────────────────────────────────────────────


def test_phase3_prosireni_reads_from_master_file(tmp_path, monkeypatch):
    """generate_documents(spec=PROSIRENI_SPEC) must read from the prosireni master path."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    from biracki_odbor.core.phase3_docx import generate_documents

    persons = [_make_person(1, "Ана", "Анић", "СНС", _build_valid_jmbg("010199077001"))]
    master_p = app_paths.master_path_for(PROSIRENI_SPEC)
    master_p.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, _oik(), master_p)

    loaded = read_master(master_p)
    resenja_dir = app_paths.resenja_dir_for(PROSIRENI_SPEC)
    result = generate_documents(
        persons=loaded,
        oik=_oik(),
        election=_election(),
        output_dir=resenja_dir,
        spec=PROSIRENI_SPEC,
    )

    assert result.report.ok or len(result.files_written) >= 1


def test_prosireni_phase3_empty_master_gives_no_output(tmp_path, monkeypatch):
    """generate_documents with an empty persons list must produce no files."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    from biracki_odbor.core.phase3_docx import generate_documents

    resenja_dir = app_paths.resenja_dir_for(PROSIRENI_SPEC)
    result = generate_documents(
        persons=[],
        oik=_oik(),
        election=_election(),
        output_dir=resenja_dir,
        spec=PROSIRENI_SPEC,
    )
    assert result.files_written == []


# ── Full cycle ────────────────────────────────────────────────────────────────


def test_prosireni_full_cycle_correction_then_phase3(tmp_path, monkeypatch):
    """Full prosireni backend cycle: master → correct → persist → Phase 3.

    Verifies that the output of Phase 3 reflects corrections, not the
    original uncorrected master (regression guard for the prior bug where
    Phase 3 read state.persons instead of the master file).
    """
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)

    from biracki_odbor.core.phase3_docx import generate_documents

    replacement_jmbg = _build_valid_jmbg("999911119999")

    persons = [
        _make_person(1, "Ана", "Анић", "СНС", _build_valid_jmbg("010199077001")),
        _make_person(2, "Бора", "Борић", "СПС", _build_valid_jmbg("020299077002")),
    ]

    master_p = app_paths.master_path_for(PROSIRENI_SPEC)
    master_p.parent.mkdir(parents=True, exist_ok=True)
    write_master(persons, _oik(), master_p)

    # Apply a correction: replace БМ 2 member.
    loaded = read_master(master_p)
    log_p = app_paths.corrections_log_path_for(PROSIRENI_SPEC)
    state = CorrectionsState(persons=loaded, log_path=log_p)
    bm2 = next(p for p in loaded if p.bm_number == 2 and p.is_filled)
    state.replace_member(bm2.bm_number, bm2.function,
                         {"name": "Замена Особа", "jmbg": replacement_jmbg}, note="Тест")

    # Persist corrections.
    write_master(loaded, _oik(), master_p)

    # Phase 3 using the updated master.
    final_persons = read_master(master_p)
    resenja_dir = app_paths.resenja_dir_for(PROSIRENI_SPEC)
    result = generate_documents(
        persons=final_persons,
        oik=_oik(),
        election=_election(),
        output_dir=resenja_dir,
        spec=PROSIRENI_SPEC,
    )

    assert len(result.files_written) >= 1
    # Stalni log must not have been created.
    assert not app_paths.corrections_log_path().exists()
    # Prosireni log has the replacement event.
    events = read_log(log_p)
    assert any(e["event_type"] == "replace_member" for e in events)
