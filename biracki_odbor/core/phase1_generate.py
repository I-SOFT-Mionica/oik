"""Phase 1: generate one locked .xlsx per party for filling in members.

Refactored from legacy bo_system.py:generate_party_files. Differences:
  - Polling-station data comes from OikConstants, NOT the template's
    'bm' sheet (template can omit it).
  - Lock password comes from OikConstants, not hard-coded.
  - JMBG MOD 11 formula generated via biracki_odbor.core.jmbg.
  - Returns a ValidationReport with per-BM warnings (unknown BM, etc.)
    instead of printing to stdout.
  - Caller-supplied progress callback for GUI feedback.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import openpyxl
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Protection, Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import PageSetupProperties

from biracki_odbor.config.candidacies import CandidaciesRegistry
from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core.xlsx_safety import safe_cell
from biracki_odbor.core.models import (
    FUNCTIONS,
    Allocation,
    Issue,
    PollingStation,
    ValidationReport,
    slot_rbr,
)
from biracki_odbor.core.template import read_template
from biracki_odbor.validation.reports import Codes, message


# Hidden cell holding the file-identity marker; see popunjeni_io.
MARKER_CELL = "M1"
MARKER_COLUMN_LETTER = "M"

# Visible paste-resistant validity column ("Провера"). Each data row gets a
# locked formula cell that reads the JMBG and emits "✓" / "✗". Because the
# cell is locked, sheet protection blocks Excel's paste-clear behavior that
# wipes the JMBG column's own data validation + conditional formatting — so
# even after a user pastes 18 JMBGs from a CRM and unintentionally erases
# the green/red feedback on column G, column N stays accurate.
VALIDITY_COLUMN_LETTER = "N"
VALIDITY_COLUMN_INDEX = 14
VALIDITY_HEADER = "Провера"


def build_marker(
    election_uuid: str,
    party_safe_name: str,
    run_ts: int = 0,
    election_epoch: int = 0,
) -> str:
    """Stamp inside Phase 1 .xlsx that lets Phase 2 import recognize the file.

    Base format:    BO/<election_uuid>/<party_safe_name>
    Extended format: BO/<election_uuid>/<party_safe_name>/<run_ts>/<election_epoch>

    The extended format is written when run_ts > 0. Phase 2 import uses it to
    reject files from a previous generation run within the same cycle (e.g.
    after "Поништи и поново генериши"). Old-format files (no run_ts) are still
    accepted — Phase 2 skips the generation check when run_ts is absent.

    Components:
      election_uuid  — scopes file to a single election cycle
      party_safe_name — canonical party/entity filename stem
      run_ts         — Unix epoch of the first Phase 1 run; fixed for normal
                       re-runs, advanced only on explicit invalidation
      election_epoch — Unix epoch of election day at 07:00 local time (polls open)
    """
    base = f"BO/{election_uuid}/{party_safe_name}"
    if run_ts:
        return f"{base}/{run_ts}/{election_epoch}"
    return base


def election_epoch_from_election(election: ElectionConfig | None) -> int:
    """Return Unix epoch of election day at 07:00 local time, or 0 if unknown."""
    if election is None:
        return 0
    from datetime import datetime
    from biracki_odbor.config import declension
    parsed = declension.parse_serbian_date(election.election.dates.date_full)
    if parsed is None:
        return 0
    y, m, d = parsed
    return int(datetime(y, m, d, 7, 0, 0).timestamp())


# ── Styles ──────────────────────────────────────────────────────────────

HEADER_FILL = PatternFill("solid", fgColor="2F5496")
HEADER_FONT = Font(name="Arial", bold=True, size=10, color="FFFFFF")
LOCKED_FILL = PatternFill("solid", fgColor="D9E2F3")
LOCKED_FONT = Font(name="Arial", size=10, color="2F5496")
INPUT_FILL = PatternFill("solid", fgColor="FFFFFF")
INPUT_FONT = Font(name="Arial", size=10)
INVALID_FILL = PatternFill("solid", fgColor="FFC7CE")
VALID_FILL = PatternFill("solid", fgColor="C6EFCE")
# Excel "Good / Bad / Neutral" font colors paired with the fills above
# for legible contrast across the three CF states on A:D rows + N column.
# Each pair is a known-WCAG-tested combination (it's the same palette
# Excel ships under Home → Conditional Formatting → Color Scales).
EMPTY_FONT_COLOR = "2F5496"    # dark blue on LOCKED_FILL (#D9E2F3)
VALID_FONT_COLOR = "006100"    # dark green on VALID_FILL (#C6EFCE)
INVALID_FONT_COLOR = "9C0006"  # dark red on INVALID_FILL (#FFC7CE)
THIN_BORDER = Border(
    left=Side(style="thin", color="8DB4E2"),
    right=Side(style="thin", color="8DB4E2"),
    top=Side(style="thin", color="8DB4E2"),
    bottom=Side(style="thin", color="8DB4E2"),
)
BM_SEPARATOR_BORDER = Border(
    left=Side(style="thin", color="8DB4E2"),
    right=Side(style="thin", color="8DB4E2"),
    top=Side(style="medium", color="2F5496"),
    bottom=Side(style="thin", color="8DB4E2"),
)

INPUT_COLUMNS = [
    ("Име", 16),
    ("Презиме", 18),
    ("ЈМБГ", 16),
    ("Место пребивалишта", 22),
    ("Адреса пребивалишта", 28),
    ("Број телефона", 18),
    ("Е-пошта", 28),
]


@dataclass
class Phase1Result:
    files_written: list[Path]
    report: ValidationReport


_MAX_FILENAME_STEM = 80  # keeps output_dir/{stem}.xlsx well under Windows' 260-char MAX_PATH


def _safe_filename(name: str) -> str:
    """Sanitize `name` for use as a filename stem.

    Allowlist, not denylist: the well-known Windows-illegal characters
    (: " * ? < > | \\ /) aren't the only way to break a filename — a
    literal embedded newline (e.g. pasted from a long, multi-line
    election-list name copied verbatim from an official document) is
    just as fatal to `wb.save()`, and easy to miss enumerating one
    character at a time. Also caps length: an operator-entered full
    name can run past 300 characters, which alone can exceed Windows'
    MAX_PATH once combined with a real output directory — confirmed by
    direct reproduction, not theoretical (see test_xlsx_safety.py).
    """
    cleaned = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    cleaned = re.sub(r"[ _]+", "_", cleaned).strip("_")
    return (cleaned or "странка")[:_MAX_FILENAME_STEM]


def _station_or_placeholder(
    bm_number: int,
    oik: OikConstants,
) -> tuple[PollingStation, list[Issue]]:
    """Look up by BM number; if missing, return (placeholder, [warning Issue])."""
    ps = oik.station_by_bm(bm_number)
    if ps is None:
        issue = Issue(
            code=Codes.BM_UNKNOWN,
            message_sr=message(Codes.BM_UNKNOWN, row=bm_number),
            severity="warning",
            row=bm_number, detail=str(bm_number),
        )
        placeholder = PollingStation(
            bm_number=bm_number, name="", address="",
            full_name=f"БМ бр. {bm_number}",
        )
        return placeholder, [issue]
    return ps, []


def generate_party_files(
    template_path: Path | str,
    output_dir: Path | str,
    oik: OikConstants,
    progress: Callable[[str, int, int], None] | None = None,
    max_workers: int | None = None,
    election: ElectionConfig | None = None,
    demo_mode: bool = False,
    run_ts: int = 0,
) -> Phase1Result:
    """Generate one locked .xlsx per party.

    Args:
      template_path: Stalni_sastav.xlsx (must contain 'Raspodela' sheet).
      output_dir: directory to write party files into (created if absent).
      oik: source of polling-station info and lock password.
      progress: optional callback `progress(party_name, idx, total)`.
      max_workers: process-pool size. None → min(4, cpu_count). Pass 1
        for an in-process sequential path (used in tests).
      election: when provided, each output .xlsx is stamped with a
        hidden+locked identity marker (cell M1) tying it to this election
        cycle's `election_uuid`. Phase 2 import refuses unmarked files.
        Optional for legacy callers and tests.
      demo_mode: when True (= no/invalid license), restrict the output to
        slots from a SINGLE polling station — the one with the lowest
        bm_number. Files are still written for every party but each
        contains only that one BM's slots. Lets prospective customers
        exercise the full flow end-to-end without unlocking production
        usage. A `DEMO_MODE_LIMIT` info-level issue surfaces on the
        report so the GUI can echo the limit.

    Returns Phase1Result with file paths + accumulated report.
    """
    import logging
    import os
    log = logging.getLogger(__name__)

    report = ValidationReport()
    template_data, t_report = read_template(template_path)
    report.extend(t_report)
    if not report.ok:
        return Phase1Result([], report)

    allocations = list(template_data.allocations)
    if demo_mode and allocations:
        # Pick a single BM — the lowest bm_number for reproducibility.
        # Restrict every party's slots to that BM. Files still get
        # generated for every party so the operator sees the full
        # parties.xlsx shape, just with one row of slots per file.
        demo_bm = min(a.bm_number for a in allocations)
        allocations = [a for a in allocations if a.bm_number == demo_bm]
        report.add(Issue(
            code=Codes.DEMO_MODE_LIMIT,
            message_sr=message(Codes.DEMO_MODE_LIMIT, row=demo_bm),
            severity="info",
            row=demo_bm,
        ))
        log.warning(
            "generate_party_files: DEMO mode active — limiting output"
            " to BM %d (%d slots out of %d in template)",
            demo_bm, len(allocations), len(template_data.allocations),
        )

    # Group allocations by party.
    by_party: dict[str, list[Allocation]] = {}
    func_order = {f: i for i, f in enumerate(FUNCTIONS)}
    for alloc in allocations:
        by_party.setdefault(alloc.party, []).append(alloc)
    for slots in by_party.values():
        slots.sort(key=lambda a: (a.bm_number, func_order.get(a.function, 99)))

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    parties_sorted = sorted(by_party.keys())
    total = len(parties_sorted)
    if max_workers is None:
        max_workers = min(4, os.cpu_count() or 2)
    log.info(
        "generate_party_files: %d parties to produce (max_workers=%d)",
        total, max_workers,
    )

    election_uuid = (election.election_uuid.strip() if election else "")
    ep = election_epoch_from_election(election) if run_ts else 0
    combined_name_header = bool(election and election.combined_name_header)
    tasks = [
        (
            party, by_party[party], oik,
            out / f"{_safe_filename(party)}.xlsx",
            election_uuid,
            run_ts,
            ep,
            "Стални састав бирачких одбора",
            None,
            None,
            combined_name_header,
        )
        for party in parties_sorted
    ]

    files_written: list[Path] = []

    # Process pool startup is ~300 ms on Windows; each party file is ~100 ms.
    # Below ~6 parties the pool is a net loss.
    if max_workers <= 1 or total < 6:
        for idx, args in enumerate(tasks, start=1):
            party, file_path = args[0], args[3]
            issues = _write_party_workbook(*args)
            for issue in issues:
                report.add(issue)
            files_written.append(file_path)
            if progress:
                progress(party, idx, total)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            future_to_args = {
                pool.submit(_write_party_workbook, *args): args
                for args in tasks
            }
            for idx, fut in enumerate(as_completed(future_to_args), start=1):
                args = future_to_args[fut]
                party, file_path = args[0], args[3]
                issues = fut.result()
                for issue in issues:
                    report.add(issue)
                files_written.append(file_path)
                if progress:
                    progress(party, idx, total)

    files_written.sort()
    log.info("generate_party_files: %d files written", len(files_written))
    return Phase1Result(files_written, report)


def _write_party_workbook(
    party: str,
    slots: list[Allocation],
    oik: OikConstants,
    file_path: Path,
    election_uuid: str = "",
    run_ts: int = 0,
    election_epoch: int = 0,
    title_prefix: str = "Стални састав бирачких одбора",
    rbr_list: list[int] | None = None,
    display_name: str | None = None,
    combined_name_header: bool = False,
) -> list[Issue]:
    """Module-level worker; returns the list of Issues raised while writing.

    When `election_uuid` is non-empty, writes the compound identity marker to
    cell `MARKER_CELL` and hides column `MARKER_COLUMN_LETTER`. Phase 2 import
    refuses files without a valid marker; when run_ts > 0 it also rejects files
    from a different generation run within the same cycle.

    `title_prefix` customises the D1 cell title (default: stalni text).
    `rbr_list` overrides the per-row Р.бр. values — pass when slot_rbr is
    not meaningful (e.g. prosireni files with compound function strings).
    When None, slot_rbr(bm, function) is used (stalni default).

    `party` is an operational key (stalni: party abbreviation; prosireni:
    entity_id) — it's what gets locked into the Предлагач column on every
    row and folded into the hidden identity marker, so it must stay short
    (Windows path limits, Thunderbird subject/search handling). `display_name`
    is the human-readable label shown ONLY in the D1 title; defaults to
    `party` when not given, so stalni callers (which already pass a short
    abbreviation) are unaffected.

    `combined_name_header` genuinely merges the Име/Презиме cells (E:F)
    into one real input box per row, matching official forms that list
    "Име и презиме" as a single field. popunjeni_io.parse_party_file
    detects the shape from the file itself (F3 blank) and splits the
    typed text back into first/last name on import — 2 words auto-split
    cleanly; 3+ words can't be split unambiguously and are flagged
    (NAME_AMBIGUOUS_SPLIT) for a manual fix in Корекције rather than
    guessed at. Explicitly accepted tradeoff, not an oversight.
    """
    issues: list[Issue] = []
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Подаци"

    # Row 1: 3-cell summary block (cols A:C) + title (merged D1:L1).
    # Row 2: matching numeric/formula values (cols A:C) + instructions
    # (merged D2:L2). Layout chosen so the operator sees the count of
    # filled slots and invalid JMBGs at the top of the file — previously
    # this block lived at the bottom, easy to miss after a paste op.
    # Marker cell M1 sits outside the D:L merge (column M is hidden).
    summary_label_font = Font(name="Arial", bold=True, size=10, color="2F5496")
    summary_value_font = Font(name="Arial", bold=True, size=11, color="2F5496")
    for col_idx, label in enumerate(("Укупно", "Попуњени", "Неисправни"), 1):
        c = ws.cell(row=1, column=col_idx, value=label)
        c.font = summary_label_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = HEADER_FILL
        c.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        c.border = THIN_BORDER
    ws.column_dimensions["A"].width = 11
    ws.column_dimensions["B"].width = 11
    ws.column_dimensions["C"].width = 12

    # Title sits in the empty D:L stretch of row 1. Uses the human-readable
    # display_name (falls back to `party` for stalni, whose `party` already
    # is the short-but-readable abbreviation) — entity full names can be
    # long, so shrink_to_fit keeps them from clipping instead of wrapping
    # into the merged cell's fixed 30px row height.
    ws.merge_cells("D1:L1")
    ws["D1"] = f"{title_prefix} — {display_name if display_name is not None else party}"
    ws["D1"].data_type = "s"  # never let a leading =/+/-/@ in display_name/party become a formula
    ws["D1"].font = Font(name="Arial", bold=True, size=14, color="2F5496")
    ws["D1"].alignment = Alignment(horizontal="center", vertical="center", shrink_to_fit=True)
    ws.row_dimensions[1].height = 30

    # Instructions in D2:L2; A2:C2 holds the actual summary values (filled
    # in below once `last_data_row` is known).
    ws.merge_cells("D2:L2")
    ws["D2"] = (
        "Попуните БЕЛЕ ћелије. Плаве ћелије су закључане. "
        "ЈМБГ мора имати 13 цифара и проћи MOD 11 проверу (зелено = исправно)."
    )
    ws["D2"].font = Font(name="Arial", size=9, italic=True, color="666666")
    ws["D2"].alignment = Alignment(horizontal="center")

    # Header row (row 3)
    # `None` placeholder keeps column M (the hidden marker column) out of the
    # header row but preserves enumerate-based column indexing — so Провера
    # actually lands at column N (14), not M (13).
    # Official forms list "Име и презиме" as one field — `combined_name_
    # header` genuinely merges the Име/Презиме cells (E:F) into one input
    # box per row, matching that. Chosen deliberately over reshuffling the
    # whole column layout: G (ЈМБГ), J (phone), the hidden marker column
    # and every DataValidation/CF formula below stay exactly where they
    # are, since only E/F's own meaning changes — see
    # popunjeni_io.parse_party_file for the matching read side (detects
    # this shape from F3 being blank, not from the live election
    # setting, so an older split-column file always still parses as
    # split). Known, accepted loss: a submitted name of 3+ words can't
    # be auto-split into first/last — parse_party_file flags those with
    # NAME_AMBIGUOUS_SPLIT for a manual fix in Корекције.
    input_headers = list(INPUT_COLUMNS)
    if combined_name_header:
        input_headers[0] = ("Име и презиме", input_headers[0][1])
        input_headers[1] = (None, input_headers[1][1])
    headers = (
        [("Р.бр.", 6), ("БМ бр.", 7), ("Гласачко место", 35), ("Функција", 22)]
        + input_headers
        + [("Предлагач", 12), (None, 0), (VALIDITY_HEADER, 9)]
    )
    for col_idx, (h_name, h_width) in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = h_width
        if h_name is None:
            continue
        cell = ws.cell(row=3, column=col_idx, value=h_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        cell.protection = Protection(locked=True)
    if combined_name_header:
        ws.merge_cells("E3:F3")
    ws.row_dimensions[3].height = 28

    # Data rows
    jmbg_cells: list[str] = []
    prev_bm: int | None = None
    for data_idx, slot in enumerate(slots):
        row = data_idx + 4
        ps, ps_issues = _station_or_placeholder(slot.bm_number, oik)
        issues.extend(ps_issues)
        use_sep = prev_bm is not None and slot.bm_number != prev_bm
        border = BM_SEPARATOR_BORDER if use_sep else THIN_BORDER
        prev_bm = slot.bm_number

        rbr = rbr_list[data_idx] if rbr_list is not None else slot_rbr(slot.bm_number, slot.function)
        locked = [
            (1, rbr),
            (2, slot.bm_number),
            (3, ps.full_name or ps.name),
            (4, slot.function),
        ]
        for col, val in locked:
            c = safe_cell(ws, row, col, val)
            # Cols 1-4 (Р.бр., БМ, Гласачко место, Функција) get their
            # appearance entirely from CF rules below (empty/✓/✗ states).
            # NO static fill/font here — an explicit PatternFill on the
            # cell blocks Excel from fully repainting via the CF
            # DifferentialStyle, which was the v0.5.0 bug.
            c.border = border
            c.alignment = Alignment(vertical="center", wrap_text=(col == 3))
            c.protection = Protection(locked=True)

        for input_idx in range(7):
            col = input_idx + 5
            c = ws.cell(row=row, column=col)
            c.font = INPUT_FONT
            c.fill = INPUT_FILL
            c.border = border
            c.alignment = Alignment(vertical="center")
            c.protection = Protection(locked=False)
            if col == 7:  # JMBG column G (after Име/Презиме split)
                c.number_format = "@"
                jmbg_cells.append(c.coordinate)
            elif col == 10:  # Phone column J — force text so 064… keeps its 0
                c.number_format = "@"

        if combined_name_header:
            # One real input box per row — F only ever holds the
            # top-left (E) cell's value once merged, matching the
            # header. Styled like any other cell above before merging;
            # the merge itself doesn't need re-styling.
            ws.merge_cells(f"E{row}:F{row}")

        c = safe_cell(ws, row, 12, party)
        c.font = LOCKED_FONT
        c.fill = LOCKED_FILL
        c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.protection = Protection(locked=True)

        # Paste-resistant validity cell. Formula reads JMBG in column G of
        # this row and emits "✓" / "✗" / "" (empty when JMBG is blank).
        # `hidden=True` keeps the formula bar empty when the cell is
        # selected — party clerks can see the symbol but not the math.
        jmbg_ref = f"G{row}"
        jmbg_check = jmbg_mod.excel_validation_formula(jmbg_ref).lstrip("=")
        c = ws.cell(
            row=row, column=VALIDITY_COLUMN_INDEX,
            value=f'=IF({jmbg_ref}="","",IF({jmbg_check},"✓","✗"))',
        )
        c.font = LOCKED_FONT
        c.fill = LOCKED_FILL
        c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.protection = Protection(locked=True, hidden=True)

    last_data_row = len(slots) + 3

    # JMBG validation: hard block on bad MOD 11 / wrong length via DataValidation,
    # plus red/green conditional formatting for at-a-glance feedback while typing.
    if jmbg_cells:
        first_jmbg_cell = "G4"
        check = jmbg_mod.excel_validation_formula(first_jmbg_cell).lstrip("=")
        dv = DataValidation(
            type="custom",
            formula1=f'OR({first_jmbg_cell}="",{check})',
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Неисправан ЈМБГ",
            error=(
                "ЈМБГ мора имати тачно 13 цифара и проћи MOD 11 проверу."
                " Проверите цифре пре поновног уноса."
            ),
            showInputMessage=True,
            promptTitle="ЈМБГ",
            prompt="Унесите 13-цифрени ЈМБГ (без размака и црта).",
        )
        dv.add(f"G4:G{last_data_row}")
        ws.add_data_validation(dv)

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

    # Paste-resistant CF on the validity column. CF on locked cells is
    # preserved across paste operations into the JMBG column, so the
    # red/green visual stays even if the user breaks the JMBG column's
    # own CF via Paste/Paste-Values.
    #
    # Font is paired with fill on each rule so the ✓/✗ glyph stays
    # legible (and not jarring) against the green/red background —
    # dark-blue glyph on light-green looked muddy in field testing.
    if jmbg_cells:
        validity_range = (
            f"{VALIDITY_COLUMN_LETTER}4:"
            f"{VALIDITY_COLUMN_LETTER}{last_data_row}"
        )
        ws.conditional_formatting.add(
            validity_range,
            FormulaRule(
                formula=[f'={VALIDITY_COLUMN_LETTER}4="✓"'],
                fill=VALID_FILL,
                font=Font(name="Arial", size=10, bold=True,
                          color=VALID_FONT_COLOR),
            ),
        )
        ws.conditional_formatting.add(
            validity_range,
            FormulaRule(
                formula=[f'={VALIDITY_COLUMN_LETTER}4="✗"'],
                fill=INVALID_FILL,
                font=Font(name="Arial", size=10, bold=True,
                          color=INVALID_FONT_COLOR),
            ),
        )

    # Phone validation: digits only, at least 6 long, starts with "0"
    # (Serbian mobile/landline both begin with 0, e.g. 064xxx, 011xxx).
    # ISNUMBER(VALUE(J4)) is true iff the string can be parsed as a number
    # — coercion fails on letters/dashes/spaces. The number_format="@" on
    # the cell preserves the leading zero as a string for storage.
    dv_phone = DataValidation(
        type="custom",
        formula1='=AND(LEN(J4)>=6,ISNUMBER(VALUE(J4)),LEFT(J4,1)="0")',
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Број телефона",
        error=(
            "Број телефона мора садржати само цифре, почети нулом (нпр. 064...) "
            "и имати најмање 6 цифара."
        ),
    )
    dv_phone.add(f"J4:J{last_data_row}")
    ws.add_data_validation(dv_phone)

    # Sentence-case data validation for Име and Презиме — warning-style
    # (not blocking), since paste-from-CRM may legitimately introduce
    # already-capitalized values. EXACT vs PROPER catches "marko" /
    # "MARKO PETROVIĆ" / "petrović" lowercase typos. The CF rule below
    # adds a visual flag for the paste-bypass case.
    dv_name = DataValidation(
        type="custom",
        formula1='=EXACT(E4,PROPER(E4))',
        allow_blank=True,
        showErrorMessage=True,
        errorStyle="warning",
        errorTitle="Капитализација имена",
        error=(
            'Прво слово сваке речи треба да буде велико,'
            ' остала мала (нпр. „Марко", „Ана Марија").'
        ),
    )
    dv_name.add(f"E4:E{last_data_row}")
    ws.add_data_validation(dv_name)

    # F is merged away under combined_name_header (see the header-row
    # comment above) — no separate Презиме cell exists to validate.
    name_cols = (("E", "E4"),) if combined_name_header else (("E", "E4"), ("F", "F4"))
    if not combined_name_header:
        dv_lastname = DataValidation(
            type="custom",
            formula1='=EXACT(F4,PROPER(F4))',
            allow_blank=True,
            showErrorMessage=True,
            errorStyle="warning",
            errorTitle="Капитализација презимена",
            error=(
                'Прво слово презимена треба да буде велико,'
                ' остала мала (нпр. „Петровић").'
            ),
        )
        dv_lastname.add(f"F4:F{last_data_row}")
        ws.add_data_validation(dv_lastname)

    # CF on Име / Презиме: yellow background when capitalization is off.
    # Caught at paste time (DV doesn't fire on paste; CF does).
    for col_letter, first_cell in name_cols:
        ws.conditional_formatting.add(
            f"{col_letter}4:{col_letter}{last_data_row}",
            FormulaRule(
                formula=[f'=AND({first_cell}<>"",NOT(EXACT({first_cell},PROPER({first_cell}))))'],
                fill=PatternFill("solid", fgColor="FFEB9C"),
            ),
        )

    # Email validation: must contain "@" and a "." after it, length ≥ 5.
    # Excel has no native regex, but the SEARCH-based composition handles
    # the basic shape of a real address ("a@b.c") while staying permissive
    # of legitimate addresses with subdomains and unusual TLDs.
    dv_email = DataValidation(
        type="custom",
        formula1=(
            '=AND(ISNUMBER(SEARCH("@",K4)),'
            'ISNUMBER(SEARCH(".",K4,SEARCH("@",K4))),'
            'LEN(K4)>=5)'
        ),
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Неисправна е-пошта",
        error="Е-пошта мора садржати знак @ и тачку после њега (нпр. ime@example.com).",
    )
    dv_email.add(f"K4:K{last_data_row}")
    ws.add_data_validation(dv_email)

    # CF on the row's identification columns (A:D) — blue when JMBG is
    # empty (locked-context cue), green when it passes, red when it fails.
    # Whole rows are scannable at a glance.
    #
    # Per-row CF with fully-absolute references. Earlier attempts used a
    # single range-wide rule with `$N4` (v0.3.1) and then `INDIRECT(...)`
    # (v0.4.0) hoping Excel's relative-reference adjustment would walk
    # the rows. Both failed in the field — Excel either anchored every
    # row to N4 or didn't evaluate INDIRECT in CF reliably. Per-row rules
    # with `=$N$5="✓"` for row 5, `=$N$6="✓"` for row 6, etc. eliminate
    # every avenue for ambiguity.
    #
    # Three rules per row (empty / ✓ / ✗). The empty-state rule paints
    # the "locked-context blue" — A:D cells have NO static fill (see the
    # locked-cells loop above), so without this rule those cells would
    # render as plain white when JMBG is empty. Driving all three states
    # from CF (no static fill underneath) is what made v0.5.1's green/red
    # tinting actually display — in v0.5.0 the static LOCKED_FILL blocked
    # openpyxl's DifferentialStyle from fully repainting.
    #
    # Font is paired with fill on each state so dark-blue text never
    # ends up on a green/red background (low-contrast and visually
    # jarring). Palette is Excel's "Good / Bad / Neutral" standard.
    #
    # Cost: 3 rules × N data rows per file (~420 for a typical 140-slot
    # party file) — well within Excel's CF rule limits.
    if jmbg_cells:
        empty_font = Font(name="Arial", size=10, bold=True,
                          color=EMPTY_FONT_COLOR)
        valid_font = Font(name="Arial", size=10, bold=True,
                          color=VALID_FONT_COLOR)
        invalid_font = Font(name="Arial", size=10, bold=True,
                            color=INVALID_FONT_COLOR)
        for row_idx in range(4, last_data_row + 1):
            row_range = f"A{row_idx}:D{row_idx}"
            n_cell = f"${VALIDITY_COLUMN_LETTER}${row_idx}"
            ws.conditional_formatting.add(
                row_range,
                FormulaRule(formula=[f'={n_cell}=""'], fill=LOCKED_FILL,
                            font=empty_font),
            )
            ws.conditional_formatting.add(
                row_range,
                FormulaRule(formula=[f'={n_cell}="✓"'], fill=VALID_FILL,
                            font=valid_font),
            )
            ws.conditional_formatting.add(
                row_range,
                FormulaRule(formula=[f'={n_cell}="✗"'], fill=INVALID_FILL,
                            font=invalid_font),
            )

    # Fill in the top-of-sheet summary values (A2:C2) now that we know
    # `last_data_row`. Labels are in row 1; numeric/formula values in
    # row 2 line up under them.
    summary_value_font = Font(name="Arial", bold=True, size=11, color="2F5496")
    # A2 — Укупно (total slot count, a literal number)
    c = ws.cell(row=2, column=1, value=len(slots))
    c.font = summary_value_font
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = THIN_BORDER
    # B2 — Попуњени (COUNTA of the first-name column on data rows)
    c = ws.cell(row=2, column=2, value=f"=COUNTA(E4:E{last_data_row})")
    c.font = summary_value_font
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = THIN_BORDER
    # C2 — Неисправни (COUNTIF on the paste-resistant validity column).
    # Reads from column N so the count stays accurate even if the user
    # pastes JMBGs and wipes the CF/DV on column G.
    c = ws.cell(
        row=2, column=3,
        value=(
            f'=COUNTIF({VALIDITY_COLUMN_LETTER}4:'
            f'{VALIDITY_COLUMN_LETTER}{last_data_row},"✗")'
        ),
    )
    c.font = summary_value_font
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = THIN_BORDER

    # Identity marker (hidden + locked) for Phase 2 import recognition.
    # Column M sits past the visible data columns; hiding it keeps the layout
    # clean. Locking it (and the sheet protection below) prevents party-side
    # tampering — they'd have to break the password to edit it.
    if election_uuid:
        safe_party = _safe_filename(party)
        marker_cell = ws[MARKER_CELL]
        marker_cell.value = build_marker(election_uuid, safe_party, run_ts, election_epoch)
        # locked AND hidden — sheet protection blocks edits; hidden empties
        # the formula bar so even if the user selects M1 they don't see
        # the UID string. Combined with formatColumns=True (locked) below,
        # this means the marker can't be unhidden in the UI either.
        marker_cell.protection = Protection(locked=True, hidden=True)
        ws.column_dimensions[MARKER_COLUMN_LETTER].hidden = True

    # Freeze + protection + print setup.
    #
    # OOXML semantics for sheetProtection bool attrs are *inverted* from
    # the previous version of this code: `True` means the action is
    # LOCKED (user can't do it), `False` means the action is allowed.
    # We want users to fill data cells but nothing else — no formatting
    # changes, no column unhide (which would reveal the marker), no
    # structural edits.
    ws.freeze_panes = "E4"
    ws.protection.sheet = True
    ws.protection.password = oik.lock_password
    # Block all formatting + structural edits.
    ws.protection.formatCells = True
    ws.protection.formatColumns = True   # also blocks "Unhide column"
    ws.protection.formatRows = True
    ws.protection.insertColumns = True
    ws.protection.insertRows = True
    ws.protection.deleteColumns = True
    ws.protection.deleteRows = True
    ws.protection.pivotTables = True
    ws.protection.objects = True
    ws.protection.scenarios = True
    # Sort + autoFilter stay allowed for usability (party can sort by БМ,
    # filter to see only their assigned slots).
    ws.protection.sort = False
    ws.protection.autoFilter = False
    # Both lock-states selectable so the user can read the prefilled
    # context (БМ, function, party) without having to break protection.
    ws.protection.selectLockedCells = False
    ws.protection.selectUnlockedCells = False

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = "3:3"

    wb.save(file_path)
    wb.close()
    return issues


# ── Проширени састав — entity file generation ─────────────────────────


def generate_entity_files(
    registry: CandidaciesRegistry,
    bm_numbers: list[int],
    output_dir: Path | str,
    oik: OikConstants,
    progress: Callable[[str, int, int], None] | None = None,
    election: ElectionConfig | None = None,
    run_ts: int = 0,
    demo_mode: bool = False,
) -> Phase1Result:
    """Generate one locked .xlsx per canonical entity for the prošireni workflow.

    Analogous to `generate_party_files` but:
    - Source of slot structure: CandidaciesRegistry → build_prosireni_allocation()
    - One file per canonical entity (not per party abbreviation).
    - Row numbers are sequential (not slot_rbr-based).
    - Title row reads "Проширени састав бирачких одбора — <entity name>"
      (full display name — only the title; filename, the hidden identity
      marker, and the locked Предлагач column all use the short
      entity_id, same operational-key convention as stalni's party
      abbreviation. See build_prosireni_allocation's docstring).

    ProcessPoolExecutor is skipped: entity files are typically small (≤10
    entities × few BMs × 2 roles) so in-process sequential generation is
    fast enough and avoids pickle constraints on rbr_list.

    `demo_mode` — same restriction as `generate_party_files`: without it,
    prosireni had NO demo limit at all (field report), so a demo user
    could generate/collect a full committee for every BM through this
    workflow regardless of the stalni-side one-BM limit. Restricts every
    entity's file to the single lowest-numbered BM, same as stalni, so
    both workflows agree on which BM the trial covers.
    """
    import logging
    from biracki_odbor.core.prosireni_allocation import (
        build_prosireni_allocation, canonical_slots,
    )

    log = logging.getLogger(__name__)
    report = ValidationReport()

    allocations = build_prosireni_allocation(registry, bm_numbers)
    if not allocations:
        report.add(Issue(
            code=Codes.NO_ALLOCATIONS,
            message_sr="Нема ентитета у регистру кандидатура. Прво унесите ентитете у Избори → Кандидати.",
            severity="error",
        ))
        return Phase1Result([], report)

    if demo_mode and allocations:
        demo_bm = min(a.bm_number for a in allocations)
        allocations = [a for a in allocations if a.bm_number == demo_bm]
        report.add(Issue(
            code=Codes.DEMO_MODE_LIMIT,
            message_sr=message(Codes.DEMO_MODE_LIMIT, row=demo_bm),
            severity="info",
            row=demo_bm,
        ))
        log.warning(
            "generate_entity_files: DEMO mode active — limiting output"
            " to BM %d (%d slots)",
            demo_bm, len(allocations),
        )

    # Group by canonical entity_id (= Allocation.party).
    by_entity: dict[str, list[Allocation]] = {}
    for alloc in allocations:
        by_entity.setdefault(alloc.party, []).append(alloc)

    # entity_id -> full display name, for the D1 title only.
    name_by_id = {cs.entity.entity_id: cs.name for cs in canonical_slots(registry)}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    election_uuid = (election.election_uuid.strip() if election else "")
    ep = election_epoch_from_election(election) if run_ts else 0
    entities_sorted = sorted(by_entity.keys())
    total = len(entities_sorted)
    log.info("generate_entity_files: %d entities to produce", total)

    files_written: list[Path] = []
    PROSIRENI_TITLE = "Проширени састав бирачких одбора"

    for idx, entity_id in enumerate(entities_sorted, start=1):
        slots = by_entity[entity_id]
        rbr_list = list(range(1, len(slots) + 1))
        file_path = out / f"{_safe_filename(entity_id)}.xlsx"
        issues = _write_party_workbook(
            entity_id, slots, oik, file_path, election_uuid,
            run_ts, ep,
            title_prefix=PROSIRENI_TITLE,
            rbr_list=rbr_list,
            display_name=name_by_id.get(entity_id, entity_id),
            combined_name_header=bool(election and election.combined_name_header),
        )
        for issue in issues:
            report.add(issue)
        files_written.append(file_path)
        if progress:
            progress(name_by_id.get(entity_id, entity_id), idx, total)

    files_written.sort()
    log.info("generate_entity_files: %d files written", len(files_written))
    return Phase1Result(files_written, report)
