"""Excel template for načelnik committee appointments.

When a party misses the deadline or submits ineligible personnel the
OIK head (načelnik) fills every remaining empty slot.  This module
handles the Excel side of that workflow:

  export_nacelnik_template()  — writes an xlsx pre-filled with slot
                                 context; member-data columns are left
                                 blank for the načelnik to complete
  read_nacelnik_xlsx()        — reads back the completed file; returns
                                 (rows, errors) where a non-empty
                                 ``errors`` list means the file is
                                 unacceptable (missing slots, bad JMBGs)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Protection, Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core import phone as phone_mod
from biracki_odbor.core.models import Person, PollingStation, slot_rbr, split_combined_name
from biracki_odbor.core.phase1_generate import INPUT_COLUMNS as _PARTY_INPUT_COLUMNS
from biracki_odbor.core.xlsx_safety import safe_cell


# ── Style constants (mirror phase1_generate.py's palette exactly — this
# is the same kind of file, filled by a different assigning mechanism
# (chief appointment vs. party submission), and should look/behave like
# one rather than drifting into a third, bespoke convention.) ─────────

_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_LOCKED_FILL = PatternFill("solid", fgColor="D9E2F3")
_INPUT_FILL  = PatternFill("solid", fgColor="FFFFFF")
_INVALID_FILL = PatternFill("solid", fgColor="FFC7CE")
_VALID_FILL   = PatternFill("solid", fgColor="C6EFCE")
_NAME_CASE_FILL = PatternFill("solid", fgColor="FFEB9C")
_HEADER_FONT = Font(name="Arial", bold=True, size=10, color="FFFFFF")
_LOCKED_FONT = Font(name="Arial", size=10, color="2F5496")
_INPUT_FONT  = Font(name="Arial", size=10)
_EMPTY_FONT_COLOR   = "2F5496"
_VALID_FONT_COLOR   = "006100"
_INVALID_FONT_COLOR = "9C0006"
_THIN        = Side(style="thin", color="8DB4E2")
_THIN_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_SEP_BORDER  = Border(
    left=_THIN, right=_THIN,
    top=Side(style="medium", color="2F5496"), bottom=_THIN,
)

# Column layout
# Indices 0-3 (1-4 in Excel): locked context columns
# Indices 4-10 (5-11 in Excel): editable member-data columns
# Index 11 (12 in Excel): "Провера" — paste-resistant JMBG status.
#
# "Странка" (which party the slot was originally allocated to) was
# deliberately dropped — the chief fills a slot precisely because that
# party isn't submitting anyone for it, so showing the name here is at
# best noise and at worst reads as an instruction to coordinate with
# that party, which isn't the point of this workflow. "Р.бр." uses
# slot_rbr() — the same canonical (bm, function) -> number scheme as
# master.xlsx and every per-party workbook, so a slot has the same
# number across every file that lists it.
_LOCKED_COLS = ["Р.бр.", "БМ бр.", "БМ назив", "Функција"]
# Field report: this used to hardcode its own ("Ime", "Prezime", "JMBG",
# ...) Latin labels, mismatched against every other Cyrillic header in
# the same row ("Р.бр.", "Функција", "Провера", ...) and against the
# party-submission template's all-Cyrillic headers. Reusing
# phase1_generate.py's INPUT_COLUMNS directly is the actual fix, not
# just translating the strings separately here -- this is "the same
# kind of file... filled by a different assigning mechanism", per this
# module's own docstring, so it should share one source of truth for
# what the columns are called, not two lists that can drift apart again.
_INPUT_COLS  = [label for label, _width in _PARTY_INPUT_COLUMNS]
_VALIDITY_COL = "Провера"
_ALL_COLS    = _LOCKED_COLS + _INPUT_COLS + [_VALIDITY_COL]
# Pre-Провера shape (11 cols, always split Ime/Prezime) -- files already
# generated/handed to a chief before this change must still import; the
# Провера column is a UI-only aid (never parsed here), so its absence
# changes nothing about how a legacy row is read.
_LEGACY_ALL_COLS = _LOCKED_COLS + _INPUT_COLS
_N_LOCKED    = len(_LOCKED_COLS)  # 4
_JMBG_COL_IDX = _N_LOCKED + 3           # 7 — Ime, Prezime, JMBG
_TELEFON_COL_IDX = _N_LOCKED + 6        # 10
_VALIDITY_COL_IDX = len(_ALL_COLS)      # 12 (last column)

# Column widths in characters (one entry per column in _ALL_COLS order)
_COL_WIDTHS = [8, 8, 30, 24, 16, 18, 16, 22, 28, 16, 28, 9]

_HEADER_ROW  = 1
_INSTRUCT_ROW = 2
_DATA_START  = 3  # first actual data row (1-based)


# ── Public dataclass for one imported row ─────────────────────────────

@dataclass
class NacelnikRow:
    bm_number:  int
    function:   str
    first_name: str
    last_name:  str
    jmbg:       str
    mesto:      str
    adresa:     str
    telefon:    str
    email:      str
    row_number: int   # 1-based Excel row (for human-readable error messages)
    is_filled:  bool  # True when at least first_name or last_name is present


# ── Export ────────────────────────────────────────────────────────────

def export_nacelnik_template(
    empty_persons: list[Person],
    bm_stations: dict[int, PollingStation],
    out_path: Path,
    *,
    password: str = "",
    election: ElectionConfig | None = None,
) -> Path:
    """Write an xlsx with one row per empty slot.

    Locked (blue) columns: Р.бр., БМ бр., БМ назив, Функција.
    Editable (white) columns: Ime(/Prezime), JMBG, Mesto, Adresa, Telefon,
    E-posta. A locked "Провера" column shows a paste-resistant ✓/✗ read on
    each row's JMBG.

    This is the same kind of file as a party-submission workbook
    (core.phase1_generate.py) — just filled by a different assigning
    mechanism (chief appointment vs. party submission) — so it follows
    the exact same conventions: paste-resistant validity column + CF,
    capitalization/email checks, and `election.combined_name_header`
    (same election-level setting Поставке/Изборна already exposes for
    party files) rather than a third, bespoke layout.

    ``password`` should be the OIK lock password so the file is
    protected consistently with party-submission files. ``election``
    supplies `combined_name_header`; omit only for legacy callers/tests
    that don't care about the merged-name layout (defaults to split
    Ime/Prezime columns).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined_name = bool(election and election.combined_name_header)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Именовања"

    # Row 1 — column headers. Official forms list "Име и презиме" as one
    # field when combined_name is on — merges E:F (same shape and same
    # literal label as phase1_generate.py's headers), header text
    # blanked on the second cell so a glance at the merged box reads as
    # one field.
    headers = list(_ALL_COLS)
    if combined_name:
        headers[4] = "Име и презиме"
        headers[5] = None
    for col_idx, label in enumerate(headers, start=1):
        width = _COL_WIDTHS[col_idx - 1]
        ws.column_dimensions[get_column_letter(col_idx)].width = width
        if label is None:
            continue
        c = ws.cell(row=_HEADER_ROW, column=col_idx, value=label)
        c.font      = _HEADER_FONT
        c.fill      = _HEADER_FILL
        c.border    = _THIN_BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if combined_name:
        ws.merge_cells(start_row=_HEADER_ROW, start_column=5, end_row=_HEADER_ROW, end_column=6)
    ws.row_dimensions[_HEADER_ROW].height = 24

    # Row 2 — instructions (merged across all columns)
    last_col_letter = get_column_letter(len(_ALL_COLS))
    ws.merge_cells(f"A{_INSTRUCT_ROW}:{last_col_letter}{_INSTRUCT_ROW}")
    instr = ws.cell(row=_INSTRUCT_ROW, column=1,
                    value=(
                        "Попуните БЕЛЕ ћелије (Ime, Prezime, JMBG, ...). "
                        "СВИ слотови морају бити попуњени — непотпун фајл ће бити одбијен. "
                        "JMBG мора имати 13 цифара и проћи MOD 11 проверу. "
                        "Плаве ћелије су закључане — не мењати структуру фајла."
                    ))
    instr.font      = Font(name="Arial", size=9, italic=True, color="595959")
    instr.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    ws.row_dimensions[_INSTRUCT_ROW].height = 18

    # Data rows — one per empty slot, sorted by BM then function
    sorted_persons = sorted(empty_persons, key=lambda p: (p.bm_number, p.function))

    jmbg_cells: list[str] = []
    prev_bm: int | None = None
    for rel_idx, person in enumerate(sorted_persons):
        row_idx  = _DATA_START + rel_idx
        bm_name  = bm_stations.get(person.bm_number, PollingStation(person.bm_number)).name
        rbr      = slot_rbr(person.bm_number, person.function)
        locked   = [rbr, person.bm_number, bm_name, person.function]
        use_sep  = prev_bm is not None and person.bm_number != prev_bm
        border   = _SEP_BORDER if use_sep else _THIN_BORDER
        prev_bm  = person.bm_number

        for col_idx, val in enumerate(locked, start=1):
            c            = safe_cell(ws, row_idx, col_idx, val)
            # NO static fill/font here -- appearance comes entirely from
            # the row-level CF below (empty/valid/invalid states). A
            # static PatternFill blocks openpyxl's DifferentialStyle
            # from fully repainting the cell via CF (same lesson
            # documented in phase1_generate.py).
            c.border     = border
            c.protection = Protection(locked=True)
            c.alignment  = Alignment(vertical="center", wrap_text=(col_idx == 3))

        for col_idx in range(_N_LOCKED + 1, len(_ALL_COLS)):  # input cols, excl. Провера
            c            = ws.cell(row=row_idx, column=col_idx, value="")
            c.font       = _INPUT_FONT
            c.fill       = _INPUT_FILL
            c.border     = border
            c.protection = Protection(locked=False)
            c.alignment  = Alignment(vertical="center")
            # Same fix as the regular party-submission templates
            # (phase1_generate.py): without an explicit text format,
            # Excel treats a leading-zero JMBG/phone as a number and
            # silently drops the 0 the moment the chief types it in.
            if col_idx == _JMBG_COL_IDX:
                c.number_format = "@"
                jmbg_cells.append(c.coordinate)
            elif col_idx == _TELEFON_COL_IDX:
                c.number_format = "@"

        if combined_name:
            ws.merge_cells(start_row=row_idx, start_column=5, end_row=row_idx, end_column=6)

        # Паste-resistant validity cell -- locked + hidden formula that
        # reads this row's JMBG and shows ✓/✗/"" independent of whatever
        # happens to the JMBG column's own DataValidation/CF after a
        # paste (sheet protection blocks editing a locked cell, so a
        # Paste into the unlocked JMBG column can't touch this one).
        jmbg_ref = f"{get_column_letter(_JMBG_COL_IDX)}{row_idx}"
        jmbg_check = jmbg_mod.excel_validation_formula(jmbg_ref).lstrip("=")
        c = ws.cell(
            row=row_idx, column=_VALIDITY_COL_IDX,
            value=f'=IF({jmbg_ref}="","",IF({jmbg_check},"✓","✗"))',
        )
        c.border     = border
        c.alignment  = Alignment(horizontal="center", vertical="center")
        c.protection = Protection(locked=True, hidden=True)

    last_data_row = _DATA_START + len(sorted_persons) - 1 if sorted_persons else _DATA_START

    if jmbg_cells:
        jmbg_col = get_column_letter(_JMBG_COL_IDX)
        telefon_col = get_column_letter(_TELEFON_COL_IDX)
        first_jmbg_cell = f"{jmbg_col}{_DATA_START}"

        jmbg_check = jmbg_mod.excel_validation_formula(first_jmbg_cell).lstrip("=")
        dv_jmbg = DataValidation(
            type="custom",
            formula1=f'OR({first_jmbg_cell}="",{jmbg_check})',
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
        dv_jmbg.add(f"{jmbg_col}{_DATA_START}:{jmbg_col}{last_data_row}")
        ws.add_data_validation(dv_jmbg)

        # Red/green CF directly on the JMBG column (visible even without
        # typing through DataValidation, e.g. right after a paste).
        for coord in jmbg_cells:
            formula = jmbg_mod.excel_validation_formula(coord).lstrip("=")
            ws.conditional_formatting.add(
                coord,
                FormulaRule(formula=[f'=AND({coord}<>"",NOT({formula}))'], fill=_INVALID_FILL),
            )
            ws.conditional_formatting.add(
                coord,
                FormulaRule(formula=[f'=AND({coord}<>"",{formula})'], fill=_VALID_FILL),
            )

        first_telefon_cell = f"{telefon_col}{_DATA_START}"
        dv_telefon = DataValidation(
            type="custom",
            formula1=(
                f'AND(LEN({first_telefon_cell})>=6,'
                f'ISNUMBER(VALUE({first_telefon_cell})),'
                f'LEFT({first_telefon_cell},1)="0")'
            ),
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Број телефона",
            error=(
                "Број телефона мора садржати само цифре, почети нулом (нпр. 064...) "
                "и имати најмање 6 цифара."
            ),
        )
        dv_telefon.add(f"{telefon_col}{_DATA_START}:{telefon_col}{last_data_row}")
        ws.add_data_validation(dv_telefon)

        # Capitalization check on the name column(s) — warning-style
        # (not blocking), since a paste from a CRM may legitimately
        # already be capitalized. Sentence-case DV doesn't fire on
        # paste; the matching CF below does.
        name_cols = [("E", f"E{_DATA_START}")] if combined_name else [
            ("E", f"E{_DATA_START}"), ("F", f"F{_DATA_START}"),
        ]
        for col_letter, first_cell in name_cols:
            dv_name = DataValidation(
                type="custom",
                formula1=f'=EXACT({first_cell},PROPER({first_cell}))',
                allow_blank=True,
                showErrorMessage=True,
                errorStyle="warning",
                errorTitle="Капитализација имена",
                error=(
                    'Прво слово сваке речи треба да буде велико,'
                    ' остала мала (нпр. „Марко", „Ана Марија").'
                ),
            )
            dv_name.add(f"{col_letter}{_DATA_START}:{col_letter}{last_data_row}")
            ws.add_data_validation(dv_name)
            ws.conditional_formatting.add(
                f"{col_letter}{_DATA_START}:{col_letter}{last_data_row}",
                FormulaRule(
                    formula=[f'=AND({first_cell}<>"",NOT(EXACT({first_cell},PROPER({first_cell}))))'],
                    fill=_NAME_CASE_FILL,
                ),
            )

        # Email shape check: "@" followed by "." somewhere after it.
        email_col = get_column_letter(_N_LOCKED + 7)  # K — E-posta
        first_email_cell = f"{email_col}{_DATA_START}"
        dv_email = DataValidation(
            type="custom",
            formula1=(
                f'=AND(ISNUMBER(SEARCH("@",{first_email_cell})),'
                f'ISNUMBER(SEARCH(".",{first_email_cell},SEARCH("@",{first_email_cell}))),'
                f'LEN({first_email_cell})>=5)'
            ),
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Неисправна е-пошта",
            error="Е-пошта мора садржати знак @ и тачку после њега (нпр. ime@example.com).",
        )
        dv_email.add(f"{email_col}{_DATA_START}:{email_col}{last_data_row}")
        ws.add_data_validation(dv_email)

        # Paste-resistant CF on the Провера column itself + the row-level
        # three-state (empty/✓/✗) coloring on the locked context columns
        # (A:D), driven from each row's own Провера cell with a fully
        # absolute reference (range-wide relative/INDIRECT rules proved
        # unreliable across rows in phase1_generate.py's own history).
        validity_col = get_column_letter(_VALIDITY_COL_IDX)
        validity_range = f"{validity_col}{_DATA_START}:{validity_col}{last_data_row}"
        ws.conditional_formatting.add(
            validity_range,
            FormulaRule(formula=[f'={validity_col}{_DATA_START}="✓"'], fill=_VALID_FILL,
                        font=Font(name="Arial", size=10, bold=True, color=_VALID_FONT_COLOR)),
        )
        ws.conditional_formatting.add(
            validity_range,
            FormulaRule(formula=[f'={validity_col}{_DATA_START}="✗"'], fill=_INVALID_FILL,
                        font=Font(name="Arial", size=10, bold=True, color=_INVALID_FONT_COLOR)),
        )
        empty_font = Font(name="Arial", size=10, bold=True, color=_EMPTY_FONT_COLOR)
        valid_font = Font(name="Arial", size=10, bold=True, color=_VALID_FONT_COLOR)
        invalid_font = Font(name="Arial", size=10, bold=True, color=_INVALID_FONT_COLOR)
        for row_idx in range(_DATA_START, last_data_row + 1):
            row_range = f"A{row_idx}:D{row_idx}"
            n_cell = f"${validity_col}${row_idx}"
            ws.conditional_formatting.add(
                row_range, FormulaRule(formula=[f'={n_cell}=""'], fill=_LOCKED_FILL, font=empty_font),
            )
            ws.conditional_formatting.add(
                row_range, FormulaRule(formula=[f'={n_cell}="✓"'], fill=_VALID_FILL, font=valid_font),
            )
            ws.conditional_formatting.add(
                row_range, FormulaRule(formula=[f'={n_cell}="✗"'], fill=_INVALID_FILL, font=invalid_font),
            )

    ws.freeze_panes = f"E{_DATA_START}"

    # Sheet protection — lock context columns, keep input columns editable
    ws.protection.sheet              = True
    ws.protection.password           = password
    ws.protection.formatCells        = True
    ws.protection.formatColumns      = True
    ws.protection.formatRows         = True
    ws.protection.insertColumns      = True
    ws.protection.insertRows         = True
    ws.protection.deleteColumns      = True
    ws.protection.deleteRows         = True
    ws.protection.pivotTables        = True
    ws.protection.objects            = True
    ws.protection.scenarios          = True
    ws.protection.sort               = False   # allow sorting
    ws.protection.autoFilter         = False   # allow filtering
    ws.protection.selectLockedCells   = False  # can select both
    ws.protection.selectUnlockedCells = False

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    from openpyxl.worksheet.properties import PageSetupProperties
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = f"{_HEADER_ROW}:{_HEADER_ROW}"

    wb.save(out_path)
    wb.close()
    return out_path


# ── Import / validation ───────────────────────────────────────────────

def read_nacelnik_xlsx(
    path: Path | str,
    *,
    election_date: date | None = None,
) -> tuple[list[NacelnikRow], list[str]]:
    """Read a completed nacelnik template.

    Returns ``(rows, errors)``.

    ``rows`` — one ``NacelnikRow`` per data row found in the file, whether
    filled or not.  The caller uses ``row.is_filled`` to detect gaps.

    ``errors`` — human-readable Cyrillic strings.  Non-empty means the
    file must not be imported:
    - Unreadable file or wrong header structure
    - Any slot where Ime or Prezime is still blank (incomplete submission)
    - Invalid JMBG (bad MOD 11 or wrong length) on a filled row
    - Person under 18 on election_date (when provided)

    The caller is responsible for cross-checking JMBGs against the
    existing master to catch duplicates.
    """
    p = Path(path)
    if not p.exists():
        return [], [f"Фајл не постоји: {p.name}"]

    try:
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    except PermissionError:
        return [], [f"Фајл је закључан: {p.name}"]
    except Exception as exc:
        return [], [f"Не могу да отворим '{p.name}': {exc}"]

    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)

    # Validate header row
    header_raw = next(rows_iter, None)
    if header_raw is None:
        wb.close()
        return [], ["Фајл је празан."]

    def _str(v: object) -> str:
        s = str(v or "").strip()
        return s.lstrip("'") if s.startswith("'") else s

    # Legacy shape (11 cols, no Провера, always split Ime/Prezime) --
    # files already generated before this change must still import.
    # Checked first since it's an exact, unambiguous literal match;
    # anything else falls through to the current-shape check below.
    found_legacy = [_str(v) for v in header_raw[:11]]
    is_legacy = (
        len(found_legacy) == 11 and found_legacy == _LEGACY_ALL_COLS
        and (len(header_raw) < 12 or not _str(header_raw[11]))
    )

    if is_legacy:
        combined_name = False
        found_headers: list[str] = found_legacy
        expected: list[str] = _LEGACY_ALL_COLS
    else:
        # combined_name_header (same election-level setting as the party
        # templates — see export_nacelnik_template) merges Ime/Prezime
        # into one "Ime i prezime" box. Detected from the file's own
        # header row, not a live setting, so a file exported under a
        # different value of that toggle always still parses correctly
        # — same technique as popunjeni_io.parse_party_file for the
        # party files.
        header_e = _str(header_raw[4]) if len(header_raw) > 4 else ""
        header_f = _str(header_raw[5]) if len(header_raw) > 5 else ""
        combined_name = bool(header_e) and not header_f
        expected = list(_ALL_COLS)
        if combined_name:
            expected[4], expected[5] = header_e, ""
        found_headers = [_str(header_raw[i]) for i in range(len(_ALL_COLS))]

    if found_headers != expected:
        wb.close()
        return [], [
            f"Неисправна заглавља у фајлу '{p.name}'. "
            f"Очекивано: {expected}. "
            f"Пронађено: {found_headers}."
        ]

    # Skip instruction row (row 2)
    next(rows_iter, None)

    errors: list[str] = []
    nacelnik_rows: list[NacelnikRow] = []

    for rel_idx, raw in enumerate(rows_iter):
        # Skip trailing blank rows that openpyxl sometimes appends
        if raw is None or all(v is None for v in raw):
            continue

        excel_row = _DATA_START + rel_idx

        # Locked context columns (0-based: 0=Р.бр., 1=БМ бр., 2=БМ назив, 3=Функција)
        # Р.бр. (slot_rbr) and БМ назив are display-only — the slot is
        # actually keyed by (bm_number, function), read per row here, so
        # rows can be freely sorted/reordered without breaking the match.
        try:
            bm_number = int(raw[1] or 0)
        except (ValueError, TypeError):
            bm_number = 0
        function = _str(raw[3]) if len(raw) > 3 else ""

        # Editable member-data columns (0-based: 4=Име(/и презиме), 5=Презиме, 6=ЈМБГ, ...)
        if combined_name:
            full_name = _str(raw[4]) if len(raw) > 4 else ""
            first_name, last_name = split_combined_name(full_name)
        else:
            first_name = _str(raw[4]) if len(raw) > 4 else ""
            last_name  = _str(raw[5]) if len(raw) > 5 else ""
        jmbg_raw   = _str(raw[6])  if len(raw) > 6  else ""
        mesto      = _str(raw[7])  if len(raw) > 7  else ""
        adresa     = _str(raw[8])  if len(raw) > 8  else ""
        telefon    = phone_mod.normalize(raw[9]) if len(raw) > 9 else ""
        email      = _str(raw[10]) if len(raw) > 10 else ""

        jmbg      = jmbg_mod.normalize(jmbg_raw)
        is_filled = bool(first_name or last_name)

        nacelnik_rows.append(NacelnikRow(
            bm_number  = bm_number,
            function   = function,
            first_name = first_name,
            last_name  = last_name,
            jmbg       = jmbg,
            mesto      = mesto,
            adresa     = adresa,
            telefon    = telefon,
            email      = email,
            row_number = excel_row,
            is_filled  = is_filled,
        ))

        slot_label = f"БМ {bm_number}, {function}"

        if not is_filled:
            errors.append(
                f"Ред {excel_row} [{slot_label}]: "
                "Ime / Prezime нису унети — слот мора бити попуњен."
            )
            continue  # no point checking JMBG on an unfilled row

        if jmbg:
            if not jmbg_mod.is_valid(jmbg):
                errors.append(
                    f"Ред {excel_row} [{slot_label}]: "
                    f"ЈМБГ '{jmbg}' не пролази MOD 11 проверу."
                )
            elif election_date is not None and not jmbg_mod.is_at_least_18_on(jmbg, election_date):
                errors.append(
                    f"Ред {excel_row} [{slot_label}]: "
                    f"особа са ЈМБГ '{jmbg}' није пунолетна на дан гласања."
                )

    wb.close()
    return nacelnik_rows, errors
