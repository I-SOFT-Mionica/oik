"""Read and write the aggregated master roster.

Internal storage is a single shared SQLite file (`committee.db`, one
`persons` table for both workflows) — see `_connect()` for the schema.
The Phase 2 aggregator produces/updates it; the Corrections tab loads
it into `Person` objects, mutates in memory, then writes it back. This
module is the round-trip layer and the only place that touches the
storage format directly.

Schema version 1 added a DB-level trigger hard-blocking a write that
would give the same filled JMBG a seat in both стални and проширени at
once. Version 2 drops it (migrated away on every already-initialized
DB, not just skipped for new ones — see `_connect()`): a hard,
unconditional block has no non-destructive way to recover when it
fires, and in practice the only "recovery" available (phase2_aggregate.
py used to blank the colliding JMBG and retry) hid the collision from
every downstream duplicate-detection mechanism instead of surfacing
it. The real block now lives at Phase 3 (validation.preflight.
preflight_phase3) — producing a решење for an already-double-seated
person is the costly mistake, not importing the data; Phase 2 and
Corrections only ever soft-flag it (core.row_checks.
find_cross_workflow_duplicate_jmbgs), same treatment a same-workflow
duplicate already gets.

Version 3 rewrites any persisted прошиени `function` text still reading
"Заменик клана …" (a typo — missing "ч" — in `SUBSTITUTE_LABEL` since
прошиени's first commit) to the correct "Заменик члана …", so already-
imported rows keep matching слот lookups built from the now-fixed
constant.

`export_master_xlsx()` is the human-facing counterpart: it produces a
real, readable `.xlsx` (the same layout the master used to be stored
as) for operator-initiated exports ("Извези", error-row export) — the
internal store itself is never handed to anyone directly.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core.models import Person
from biracki_odbor.core.workflow import WorkflowSpec

log = logging.getLogger(__name__)

_SCHEMA_VERSION = 3

_COLUMNS = (
    "bm_number", "function", "party", "first_name", "last_name",
    "jmbg", "mesto", "adresa", "telefon", "email", "appointed_by_nacelnik",
)


def _workflow_of(spec: WorkflowSpec | None) -> str:
    return spec.slug if spec is not None else "stalni"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    # Schema init must be SKIPPED once already applied -- `PRAGMA user_version
    # = N` (and, empirically, re-running `CREATE TABLE/TRIGGER IF NOT EXISTS`
    # on an already-matching schema) unconditionally WRITES to the file even
    # when nothing actually changes. Since this function backs read_master()
    # too, that turned every "read" into a silent mutation of the file's
    # bytes -- which broke file_integrity's fingerprinting: any verified read
    # invalidated itself the moment it ran, so the very next verified read
    # (from any tab) saw a false "changed outside the application" mismatch,
    # forever. Checking user_version first (a pure read, no side effect)
    # makes this function a true no-op against an already-initialized DB.
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if current_version >= _SCHEMA_VERSION:
        return conn
    if current_version < 1:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS persons (
                workflow TEXT NOT NULL CHECK (workflow IN ('stalni', 'prosireni')),
                bm_number INTEGER NOT NULL,
                function TEXT NOT NULL,
                party TEXT NOT NULL DEFAULT '',
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                jmbg TEXT NOT NULL DEFAULT '',
                mesto TEXT NOT NULL DEFAULT '',
                adresa TEXT NOT NULL DEFAULT '',
                telefon TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                appointed_by_nacelnik INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (workflow, bm_number, function)
            )
            """
        )
    if current_version < 2:
        # See module docstring: the hard cross-workflow block moved to
        # Phase 3's preflight gate. Unconditional (not IF EXISTS-guarded
        # on a condition) because a version-1 DB is guaranteed to have
        # created it; a fresh (version-0) DB never did, so this is a
        # harmless no-op for it.
        conn.execute("DROP TRIGGER IF EXISTS trg_persons_cross_workflow_jmbg")
    if current_version < 3:
        # "Заменик клана" was a typo (missing "ч") baked into
        # core.prosireni_allocation.SUBSTITUTE_LABEL since прошиени's
        # very first commit -- fixing the constant alone would silently
        # break slot matching (member_by_func lookups, Corrections' slot
        # keys) for every прошиени row already persisted under the old
        # spelling, since function is part of this table's PRIMARY KEY.
        # Rewrite in place instead.
        conn.execute(
            """
            UPDATE persons SET function = REPLACE(function, 'Заменик клана', 'Заменик члана')
            WHERE workflow = 'prosireni' AND function LIKE 'Заменик клана%'
            """
        )
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    # Earlier migrations only ever ran DDL (CREATE/DROP TRIGGER), which
    # SQLite auto-commits regardless of transaction state -- this one is
    # the first to run a plain UPDATE, which does NOT auto-commit. Without
    # this, read_master()'s conn.close() (no commit anywhere in its own
    # path) silently rolled the UPDATE back, so the fix never actually
    # reached disk -- every read just re-ran (and re-discarded) it.
    conn.commit()
    # A migration just changed this file's bytes (same DDL-writes-even-
    # when-IF-EXISTS-matches behavior the comment above already warns
    # about). If this path already has a verified fingerprint, that
    # fingerprint is now stale and must be re-stamped here, or the very
    # next verified read sees a false "changed outside the application"
    # mismatch. Only when one already exists, though -- a BRAND NEW file
    # (first-ever creation, nothing inserted yet) must NOT get a
    # fingerprint stamped here, since write_master() hasn't written the
    # actual rows yet; stamping now would freeze an empty-table snapshot
    # that the real data then mismatches against. Let write_master's own
    # verify=True path (or check_or_raise's "no baseline yet" rule)
    # establish that one when the real content is actually in place.
    from biracki_odbor.core import file_integrity
    if file_integrity.has_verified_copy(path):
        file_integrity.record_verified(path)
    return conn


