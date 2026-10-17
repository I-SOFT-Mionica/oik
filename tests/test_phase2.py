"""Tests for core.phase2_aggregate."""

from __future__ import annotations

from pathlib import Path

import openpyxl

from biracki_odbor.core.phase1_generate import generate_party_files
from biracki_odbor.core.phase2_aggregate import aggregate_party_files
from biracki_odbor.validation.reports import Codes
from tests.fixtures.stalni_sastav import build_template
from tests.test_jmbg import VALID_SAMPLES
from tests.test_phase1 import _make_oik


def _fill_party_file(file_path: Path, *, member_count: int, jmbgs: list[str]) -> None:
    """Open a generated party workbook and fill in member data for testing.

    Bypasses sheet protection by writing directly to cells via openpyxl
    (the password lock applies to Excel users, not to openpyxl).
    """
    wb = openpyxl.load_workbook(file_path)
    ws = wb.active
    for i in range(member_count):
        row = i + 4
        # Schema post-split: E=Име, F=Презиме, G=ЈМБГ, H=Место, I=Адреса, J=Тел, K=Е-пошта
        ws.cell(row=row, column=5, value=f"Особа{i + 1}")
        ws.cell(row=row, column=6, value=f"Презименић{i + 1}")
        ws.cell(row=row, column=7, value=jmbgs[i % len(jmbgs)])
        ws.cell(row=row, column=8, value="Уб")
        ws.cell(row=row, column=9, value=f"Адреса {i + 1}")
        ws.cell(row=row, column=10, value="0641234567")
        ws.cell(row=row, column=11, value=f"osoba{i + 1}@example.com")
    wb.save(file_path)
    wb.close()


def test_cache_allowlist_skips_files_not_imported(tmp_path: Path, monkeypatch) -> None:
    """Files dropped into popunjeni/ without going through `popunjeni_io.import_file`
    surface as UNIMPORTED_FILE warnings and are NOT aggregated."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    election = ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date="6. децембра 2026. године",
                session_number="5",
            ),
            types=["parliamentary"],
            rik_decision="X",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="Y"),
        party_full_names={"СНС": "A"},
        election_uuid="cache-test-uuid",
    )
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=2,
                              parties=("СНС",))
    oik = _make_oik(2)
    p1 = generate_party_files(template, tmp_path / "stranke", oik, election=election)
    # Drop file into popunjeni/ WITHOUT importing — simulates user dragging
    # an .xlsx into the folder via Explorer.
    popunjeni = tmp_path / "popunjeni"
    popunjeni.mkdir()
    for f in p1.files_written:
        _fill_party_file(f, member_count=6, jmbgs=VALID_SAMPLES)
        f.rename(popunjeni / f.name)

    master = tmp_path / "master" / "zbirana.xlsx"
    result = aggregate_party_files(popunjeni, template, master, oik, election=election)
    codes = {i.code for i in result.report.issues}
    assert Codes.UNIMPORTED_FILE in codes
    # No persons aggregated because the only file present wasn't in cache.
    filled = [p for p in result.persons if p.is_filled]
    assert filled == []


def test_cache_hit_path_reuses_records(tmp_path: Path, monkeypatch) -> None:
    """Once a file is imported, a second Phase 2 run with no changes uses
    the cache and doesn't re-parse the .xlsx."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.core import popunjeni_io, popunjeni_cache
    election = ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date="6. децембра 2026. године",
                session_number="5",
            ),
            types=["parliamentary"],
            rik_decision="X",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="Y"),
        party_full_names={"СНС": "A"},
        election_uuid="hit-test-uuid",
    )
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=2,
                              parties=("СНС",))
    oik = _make_oik(2)
    p1 = generate_party_files(template, tmp_path / "stranke", oik, election=election)
    src = p1.files_written[0]
    _fill_party_file(src, member_count=6, jmbgs=VALID_SAMPLES)

    popunjeni = tmp_path / "popunjeni"
    outcome = popunjeni_io.import_file(src, election, popunjeni)
    assert outcome.ok

    # Populate cache via the GUI-equivalent path (mirrors what phase2.py does
    # after import_file returns).
    cache_data = popunjeni_cache.load(election_uuid=election.election_uuid)
    records, issues = popunjeni_io.parse_for_cache(outcome.canonical_path)
    cache_data.entries[str(outcome.canonical_path)] = (
        popunjeni_cache.CacheEntry.from_parsed(
            outcome.canonical_path, records, issues,
        )
    )
    popunjeni_cache.save(cache_data)

    # First Phase 2 run — should aggregate the cached file.
    master = tmp_path / "master" / "zbirana.xlsx"
    r1 = aggregate_party_files(popunjeni, template, master, oik, election=election)
    filled = [p for p in r1.persons if p.is_filled]
    assert filled, "Expected at least one filled person after Phase 2"

    # Now spy on parse_party_file — second run must NOT call it.
    calls = {"n": 0}
    real_parse = popunjeni_io.parse_party_file

    def spy(*a, **kw):
        calls["n"] += 1
        return real_parse(*a, **kw)

    monkeypatch.setattr(popunjeni_io, "parse_party_file", spy)
    r2 = aggregate_party_files(popunjeni, template, master, oik, election=election)
    assert calls["n"] == 0, "Cache-hit run must not invoke parse_party_file"
    # Records identical (filled persons same length).
    assert len([p for p in r2.persons if p.is_filled]) == len(filled)


