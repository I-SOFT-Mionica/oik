"""Tests for biracki_odbor.core.master_io — the shared SQLite committee store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from biracki_odbor.core import master_io
from biracki_odbor.core.models import Person
from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
from tests.test_phase1 import _make_oik


def _make_persons(jmbg_start: int = 101990710001) -> list[Person]:
    persons = []
    jmbg = jmbg_start
    for bm in (1, 2, 3):
        for func in ("Председник", "Заменик председника", "Члан 1"):
            persons.append(Person(
                bm_number=bm, function=func, party="СНС",
                first_name=f"Особа{bm}", last_name=func[:5],
                jmbg=f"0{jmbg}",
                mesto="Уб", adresa="X 1", telefon="0641234567",
            ))
            jmbg += 1
    return persons


def test_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "master" / "committee.db"
    persons = _make_persons()
    master_io.write_master(persons, _make_oik(3), out)
    loaded = master_io.read_master(out)
    assert len(loaded) == len(persons)
    assert loaded[0].bm_number == persons[0].bm_number
    assert loaded[0].function == persons[0].function


def test_read_master_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    assert master_io.read_master(tmp_path / "nope.db") == []


def test_write_master_replaces_only_this_workflow(tmp_path: Path) -> None:
    out = tmp_path / "committee.db"
    master_io.write_master(_make_persons(), _make_oik(3), out)
    # Rewriting with fewer rows must not leave stale rows behind.
    master_io.write_master(_make_persons()[:3], _make_oik(3), out)
    reread = master_io.read_master(out)
    assert len(reread) == 3


def test_stalni_and_prosireni_coexist_in_one_file(tmp_path: Path) -> None:
    out = tmp_path / "committee.db"
    master_io.write_master(_make_persons(jmbg_start=101990710001), _make_oik(3), out, spec=STALNI_SPEC)
    master_io.write_master(_make_persons(jmbg_start=201990710001), _make_oik(3), out, spec=PROSIRENI_SPEC)

    stalni = master_io.read_master(out, spec=STALNI_SPEC)
    prosireni = master_io.read_master(out, spec=PROSIRENI_SPEC)
    assert len(stalni) == 9
    assert len(prosireni) == 9
    assert {p.jmbg for p in stalni}.isdisjoint({p.jmbg for p in prosireni})

    # Rewriting one workflow must not touch the other's rows.
    master_io.write_master(_make_persons(jmbg_start=101990710001)[:2], _make_oik(3), out, spec=STALNI_SPEC)
    assert len(master_io.read_master(out, spec=STALNI_SPEC)) == 2
    assert len(master_io.read_master(out, spec=PROSIRENI_SPEC)) == 9


def test_cross_workflow_jmbg_collision_is_allowed_at_db_level(tmp_path: Path) -> None:
    """Schema v2: the hard DB-level block is gone (see master_io's module
    docstring) -- a cross-workflow JMBG collision is never rejected or
    mutated here. It's soft-flagged at Phase 2 import time (core.
    row_checks.find_cross_workflow_duplicate_jmbgs) and actually BLOCKED
    at Phase 3 (validation.preflight.preflight_phase3) instead. The old
    hard trigger's only "recovery" from its own abort was blanking the
    colliding JMBG -- which hid the problem from every downstream
    duplicate check instead of surfacing it (field report)."""
    out = tmp_path / "committee.db"
    shared_jmbg = "0101990710099"
    stalni_persons = [Person(
        bm_number=1, function="Председник", party="СНС",
        first_name="Ана", last_name="Анић", jmbg=shared_jmbg,
    )]
    master_io.write_master(stalni_persons, _make_oik(1), out, spec=STALNI_SPEC)

    prosireni_persons = [Person(
        bm_number=1, function="Члан [1]", party="ent1",
        first_name="Ана", last_name="Анић", jmbg=shared_jmbg,
    )]
    master_io.write_master(prosireni_persons, _make_oik(1), out, spec=PROSIRENI_SPEC)

    # Both copies keep their REAL jmbg -- neither gets silently blanked.
    assert master_io.read_master(out, spec=STALNI_SPEC)[0].jmbg == shared_jmbg
    assert master_io.read_master(out, spec=PROSIRENI_SPEC)[0].jmbg == shared_jmbg


def test_schema_migration_drops_cross_workflow_trigger_from_old_db(tmp_path: Path) -> None:
    """A committee.db created by a pre-v2 install already has the hard
    trigger baked in -- `_connect()`'s version gate must actually DROP it
    on that file, not just skip creating it on a fresh one."""
    out = tmp_path / "committee.db"
    conn = sqlite3.connect(str(out))
    conn.execute(
        """
        CREATE TABLE persons (
            workflow TEXT NOT NULL CHECK (workflow IN ('stalni', 'prosireni')),
            bm_number INTEGER NOT NULL, function TEXT NOT NULL,
            party TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', jmbg TEXT NOT NULL DEFAULT '',
            mesto TEXT NOT NULL DEFAULT '', adresa TEXT NOT NULL DEFAULT '',
            telefon TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            appointed_by_nacelnik INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (workflow, bm_number, function)
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_persons_cross_workflow_jmbg
        BEFORE INSERT ON persons
        WHEN NEW.jmbg != '' AND (trim(NEW.first_name) != '' OR trim(NEW.last_name) != '')
        BEGIN
            SELECT RAISE(ABORT, 'cross-workflow JMBG collision')
            WHERE EXISTS (
                SELECT 1 FROM persons
                WHERE jmbg = NEW.jmbg AND workflow != NEW.workflow
                  AND (trim(first_name) != '' OR trim(last_name) != '')
            );
        END
        """
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    # Any call through master_io (read or write) runs _connect(), which
    # must migrate this file in place.
    master_io.read_master(out)

    conn = sqlite3.connect(str(out))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
            " AND name='trg_persons_cross_workflow_jmbg'"
        ).fetchone()
        assert row is None, "migration must DROP the old trigger, not just skip creating it"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == master_io._SCHEMA_VERSION  # noqa: SLF001
    finally:
        conn.close()


def _build_v1_db_with_data(out: Path) -> None:
    """A schema-v1 committee.db with one real row, built with raw sqlite3
    (not master_io, which only knows how to produce v2 schemas now) --
    matching exactly what an install running the OLD code would have on
    disk, trigger and all."""
    conn = sqlite3.connect(str(out))
    conn.execute(
        """
        CREATE TABLE persons (
            workflow TEXT NOT NULL CHECK (workflow IN ('stalni', 'prosireni')),
            bm_number INTEGER NOT NULL, function TEXT NOT NULL,
            party TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', jmbg TEXT NOT NULL DEFAULT '',
            mesto TEXT NOT NULL DEFAULT '', adresa TEXT NOT NULL DEFAULT '',
            telefon TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            appointed_by_nacelnik INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (workflow, bm_number, function)
        )
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_persons_cross_workflow_jmbg
        BEFORE INSERT ON persons
        WHEN NEW.jmbg != '' AND (trim(NEW.first_name) != '' OR trim(NEW.last_name) != '')
        BEGIN
            SELECT RAISE(ABORT, 'cross-workflow JMBG collision')
            WHERE EXISTS (
                SELECT 1 FROM persons
                WHERE jmbg = NEW.jmbg AND workflow != NEW.workflow
                  AND (trim(first_name) != '' OR trim(last_name) != '')
            );
        END
        """
    )
    conn.execute(
        "INSERT INTO persons (workflow, bm_number, function, party,"
        " first_name, last_name, jmbg, mesto, adresa, telefon, email,"
        " appointed_by_nacelnik) VALUES ('stalni', 1, 'Председник', 'СНС',"
        " 'Ана', 'Анић', '1605991774818', '', '', '', '', 0)"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_schema_migration_does_not_break_an_existing_verified_fingerprint(tmp_path: Path) -> None:
    """Field report: a real, previously-used committee.db (schema v1,
    already verified from normal use) failed its integrity check on the
    very first launch after upgrading -- the v1->v2 migration's own DDL
    (DROP TRIGGER) changed the file's bytes without re-stamping the
    fingerprint, so the next verified read compared post-migration
    content against a pre-migration hash and raised a false positive.
    _connect() must re-stamp the fingerprint as part of migrating a file
    that already had one."""
    from biracki_odbor.core import file_integrity

    out = tmp_path / "committee.db"
    _build_v1_db_with_data(out)
    # Simulate "already verified from normal use under the old app version"
    # -- the fingerprint a real install would have from its last save.
    file_integrity.record_verified(out)

    # Any call through master_io migrates the file to v2 in place --
    # must not invalidate the fingerprint that was just established.
    master_io.read_master(out, verify=True, spec=STALNI_SPEC)
    # A second read (e.g. a different tab opening) must also still pass,
    # proving the re-stamp actually matches the post-migration bytes.
    master_io.read_master(out, verify=True, spec=STALNI_SPEC)


def test_fresh_db_creation_does_not_stamp_a_premature_fingerprint(tmp_path: Path) -> None:
    """A brand-new file has no prior fingerprint to repair -- _connect()
    must NOT stamp one during schema creation itself (before the real
    rows are inserted), or write_master's own post-insert content would
    immediately mismatch against that premature, empty-table snapshot."""
    out = tmp_path / "committee.db"
    persons = [Person(bm_number=1, function="Председник", party="СНС",
                       first_name="Ана", last_name="Анић", jmbg="1605991774818")]
    master_io.write_master(persons, _make_oik(1), out, spec=STALNI_SPEC, verify=True)
    master_io.read_master(out, verify=True, spec=STALNI_SPEC)  # must NOT raise


def test_same_workflow_duplicate_jmbg_is_allowed(tmp_path: Path) -> None:
    """Duplicate JMBGs WITHIN one workflow are a normal, soft-resolvable
    state (multiple parties submitting the same person) -- detect_conflicts
    surfaces these for the operator; the DB must not hard-block them."""
    out = tmp_path / "committee.db"
    shared_jmbg = "0101990710099"
    persons = [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg=shared_jmbg),
        Person(bm_number=2, function="Члан 1", party="СПС",
               first_name="Ана", last_name="Анић", jmbg=shared_jmbg),
    ]
    master_io.write_master(persons, _make_oik(2), out, spec=STALNI_SPEC)
    loaded = master_io.read_master(out, spec=STALNI_SPEC)
    assert len(loaded) == 2
    assert {p.jmbg for p in loaded} == {shared_jmbg}


def test_cross_workflow_allows_same_jmbg_when_not_filled(tmp_path: Path) -> None:
    """An empty-name placeholder row sharing a JMBG string (edge case,
    e.g. both blank) must not trip the uniqueness index -- it only
    applies to actually-filled persons, mirroring Person.is_filled."""
    out = tmp_path / "committee.db"
    unfilled = Person(bm_number=1, function="Председник", party="СНС", jmbg="")
    master_io.write_master([unfilled], _make_oik(1), out, spec=STALNI_SPEC)
    # Should not raise -- both rows are unfilled (blank names).
    master_io.write_master([Person(bm_number=1, function="Члан [1]", party="ent1", jmbg="")],
                            _make_oik(1), out, spec=PROSIRENI_SPEC)


def test_export_master_xlsx_produces_openable_workbook(tmp_path: Path) -> None:
    import openpyxl
    out = tmp_path / "export.xlsx"
    persons = _make_persons()
    master_io.export_master_xlsx(persons, _make_oik(3), out, spec=STALNI_SPEC)
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    try:
        assert wb.active.title
        assert "Статистика" in wb.sheetnames
    finally:
        wb.close()


def test_read_legacy_xlsx_master_parses_old_format(tmp_path: Path) -> None:
    """The one-time migration reader must still parse the pre-SQLite
    per-workflow xlsx layout correctly."""
    legacy_path = tmp_path / "zbirana_tabela.xlsx"
    persons = _make_persons()
    master_io.export_master_xlsx(persons, _make_oik(3), legacy_path, spec=STALNI_SPEC)
    parsed = master_io._read_legacy_xlsx_master(legacy_path)
    assert len(parsed) == len(persons)
    assert parsed[0].jmbg == persons[0].jmbg
    assert parsed[0].first_name == persons[0].first_name


# ── Startup reconciliation (legacy xlsx -> shared committee.db) ──────────


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    yield


def test_reconcile_imports_both_legacy_masters(tmp_path: Path) -> None:
    from biracki_odbor import app_paths

    stalni_persons = _make_persons(jmbg_start=101990710001)
    prosireni_persons = _make_persons(jmbg_start=201990710001)
    master_io.export_master_xlsx(
        stalni_persons, _make_oik(3), app_paths.legacy_xlsx_master_path_for(STALNI_SPEC),
        spec=STALNI_SPEC,
    )
    master_io.export_master_xlsx(
        prosireni_persons, _make_oik(3), app_paths.legacy_xlsx_master_path_for(PROSIRENI_SPEC),
        spec=PROSIRENI_SPEC,
    )

    assert master_io.reconcile_legacy_xlsx_masters() is True

    db_path = app_paths.committee_db_path()
    migrated_stalni = master_io.read_master(db_path, spec=STALNI_SPEC)
    migrated_prosireni = master_io.read_master(db_path, spec=PROSIRENI_SPEC)
    assert len(migrated_stalni) == len(stalni_persons)
    assert len(migrated_prosireni) == len(prosireni_persons)

    # Legacy files are renamed, not deleted -- and no longer picked up again.
    assert not app_paths.legacy_xlsx_master_path_for(STALNI_SPEC).exists()
    assert not app_paths.legacy_xlsx_master_path_for(PROSIRENI_SPEC).exists()
    assert app_paths.legacy_xlsx_master_path_for(STALNI_SPEC).with_name(
        app_paths.legacy_xlsx_master_path_for(STALNI_SPEC).name + ".migrated"
    ).exists()

    # A pre-migration safety backup was taken.
    backups = list((app_paths.home() / "backups").glob("pre-migration-*.zip"))
    assert len(backups) == 1


def test_reconcile_is_a_noop_without_legacy_files(tmp_path: Path) -> None:
    """No legacy xlsx present (fresh install, or already migrated) --
    must not create a committee.db or a backup out of nothing."""
    from biracki_odbor import app_paths

    assert master_io.reconcile_legacy_xlsx_masters() is False

    assert not app_paths.committee_db_path().exists()
    backups_dir = app_paths.home() / "backups"
    assert not backups_dir.exists() or not list(backups_dir.glob("pre-migration-*.zip"))


def test_reconcile_second_run_is_idempotent(tmp_path: Path) -> None:
    from biracki_odbor import app_paths

    master_io.export_master_xlsx(
        _make_persons(), _make_oik(3), app_paths.legacy_xlsx_master_path_for(STALNI_SPEC),
        spec=STALNI_SPEC,
    )
    assert master_io.reconcile_legacy_xlsx_masters() is True
    first_backup_count = len(list((app_paths.home() / "backups").glob("pre-migration-*.zip")))

    # Second run: no legacy files left, must be a clean no-op.
    assert master_io.reconcile_legacy_xlsx_masters() is False
    second_backup_count = len(list((app_paths.home() / "backups").glob("pre-migration-*.zip")))
    assert second_backup_count == first_backup_count
    assert len(master_io.read_master(app_paths.committee_db_path(), spec=STALNI_SPEC)) == 9


def test_schema_migration_fixes_zamenik_clana_typo(tmp_path: Path) -> None:
    """"Заменик клана" (missing "ч") was baked into прошиени's
    SUBSTITUTE_LABEL constant since прошиени's first commit -- an
    already-persisted v2 DB has it as part of the PRIMARY KEY, so fixing
    just the constant would silently stop matching these rows (empty
    slots in generated решења) until re-aggregated from scratch. The
    migration must rewrite the stored text in place."""
    out = tmp_path / "committee.db"
    conn = sqlite3.connect(str(out))
    conn.execute(
        """
        CREATE TABLE persons (
            workflow TEXT NOT NULL CHECK (workflow IN ('stalni', 'prosireni')),
            bm_number INTEGER NOT NULL, function TEXT NOT NULL,
            party TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '', jmbg TEXT NOT NULL DEFAULT '',
            mesto TEXT NOT NULL DEFAULT '', adresa TEXT NOT NULL DEFAULT '',
            telefon TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            appointed_by_nacelnik INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (workflow, bm_number, function)
        )
        """
    )
    conn.execute(
        "INSERT INTO persons (workflow, bm_number, function, party,"
        " first_name, last_name, jmbg, mesto, adresa, telefon, email,"
        " appointed_by_nacelnik) VALUES ('prosireni', 1, 'Заменик клана [1]',"
        " 'СНС', 'Ана', 'Анић', '1605991774818', '', '', '', '', 0)"
    )
    # A real стални row too — the migration's WHERE clause must not touch it.
    conn.execute(
        "INSERT INTO persons (workflow, bm_number, function, party,"
        " first_name, last_name, jmbg, mesto, adresa, telefon, email,"
        " appointed_by_nacelnik) VALUES ('stalni', 1, 'Председник', 'СНС',"
        " 'Пера', 'Перић', '2002990710029', '', '', '', '', 0)"
    )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    persons = master_io.read_master(out, spec=PROSIRENI_SPEC)
    assert len(persons) == 1
    assert persons[0].function == "Заменик члана [1]"
    assert persons[0].first_name == "Ана"  # the row itself wasn't lost/duplicated

    stalni_persons = master_io.read_master(out, spec=STALNI_SPEC)
    assert stalni_persons[0].function == "Председник"

    conn = sqlite3.connect(str(out))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == master_io._SCHEMA_VERSION  # noqa: SLF001
    finally:
        conn.close()
