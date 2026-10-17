"""Phase 2: read filled-in party files, validate, write master spreadsheet.

Refactored from legacy bo_system.py:aggregate_party_files. Key changes:
  - Detects duplicate (bm, function) collisions across files instead of
    silently overwriting (ROW_OVERWRITE issue).
  - Detects same JMBG in multiple rows (JMBG_DUPLICATE issue) — feeds
    Phase 2.5 conflict resolution.
  - Per-row validation via validation.rows.validate_person — all issues
    Cyrillic-formatted.
  - Returns (Person list, master_path, ValidationReport) — the GUI can
    inspect the list before showing it, and the .xlsx is still written.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import openpyxl
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core import phone as phone_mod
from biracki_odbor.core import popunjeni_cache
from biracki_odbor.core.xlsx_safety import safe_cell
from biracki_odbor.core.models import (
    Allocation,
    Issue,
    Person,
    PollingStation,
    ValidationReport,
    slot_rbr,
)
from biracki_odbor.core.phase1_generate import (
    BM_SEPARATOR_BORDER,
    HEADER_FILL,
    HEADER_FONT,
    INVALID_FILL,
    THIN_BORDER,
    VALID_FILL,
)
from openpyxl.formatting.rule import FormulaRule
from biracki_odbor.core.template import read_template
from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC, WorkflowSpec
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation import rows as row_checks
from biracki_odbor.validation.reports import Codes, message


@dataclass
class Phase2Result:
    persons: list[Person]
    master_path: Path
    report: ValidationReport
    files_processed: int


@log_timing("aggregate_party_files")
def aggregate_party_files(
    input_dir: Path | str,
    template_path: Path | str | None,
    output_path: Path | str,
    oik: OikConstants,
    progress: Callable[[str, int, int], None] | None = None,
    max_workers: int | None = None,
    election: ElectionConfig | None = None,
    spec: WorkflowSpec | None = None,
    allocations_override: list[Allocation] | None = None,
) -> Phase2Result:
    """Aggregate the allowlisted party returns into one master workbook.

    Source of truth is the popunjeni cache (paths populated by
    `popunjeni_io.import_file`). Files in `input_dir` that aren't in the
    cache surface as `UNIMPORTED_FILE` warnings and are not aggregated —
    this enforces the rule that every party return must come through the
    import button. The master .xlsx is always written; reads only happen
    for cache-miss files (rare: only the "user edited outside the app"
    case).

    Args:
      election: when provided, scopes the cache to this cycle's
        `election_uuid`. Mismatched/missing UID wipes the cache at load.
      spec: which workflow to aggregate; defaults to STALNI_SPEC.
      allocations_override: when provided, skip template reading and use
        these allocations directly. Used by prosireni workflow where the
        allocation is computed from the candidacies registry, not from a
        static template file.
    """
    if spec is None:
        spec = STALNI_SPEC
    import logging
    import os
    log = logging.getLogger(__name__)

    report = ValidationReport()

    if allocations_override is not None:
        alloc_list = allocations_override
    else:
        if template_path is None:
            report.add(Issue(
                code=Codes.FILE_MISSING,
                message_sr="Није наведен шаблон за обједињавање.",
                severity="error",
            ))
            return Phase2Result([], Path(output_path), report, 0)
        template_data, t_report = read_template(template_path)
        report.extend(t_report)
        if not report.ok:
            return Phase2Result([], Path(output_path), report, 0)
        alloc_list = list(template_data.allocations)

    expected: dict[tuple[int, str], Allocation] = {
        (a.bm_number, a.function): a for a in alloc_list
    }

    in_dir = Path(input_dir)
    if not in_dir.exists() or not in_dir.is_dir():
        report.add(Issue(
            code=Codes.FILE_MISSING,
            message_sr=message(Codes.FILE_MISSING, file=str(in_dir)),
            severity="error",
            file=str(in_dir),
        ))
        return Phase2Result([], Path(output_path), report, 0)

    # ── Read step ───────────────────────────────────────────────────────
    # Two modes:
    #  • When `election` is provided (production GUI flow): cache-allowlist.
    #    The popunjeni cache is the source of truth for which files are
    #    in scope; anything else on disk surfaces as UNIMPORTED_FILE.
    #  • When `election` is None (legacy tests + headless callers): scan
    #    every .xlsx in `input_dir` and read it, as before. No cache,
    #    no allowlist.
    persons_by_slot: dict[tuple[int, str], Person] = {}
    source_file_by_slot: dict[tuple[int, str], str] = {}

    if max_workers is None:
        max_workers = min(4, os.cpu_count() or 2)

    read_results: dict[Path, tuple[list[tuple[tuple[int, str], Person]], list[Issue]]] = {}

    if election is not None:
        # ── Cache-allowlist mode ──
        election_uuid = election.election_uuid.strip()
        cache_data = popunjeni_cache.load(election_uuid=election_uuid)
        popunjeni_cache.prune_missing(cache_data)

        # Visibility pass: files on disk but not in cache get warned.
        on_disk = sorted(
            f for f in in_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".xlsx" and not f.name.startswith("~")
        )
        cached_paths = {Path(p) for p in cache_data.entries.keys()}
        for fp in on_disk:
            if fp not in cached_paths:
                report.add(Issue(
                    code=Codes.UNIMPORTED_FILE,
                    message_sr=message(Codes.UNIMPORTED_FILE, file=fp.name),
                    severity="warning",
                    file=fp.name,
                ))

        # Multiple submissions per party are now valid (every import
        # gets a timestamped filename); pick the latest by
        # received_time_iso so the aggregator reads ONLY the freshest
        # per party. Older versions stay on disk (audit trail) and
        # surface as info-level notes in the report.
        all_paths = [Path(p) for p in sorted(cache_data.entries.keys())]
        by_party: dict[str, list[Path]] = {}
        for fp in all_paths:
            entry = cache_data.entries.get(str(fp))
            if entry is None:
                continue
            # Group by the cached `party` field — populated at import
            # time. Pre-v2 cache entries lack it; fall back to None so
            # they all land in one "unknown" bucket and the first new
            # import of any party shadows them via the
            # received_time_iso sort below.
            by_party.setdefault(entry.party or "", []).append(fp)

        files: list[Path] = []
        for party, party_files in by_party.items():
            # Sort by received_time_iso (lexicographic ↔ chronological);
            # empty strings (legacy v1 entries) sort first, so they
            # become the "oldest" — any newer timestamped submission
            # supersedes them.
            party_files.sort(
                key=lambda p: cache_data.entries[str(p)].received_time_iso or "",
            )
            chosen = party_files[-1]
            files.append(chosen)
            if len(party_files) > 1:
                superseded = [p.name for p in party_files[:-1]]
                report.add(Issue(
                    code=Codes.MULTIPLE_SUBMISSIONS,
                    message_sr=message(
                        Codes.MULTIPLE_SUBMISSIONS,
                        file=chosen.name,
                        detail=(
                            f"{party or '(непозната странка)'}: користи се"
                            f" {chosen.name}; занемарено {len(superseded)}"
                            f" старијих пријава ({', '.join(superseded)})"
                        ),
                    ),
                    severity="info",
                    file=chosen.name, detail=party,
                ))
        files.sort()
        total = len(files)
        log.info(
            "aggregate_party_files: %d cached files chosen (one per party)"
            " out of %d total submissions (max_workers=%d)",
            total, len(all_paths), max_workers,
        )

        miss_files: list[Path] = []
        for fp in files:
            entry = cache_data.entries.get(str(fp))
            if popunjeni_cache.hit(fp, entry) and entry is not None:
                read_results[fp] = (entry.to_records_tuples(), entry.to_issues_list())
            else:
                miss_files.append(fp)

        if miss_files:
            from biracki_odbor.core.popunjeni_io import parse_party_file
            if max_workers <= 1 or len(miss_files) < 6:
                for fp in miss_files:
                    read_results[fp] = parse_party_file(fp)
            else:
                from concurrent.futures import ProcessPoolExecutor, as_completed
                with ProcessPoolExecutor(max_workers=max_workers) as pool:
                    future_to_fp = {pool.submit(parse_party_file, fp): fp for fp in miss_files}
                    for fut in as_completed(future_to_fp):
                        fp = future_to_fp[fut]
                        read_results[fp] = fut.result()
            for fp in miss_files:
                records, issues = read_results[fp]
                # Preserve received_time_iso + import_source +
                # party from the existing cache entry — we're
                # refreshing the parsed records but not the
                # submission metadata.
                prev = cache_data.entries.get(str(fp))
                cache_data.entries[str(fp)] = popunjeni_cache.CacheEntry.from_parsed(
                    fp, records, issues,
                    received_time_iso=(prev.received_time_iso if prev else ""),
                    import_source=(prev.import_source if prev else "file_picker"),
                    party=(prev.party if prev else ""),
                    imported_by=(prev.imported_by if prev else ""),
                )
            popunjeni_cache.save(cache_data)
    else:
        # ── Legacy scan mode (no cache, no allowlist) ──
        files = sorted(
            f for f in in_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".xlsx" and not f.name.startswith("~")
        )
        total = len(files)
        log.info(
            "aggregate_party_files: %d popunjeni files to read (max_workers=%d)",
            total, max_workers,
        )

        if max_workers <= 1 or total < 6:
            for fp in files:
                read_results[fp] = _read_party_file(fp)
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                future_to_fp = {pool.submit(_read_party_file, fp): fp for fp in files}
                for fut in as_completed(future_to_fp):
                    fp = future_to_fp[fut]
                    read_results[fp] = fut.result()

    for idx, fp in enumerate(files, start=1):
        if progress:
            progress(fp.name, idx, total)
        records, file_issues = read_results[fp]
        for issue in file_issues:
            report.add(issue)
        for key, person in records:
            if key in persons_by_slot and person.is_filled:
                # ROW_OVERWRITE is a real bug in legacy code — surface it.
                report.add(Issue(
                    code=Codes.ROW_OVERWRITE,
                    message_sr=message(Codes.ROW_OVERWRITE, row=key[0], detail=key[1]),
                    severity="warning",
                    file=fp.name, detail=key[1],
                ))
            if person.is_filled or key not in persons_by_slot:
                persons_by_slot[key] = person
                source_file_by_slot[key] = fp.name

    # ── Per-row validation ──────────────────────────────────────────────
    persons: list[Person] = []
    # Phase B context for per-row validation:
    #   - candidate_jmbgs blocks committee members also running for office (B1).
    #   - election_date drives the 18+ check (B2).
    # Both are None when `election` is None (legacy aggregator calls or
    # an election without the dates filled in yet) — `validate_person`
    # treats None as "skip this check", so existing tests stay green.
    candidate_jmbgs: set[str] | None = None
    election_date = None
    if election is not None:
        candidate_jmbgs = election.candidacies.jmbg_index()
        from biracki_odbor.core import jmbg as _jmbg
        # `extract_date_of_birth` lives on jmbg.py; we want the
        # election day from `election.election.dates.date_full`. Parse
        # it via the existing declension helper for robustness.
        from biracki_odbor.config import declension as _decl
        parsed = _decl.parse_serbian_date(
            election.election.dates.date_full or "",
        )
        if parsed is not None:
            from datetime import date as _date
            try:
                election_date = _date(*parsed)
            except ValueError:
                election_date = None

    if spec.enforce_one_team_per_bm:
        from biracki_odbor.core.prosireni_allocation import func_sort_key as _fsk
        _slot_sort = lambda k: (k[0], _fsk(k[1]))  # noqa: E731
    else:
        _fo = {r.label_sr: i for i, r in enumerate(spec.roles)}
        _slot_sort = lambda k: (k[0], _fo.get(k[1], 99))  # noqa: E731
    for (bm, func) in sorted(expected.keys(), key=_slot_sort):
        alloc = expected[(bm, func)]
        if (bm, func) in persons_by_slot:
            person = persons_by_slot[(bm, func)]
            # Authoritative party comes from the template's Raspodela.
            person.party = alloc.party
            file_label = source_file_by_slot.get((bm, func), "")
            for issue in row_checks.validate_person(
                person, file=file_label,
                candidate_jmbgs=candidate_jmbgs,
                election_date=election_date,
                spec=spec,
            ):
                report.add(issue)
            persons.append(person)
        else:
            persons.append(Person(bm_number=bm, function=func, party=alloc.party))

    # Cross-row: duplicate JMBGs
    for issue in row_checks.find_duplicate_jmbgs(persons):
        report.add(issue)

    # Cross-workflow: a person already holding a filled seat in the OTHER
    # workflow's committee (стални vs проширени) can't also hold one here.
    # Flagged here as a report issue — same soft treatment as a
    # same-workflow duplicate (never blocks this batch from saving). The
    # actual block belongs at Phase 3 (see validation.preflight.
    # preflight_phase3) — producing a решење that appoints an
    # already-double-seated person is the costly mistake, not importing
    # the data; a hard DB-level block used to live here instead, and its
    # only way to "recover" was mutating the colliding JMBG to blank,
    # which hid the problem from every downstream check.
    other_spec = STALNI_SPEC if spec.slug == "prosireni" else PROSIRENI_SPEC
    other_jmbgs = row_checks.other_workflow_filled_jmbgs(output_path, other_spec)
    if other_jmbgs:
        for issue in row_checks.find_cross_workflow_duplicate_jmbgs(
            persons, other_jmbgs, other_spec.resenja_item_i_intro,
        ):
            report.add(issue)

    # Cross-row: prosireni one-team-per-BM — the same person cannot be the
    # primary member (Члан [N]) for two different entities at the same BM.
    if spec.enforce_one_team_per_bm:
        from biracki_odbor.core.prosireni_allocation import parse_slot_function
        bm_member_jmbgs: dict[int, set[str]] = {}
        for p in persons:
            if not p.is_filled or not p.jmbg:
                continue
            parsed = parse_slot_function(p.function)
            if parsed is None or parsed[1] != 0:
                continue  # skip substitutes and non-prosireni slots
            bm_set = bm_member_jmbgs.setdefault(p.bm_number, set())
            if p.jmbg in bm_set:
                report.add(Issue(
                    code=Codes.ROW_OVERWRITE,
                    message_sr=(
                        f"БМ {p.bm_number}: ЈМБГ {p.jmbg} је именован за члана"
                        " вишеструких ентитета на истом бирачком месту."
                    ),
                    severity="error",
                    detail=p.jmbg,
                ))
            else:
                bm_set.add(p.jmbg)

    # ── Write master ────────────────────────────────────────────────────
    from biracki_odbor.core.master_io import write_master as _write_master
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_master(persons, oik, out_path, spec=spec)

    return Phase2Result(persons, out_path, report, files_processed=len(files))


def _coerce_bm(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return int(s)
    return None


def _read_party_file(
    file_path: Path,
) -> tuple[list[tuple[tuple[int, str], Person]], list[Issue]]:
    """Module-level worker: parse one popunjeni .xlsx.

    Returns `(records, issues)` where `records` is a list of `(key, person)`
    pairs in the order they appear in the file. Cross-file deduplication and
    ROW_OVERWRITE detection are deferred to the caller (main thread), so the
    function is safe to call from a ProcessPoolExecutor — no shared state.
    """
    issues: list[Issue] = []
    records: list[tuple[tuple[int, str], Person]] = []

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    except PermissionError:
        issues.append(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(file_path)),
            severity="error",
            file=str(file_path),
        ))
        return records, issues
    except Exception as e:  # noqa: BLE001
        issues.append(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(file_path)) + f" ({e})",
            severity="error",
            file=str(file_path),
        ))
        return records, issues

    try:
        ws = wb.active
        if ws is None:
            return records, issues
        # iter_rows for the same O(N) reason as read_master; the per-party
        # files can have hundreds of rows.
        for row_idx, row_values in enumerate(
            ws.iter_rows(min_row=4, values_only=True), start=4,
        ):
            raw_bm = row_values[1] if len(row_values) > 1 else None
            func = row_values[3] if len(row_values) > 3 else None
            if raw_bm is None or func is None:
                continue

            bm = _coerce_bm(raw_bm)
            if bm is None:
                issues.append(Issue(
                    code=Codes.BM_NUMBER_NOT_INT,
                    message_sr=message(Codes.BM_NUMBER_NOT_INT, detail=str(raw_bm)),
                    severity="error",
                    file=file_path.name, row=row_idx, detail=str(raw_bm),
                ))
                continue

            def _str(idx: int) -> str:
                v = row_values[idx] if len(row_values) > idx else None
                return str(v or "").strip()

            func_s = _str(3)
            # Schema (post-split): E=Име, F=Презиме, G=ЈМБГ, H=Место,
            # I=Адреса, J=Телефон, K=Е-пошта, L=Предлагач
            first_name = _str(4)
            last_name = _str(5)
            jmbg = str(jmbg_mod.normalize(
                row_values[6] if len(row_values) > 6 else None
            ))
            mesto = _str(7)
            adresa = _str(8)
            telefon = phone_mod.normalize(
                row_values[9] if len(row_values) > 9 else None
            )
            email = _str(10)
            party = _str(11)

            person = Person(
                bm_number=bm, function=func_s, party=party,
                first_name=first_name, last_name=last_name,
                jmbg=jmbg, mesto=mesto, adresa=adresa,
                telefon=telefon, email=email,
            )
            records.append(((bm, func_s), person))
    finally:
        wb.close()
    return records, issues


def _write_xlsx_export(
    persons: list[Person],
    oik: OikConstants,
    out_path: Path,
    *,
    spec: WorkflowSpec | None = None,
) -> None:
    """Write the human-readable xlsx layout used for operator exports
    ("Извези", error-row export) — called via
    `master_io.export_master_xlsx()`, never for internal storage."""
    # Bug: this used to hardcode "Стални състав" regardless of which
    # workflow was actually being aggregated, so a prosireni run's own
    # zbirana_tabela_prosireni.xlsx showed a "Стални састав" title/sheet
    # name inside a correctly-separate file -- looked like the file
    # "belonged to" stalni even though it never was.
    if spec is None:
        spec = STALNI_SPEC
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{spec.name_sr} БО"

    # Title
    ws.merge_cells("A1:N1")
    title = ws["A1"]
    title.value = f"{spec.name_sr} бирачких одбора — Збирна табела"
    title.font = Font(name="Arial", bold=True, size=14, color="2F5496")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    headers = [
        ("Р.бр.", 6), ("БМ бр.", 7), ("Гласачко место", 35),
        ("Функција", 22), ("Име", 16), ("Презиме", 18), ("ЈМБГ", 16),
        ("Место пребивалишта", 22), ("Адреса пребивалишта", 28),
        ("Број телефона", 18), ("Е-пошта", 28),
        ("Предлагач", 12), ("Статус", 10), ("Именовао начелник", 16),
    ]
    for col_idx, (h_name, h_width) in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col_idx, value=h_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = h_width

    prev_bm: int | None = None
    filled = 0
    jmbg_cells: list[str] = []
    for row_idx, p in enumerate(persons):
        row = row_idx + 3
        if spec.slug == "prosireni":
            # slot_rbr() assumes stalni's fixed 6-role-per-BM roster
            # (func_idx falls back to the SAME value -- len(FUNCTIONS)
            # -- for every unrecognized function string), so every
            # prosireni slot in a BM collided on an identical Р.бр.
            # `persons` is already sorted into stable (bm, role) order
            # above, so a plain sequential counter is a correct global
            # UID here too -- same reasoning as generate_entity_files'
            # "Row numbers are sequential (not slot_rbr-based)".
            rb = row_idx + 1
        else:
            rb = slot_rbr(p.bm_number, p.function)  # global UID — matches per-party files
        station = oik.station_by_bm(p.bm_number) or PollingStation(
            bm_number=p.bm_number, full_name=f"БМ бр. {p.bm_number}"
        )
        sep = prev_bm is not None and p.bm_number != prev_bm
        border = BM_SEPARATOR_BORDER if sep else THIN_BORDER
        prev_bm = p.bm_number

        is_filled = p.is_filled
        if is_filled:
            filled += 1

        values = [
            rb, p.bm_number, station.full_name or station.name, p.function,
            p.first_name, p.last_name, p.jmbg, p.mesto, p.adresa,
            p.telefon, p.email, p.party, "✓" if is_filled else "—",
            "Да" if p.appointed_by_nacelnik else "",
        ]
        for col_idx, val in enumerate(values, 1):
            c = safe_cell(ws, row, col_idx, val)
            c.font = Font(name="Arial", size=10)
            c.border = border
            c.alignment = Alignment(vertical="center", wrap_text=(col_idx == 3))
            if col_idx == 7:  # ЈМБГ column (post-split)
                c.number_format = "@"
                jmbg_cells.append(c.coordinate)
            if col_idx == 13:  # Статус column
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.fill = VALID_FILL if is_filled else INVALID_FILL

    # JMBG visual MOD 11 feedback on the master too — same red/green treatment
    # as the per-party files so the user can spot bad entries at a glance.
    for coord in jmbg_cells:
        formula = jmbg_mod.excel_validation_formula(coord).lstrip("=")
        ws.conditional_formatting.add(
            coord,
            FormulaRule(
                formula=[f'=AND({coord}<>"",NOT({formula}))'],
                fill=INVALID_FILL,
            ),
        )
        ws.conditional_formatting.add(
            coord,
            FormulaRule(
                formula=[f'=AND({coord}<>"",{formula})'],
                fill=VALID_FILL,
            ),
        )

    ws.freeze_panes = "E3"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = "2:2"

    # Stats sheet
    ws_stats = wb.create_sheet("Статистика")
    ws_stats["A1"], ws_stats["B1"] = "Укупно позиција", len(persons)
    ws_stats["A2"], ws_stats["B2"] = "Попуњено", filled
    ws_stats["A3"], ws_stats["B3"] = "Непопуњено", len(persons) - filled
    for r in range(1, 4):
        ws_stats.cell(row=r, column=1).font = Font(name="Arial", bold=True, size=11)
    ws_stats.column_dimensions["A"].width = 22
    ws_stats.column_dimensions["B"].width = 12

    wb.save(out_path)
    wb.close()