def test_round_trip_phase1_then_phase2(tmp_path: Path) -> None:
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=2,
                              parties=("СНС", "СПС"))
    oik = _make_oik(2)
    # Phase 1
    p1 = generate_party_files(template, tmp_path / "stranke", oik)
    assert p1.report.ok

    # Fill in each party file with valid members
    for f in p1.files_written:
        wb = openpyxl.load_workbook(f)
        ws = wb.active
        # v0.4.2 moved the summary block from below the data to the top of
        # the sheet (rows 1-2). ws.max_row is now the LAST data row
        # directly — no `- 2` offset for a trailing summary.
        max_data_row = ws.max_row
        wb.close()
        _fill_party_file(f, member_count=max_data_row - 3, jmbgs=VALID_SAMPLES)

    # Move filled files into a popunjeni dir to simulate user returns
    popunjeni = tmp_path / "popunjeni"
    popunjeni.mkdir()
    for f in p1.files_written:
        f.rename(popunjeni / f.name)

    # Phase 2
    master = tmp_path / "master" / "zbirana.xlsx"
    p2 = aggregate_party_files(popunjeni, template, master, oik)
    # We expect duplicate-JMBG warnings (we cycled through 5 JMBGs across 12 slots)
    # but no fatal errors.
    assert master.exists()
    assert p2.files_processed == 2
    # All slots populated
    assert all(p.is_filled for p in p2.persons)


def test_bad_jmbg_reported(tmp_path: Path) -> None:
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=1,
                              parties=("СНС",))
    oik = _make_oik(1)
    p1 = generate_party_files(template, tmp_path / "stranke", oik)
    # Fill with invalid JMBGs
    f = p1.files_written[0]
    _fill_party_file(f, member_count=6, jmbgs=["1234567890123"])
    popunjeni = tmp_path / "popunjeni"
    popunjeni.mkdir()
    f.rename(popunjeni / f.name)

    p2 = aggregate_party_files(popunjeni, template, tmp_path / "master.xlsx", oik)
    codes = {i.code for i in p2.report.issues}
    assert Codes.JMBG_BAD_CHECKSUM in codes


def test_duplicate_jmbg_across_parties(tmp_path: Path) -> None:
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=2,
                              parties=("СНС", "СПС"))
    oik = _make_oik(2)
    p1 = generate_party_files(template, tmp_path / "stranke", oik)

    # Fill BOTH party files with the same JMBG → cross-party conflict
    same_jmbg = VALID_SAMPLES[0]
    for f in p1.files_written:
        _fill_party_file(f, member_count=2, jmbgs=[same_jmbg])

    popunjeni = tmp_path / "popunjeni"
    popunjeni.mkdir()
    for f in p1.files_written:
        f.rename(popunjeni / f.name)

    p2 = aggregate_party_files(popunjeni, template, tmp_path / "master.xlsx", oik)
    codes = {i.code for i in p2.report.issues}
    assert Codes.JMBG_DUPLICATE in codes