def read_master(
    path: Path | str, *, verify: bool = False, spec: WorkflowSpec | None = None,
) -> list[Person]:
    """Return this workflow's Person rows from the shared committee DB.

    `verify=True` — only for reads of the canonical working copy
    (`app_paths.master_path()` / `master_path_for(spec)`), never for an
    operator-chosen export path — checks the file against its last
    verified fingerprint first and raises `file_integrity.
    IntegrityMismatchError` on a mismatch. See core/file_integrity.py.
    """
    p = Path(path)
    if verify:
        from biracki_odbor.core import file_integrity
        file_integrity.check_or_raise(p)
    if not p.exists():
        return []
    workflow = _workflow_of(spec)
    conn = _connect(p)
    try:
        # Order by rowid (insertion order), NOT function name -- role order
        # (Председник, Заменик председника, Члан 1, ...) is NOT alphabetical,
        # and write_master() inserts rows in the caller's intended order.
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM persons"
            " WHERE workflow=? ORDER BY bm_number, rowid",
            (workflow,),
        ).fetchall()
    finally:
        conn.close()
    return [
        Person(
            bm_number=r[0], function=r[1], party=r[2], first_name=r[3],
            last_name=r[4], jmbg=r[5], mesto=r[6], adresa=r[7], telefon=r[8],
            email=r[9], appointed_by_nacelnik=bool(r[10]),
        )
        for r in rows
    ]


def write_master(
    persons: list[Person], oik: OikConstants, path: Path | str, *,
    verify: bool = False, spec: WorkflowSpec | None = None,
) -> Path:
    """Persist this workflow's Person list into the shared committee DB.

    Replaces this workflow's rows atomically (delete + bulk insert, one
    transaction). Writes whatever JMBG `persons` carries, even if it
    collides with a filled JMBG already recorded under the OTHER
    workflow — that collision is soft-flagged (core.row_checks.
    find_cross_workflow_duplicate_jmbgs) and only actually BLOCKED at
    Phase 3 (validation.preflight.preflight_phase3), never here. See
    the module docstring for why this changed.

    `oik` is accepted for interface stability (older callers pass it)
    but unused internally — station-name lookups only matter for the
    human-facing `export_master_xlsx()`.

    `verify=True` — records a fresh fingerprint + verified snapshot
    immediately after the write, so the next `read_master(...,
    verify=True)` trusts exactly this content.
    """
    p = Path(path)
    workflow = _workflow_of(spec)
    conn = _connect(p)
    try:
        with conn:
            conn.execute("DELETE FROM persons WHERE workflow=?", (workflow,))
            conn.executemany(
                f"INSERT INTO persons (workflow, {', '.join(_COLUMNS)})"
                f" VALUES ({', '.join(['?'] * (len(_COLUMNS) + 1))})",
                [
                    (
                        workflow, p_.bm_number, p_.function, p_.party,
                        p_.first_name, p_.last_name, p_.jmbg, p_.mesto,
                        p_.adresa, p_.telefon, p_.email,
                        int(p_.appointed_by_nacelnik),
                    )
                    for p_ in persons
                ],
            )
    finally:
        conn.close()
    if verify:
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(p)
    return p