def test_empty_input_dir(tmp_path: Path) -> None:
    template = build_template(tmp_path / "t.xlsx", n_polling_stations=1,
                              parties=("СНС",))
    popunjeni = tmp_path / "empty"
    popunjeni.mkdir()
    p2 = aggregate_party_files(popunjeni, template, tmp_path / "m.xlsx", _make_oik())
    assert p2.files_processed == 0
    # All slots show as unfilled
    assert not any(p.is_filled for p in p2.persons)


def test_multiple_submissions_picks_latest_by_received_time(
    tmp_path: Path, monkeypatch,
) -> None:
    """The director's "use the latest by ReceivedTime" requirement.

    Two cache entries for the same party with different
    received_time_iso → aggregate uses only the latest. Both files
    stay on disk (audit trail) and a MULTIPLE_SUBMISSIONS info-level
    issue surfaces in the report listing what got superseded.
    """
    from biracki_odbor.core import popunjeni_cache, popunjeni_io
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    election = ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"], rik_decision="X",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="Y"),
        party_full_names={"СНС": "A"},
        election_uuid="multi-test-uuid",
    )
    template = build_template(
        tmp_path / "t.xlsx", n_polling_stations=1, parties=("СНС",),
    )
    oik = _make_oik(1)
    p1 = generate_party_files(template, tmp_path / "stranke", oik, election=election)
    src = p1.files_written[0]
    _fill_party_file(src, member_count=6, jmbgs=VALID_SAMPLES)

    popunjeni = tmp_path / "popunjeni"

    # Import the same source file twice with distinct received_at —
    # the timestamped filename ensures two separate canonical files.
    from datetime import datetime, timezone
    t_old = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
    t_new = datetime(2026, 5, 15, 11, 30, 0, tzinfo=timezone.utc)

    o_old = popunjeni_io.import_file(src, election, popunjeni, received_at=t_old)
    o_new = popunjeni_io.import_file(src, election, popunjeni, received_at=t_new)
    assert o_old.ok and o_new.ok
    assert o_old.canonical_path != o_new.canonical_path
    assert o_old.canonical_path.exists() and o_new.canonical_path.exists()

    # Build the cache the same way Phase 2 GUI does.
    cache_data = popunjeni_cache.load(election_uuid=election.election_uuid)
    for outcome in (o_old, o_new):
        records, issues = popunjeni_io.parse_for_cache(outcome.canonical_path)
        cache_data.entries[str(outcome.canonical_path)] = (
            popunjeni_cache.CacheEntry.from_parsed(
                outcome.canonical_path, records, issues,
                received_time_iso=outcome.received_time_iso,
                import_source=outcome.import_source,
                party=outcome.party,
                imported_by="test-operator",
            )
        )
    popunjeni_cache.save(cache_data)

    master = tmp_path / "master.xlsx"
    result = aggregate_party_files(
        popunjeni, template, master, oik, election=election,
    )
    # files_processed counts the CHOSEN files only — one per party.
    assert result.files_processed == 1, (
        "Multi-version dedupe failed: expected 1 chosen file for the"
        f" single party СНС, got {result.files_processed}"
    )
    # The info-level note must call out the superseded version by name.
    codes = {i.code for i in result.report.issues}
    assert Codes.MULTIPLE_SUBMISSIONS in codes
    info = [i for i in result.report.issues if i.code == Codes.MULTIPLE_SUBMISSIONS][0]
    assert o_old.canonical_path.name in info.message_sr
    # And the master used the newer file's records.
    assert o_new.canonical_path.exists()
    assert o_old.canonical_path.exists(), (
        "Older submission must remain on disk for the audit trail."
    )