def export_master_xlsx(
    persons: list[Person], oik: OikConstants, out_path: Path | str, *,
    spec: WorkflowSpec | None = None,
) -> Path:
    """Write a human-readable `.xlsx` export of the given persons.

    This is the ONLY place that still produces the old master layout
    (14 columns, derived "Гласачко место"/"Р.бр.", Статистика sheet,
    JMBG MOD-11 conditional formatting) — used exclusively for
    operator-initiated exports ("Извези", error-row export). The
    internal working copy is never handed to anyone directly.
    """
    from biracki_odbor.core.phase2_aggregate import _write_xlsx_export
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xlsx_export(persons, oik, out_path, spec=spec)
    return out_path


def _read_legacy_xlsx_master(path: Path | str) -> list[Person]:
    """Parse an OLD per-workflow master `.xlsx` (pre-SQLite-migration
    format) back into Person rows. Used exactly once, by the startup
    reconciliation step, to import pre-existing data into the new
    shared committee DB. Not used for any ongoing read path.

    This is the same column layout/positional-read logic the app used
    before the SQLite migration:
      1 Р.бр.  2 БМ бр.  3 Гласачко место  4 Функција
      5 Име  6 Презиме  7 ЈМБГ  8 Место  9 Адреса
      10 Телефон  11 Е-пошта  12 Предлагач  13 Статус
      14 Именовао начелник
    Header on row 2, data from row 3.
    """
    import openpyxl

    def _cell(row: tuple, idx: int) -> str:
        if idx >= len(row) or row[idx] is None:
            return ""
        return str(row[idx]).strip()

    p = Path(path)
    if not p.exists():
        return []
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    try:
        ws = wb.active
        persons: list[Person] = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            raw_bm = row[1] if len(row) > 1 else None
            if raw_bm is None:
                break
            try:
                bm = int(raw_bm) if not isinstance(raw_bm, bool) else 0
            except (TypeError, ValueError):
                continue
            persons.append(Person(
                bm_number=bm,
                function=_cell(row, 3),
                first_name=_cell(row, 4),
                last_name=_cell(row, 5),
                jmbg=_cell(row, 6),
                mesto=_cell(row, 7),
                adresa=_cell(row, 8),
                telefon=_cell(row, 9),
                email=_cell(row, 10),
                party=_cell(row, 11),
                appointed_by_nacelnik=_cell(row, 13) == "Да",
            ))
    finally:
        wb.close()
    return persons


def reconcile_legacy_xlsx_masters() -> bool:
    """One-time import of pre-SQLite-migration per-workflow `.xlsx`
    masters into the shared `committee.db`.

    Call once at startup when an app-version upgrade is detected (see
    `__main__.py` / `AppSettings.last_run_version`). Idempotent in
    practice: a legacy file is renamed with a `.migrated` suffix right
    after a successful import, so a second run finds nothing left to do.

    Takes an unconditional backup BEFORE touching anything (not the
    daily-due check — this always runs once, regardless of when the
    last automatic backup happened) and aborts the whole migration
    (nothing renamed, nothing imported) if that backup fails, since a
    failed safety net means the migration itself isn't safe to attempt.

    Returns True iff at least one workflow was actually migrated — the
    caller uses this to flag `core.maintenance`'s
    "cleanup_legacy_migration_files" one-off action as available, since
    there's now something for it to clean up.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.core import backup
    from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC

    specs = (STALNI_SPEC, PROSIRENI_SPEC)
    pending = [
        (spec, path)
        for spec in specs
        if (path := app_paths.legacy_xlsx_master_path_for(spec)).exists()
    ]
    if not pending:
        return False

    home = app_paths.home()
    backups_dir = home / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pre_migration_backup = backups_dir / f"pre-migration-{ts}.zip"
    try:
        backup.build_backup_zip(home, pre_migration_backup)
    except Exception:
        log.exception(
            "reconcile_legacy_xlsx_masters: pre-migration backup failed —"
            " aborting migration, legacy masters left untouched",
        )
        return False

    db_path = app_paths.committee_db_path()
    migrated_any = False
    for spec, legacy_path in pending:
        try:
            persons = _read_legacy_xlsx_master(legacy_path)
            write_master(persons, OikConstants(), db_path, spec=spec)
        except Exception:
            log.exception(
                "reconcile_legacy_xlsx_masters: failed to migrate %s (workflow=%s)",
                legacy_path, spec.slug,
            )
            continue
        legacy_path.rename(legacy_path.with_name(legacy_path.name + ".migrated"))
        migrated_any = True
        log.info(
            "reconcile_legacy_xlsx_masters: migrated %d row(s) for workflow=%s from %s",
            len(persons), spec.slug, legacy_path,
        )
    return migrated_any
