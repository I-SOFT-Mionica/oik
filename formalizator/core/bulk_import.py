"""Bulk entry of many voters at once, from a .xlsx or .csv file, instead
of one card read / manual entry per person.

Two directions, sharing one field vocabulary:

  * `write_template(template, path)` — an empty workbook/CSV with
    exactly the columns this calibrated template needs, so an operator
    (or someone they hand it to) can fill many rows offline and bring
    the file back.
  * `read_entries(path, template)` — parses either format back into
    `VoterEntry` objects, validating every row the same way the manual
    fill-out screen does (required name, JMBG format + MOD-11), so a
    typo is caught before anything prints rather than after.

The column headers are the same Serbian labels already on the fill-out
screen (see `fillout_screen.py`'s `form.addRow(...)` calls) plus each
of the template's own "individual" custom fields, in the same
top-to-bottom page order the fill-out screen already sorts them in
(`_page_order_key`) — one vocabulary, not a second one invented for
files. `full_residence`/`full_document_info`/`jmbg_1..13` (the
computed/derived fields `VoterEntry.to_dict()` adds for the overlay)
are deliberately absent: those are outputs, not something the operator
should be typing by hand.

The .xlsx template borrows the house style documented in
oik-excel-skill.md (styled header, a JMBG live-checksum status column,
a document-type dropdown) — lighter than the fully locked/protected
templates that skill also covers, since this file is filled by the
operator's own side, not handed to an external party through an
unattended pipeline; sheet protection would only get in the way of
adding/removing rows for a variable number of people.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from biracki_odbor.core import jmbg as jmbg_mod

from formalizator.core.models import DOCUMENT_TYPES, CalibratedTemplate, VoterEntry

# Excel-friendly BOM so a double-clicked CSV opens with Cyrillic intact
# in Excel, which otherwise guesses the wrong codepage for a bare utf-8
# file with no BOM.
CSV_ENCODING = "utf-8-sig"

# (VoterEntry field name, column header) — the exact labels already
# shown on the fill-out screen, in the document's own top-to-bottom
# order. jmbg is placed right after the name fields to match the form;
# everything else follows form.addRow's order in fillout_screen.py.
_FIXED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("given_name", "Име"),
    ("surname", "Презиме"),
    ("jmbg", "ЈМБГ"),
    ("date_of_birth", "Датум рођења"),
    ("city", "Место"),
    ("full_address", "Адреса"),
    ("document_type", "Врста документа"),
    ("document_reg_no", "Број документа"),
    ("date_of_issue", "Датум издавања"),
    ("issuing_authority", "Издавалац"),
)

# Case-insensitive, trimmed header -> VoterEntry field name.
_HEADER_TO_FIELD = {label.strip().casefold(): key for key, label in _FIXED_COLUMNS}


def _custom_columns(template: CalibratedTemplate | None) -> list:
    """This template's "individual" (per-voter) custom fields, in page
    order — "universal" ones are session-wide and typed once on the
    setup screen, never a per-row column here."""
    if template is None:
        return []
    from formalizator.gui.fillout_screen import _page_order_key  # local: gui <- core would cycle otherwise

    individual = [cf for cf in template.custom_fields if cf.kind == "individual"]
    individual.sort(key=lambda cf: _page_order_key(template, cf.key))
    return individual


def headers_for(template: CalibratedTemplate | None) -> list[str]:
    """Column headers for this template: the fixed fields, then each of
    its own individual custom fields by label."""
    return [label for _key, label in _FIXED_COLUMNS] + [cf.label for cf in _custom_columns(template)]


# ── Row-level result ────────────────────────────────────────────────


@dataclass
class RowResult:
    row_number: int  # 1-based, counting the header as row 1 (matches what Excel shows)
    entry: VoterEntry
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ImportResult:
    rows: list[RowResult] = field(default_factory=list)
    file_error: str = ""  # set instead of `rows` when the file itself couldn't be read at all

    @property
    def valid_rows(self) -> list[RowResult]:
        return [r for r in self.rows if r.ok]

    @property
    def invalid_rows(self) -> list[RowResult]:
        return [r for r in self.rows if not r.ok]


def _validate(entry: VoterEntry) -> list[str]:
    """Same gate _on_print applies to a single typed/read entry —
    required here too, or a bulk import becomes the one path that can
    slip a blank ЈМБГ into a printed declaration."""
    errors = []
    if not entry.given_name.strip() or not entry.surname.strip():
        errors.append("Име и презиме су обавезни.")
    if not jmbg_mod.is_valid(entry.jmbg):
        errors.append(
            "ЈМБГ је обавезан и мора имати 13 цифара које пролазе MOD 11 проверу."
            if not entry.jmbg.strip() else
            "ЈМБГ не пролази MOD 11 проверу."
        )
    return errors


def _entry_from_row(row: dict[str, str], custom_keys_by_label: dict[str, str]) -> VoterEntry:
    """`row` is already header-normalized: fixed-field keys under their
    VoterEntry attribute name, custom fields under their column label."""
    entry = VoterEntry(
        given_name=row.get("given_name", "").strip(),
        surname=row.get("surname", "").strip(),
        jmbg=jmbg_mod.normalize(row.get("jmbg", "")),
        date_of_birth=row.get("date_of_birth", "").strip(),
        city=row.get("city", "").strip(),
        full_address=row.get("full_address", "").strip(),
        document_type=row.get("document_type", "").strip() or DOCUMENT_TYPES[0],
        document_reg_no=row.get("document_reg_no", "").strip(),
        date_of_issue=row.get("date_of_issue", "").strip(),
        issuing_authority=row.get("issuing_authority", "").strip(),
        source="bulk",
    )
    # The JMBG's first 7 digits *are* the date of birth — fill it in
    # exactly like manual entry does, only when the operator's sheet
    # left the column blank rather than typing something else.
    if not entry.date_of_birth:
        dob = jmbg_mod.extract_date_of_birth(entry.jmbg)
        if dob is not None:
            entry.date_of_birth = f"{dob.day:02d}.{dob.month:02d}.{dob.year}"
    for label, key in custom_keys_by_label.items():
        if label in row:
            entry.custom_values[key] = row[label].strip()
    return entry


def _rows_from_headers(
    raw_rows: list[dict[str, str]], template: CalibratedTemplate | None,
) -> ImportResult:
    custom_keys_by_label = {cf.label: cf.key for cf in _custom_columns(template)}

    result = ImportResult()
    for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        if not any((v or "").strip() for v in raw.values()):
            continue  # a blank row (trailing Excel rows, a stray Enter) is not an error
        # Mixed-namespace on purpose, matching what _entry_from_row reads
        # back: a fixed field lands under its VoterEntry attribute name
        # (e.g. "given_name"), a custom field keeps its own column label
        # (e.g. "Оверитељ") since custom_keys_by_label maps that label to
        # its storage key. An unrecognised header (a note column, a
        # leftover formula-helper column) is simply not copied over —
        # never an error, since it's the operator's sheet to extend.
        normalized: dict[str, str] = {}
        for header, value in raw.items():
            h = (header or "").strip()
            field_key = _HEADER_TO_FIELD.get(h.casefold())
            if field_key:
                normalized[field_key] = value or ""
            elif h in custom_keys_by_label:
                normalized[h] = value or ""
        entry = _entry_from_row(normalized, custom_keys_by_label)
        result.rows.append(RowResult(row_number=i, entry=entry, errors=_validate(entry)))
    return result


# ── CSV ──────────────────────────────────────────────────────────────


def _write_csv_template(template: CalibratedTemplate | None, path: Path) -> None:
    with open(path, "w", newline="", encoding=CSV_ENCODING) as f:
        csv.writer(f).writerow(headers_for(template))


def _read_csv(path: Path) -> list[dict[str, str]]:
    # utf-8-sig also transparently strips a BOM if present, and reads a
    # plain utf-8 file (no BOM) just as well — handles a template this
    # app wrote AND one someone typed from scratch in a plain editor.
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ── XLSX ─────────────────────────────────────────────────────────────

_HEADER_FILL_COLOR = "2F5496"
_LOCKED_FILL_COLOR = "D9E2F3"
_VALID_FILL_COLOR = "C6EFCE"
_INVALID_FILL_COLOR = "FFC7CE"


def _write_xlsx_template(template: CalibratedTemplate | None, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    # Not duplicated locally — Formalizator already depends on
    # biracki_odbor for the shared style (apply_global_style) and JMBG
    # module; this is the same cross-import pattern.
    from biracki_odbor.core.xlsx_safety import safe_cell

    headers = headers_for(template)
    wb = Workbook()
    ws = wb.active
    ws.title = "Унос"

    header_fill = PatternFill("solid", fgColor=_HEADER_FILL_COLOR)
    header_font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
    for col, label in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=label)
        c.fill = header_fill
        c.font = header_font
    ws.freeze_panes = "A2"

    # A generous, editable block below the header — plenty of rows for
    # a real signature-collection sitting without the operator having
    # to extend anything themselves; unused rows are just left blank.
    last_row = 501
    col_index = {label: i + 1 for i, label in enumerate(headers)}

    if "Врста документа" in col_index:
        col = col_index["Врста документа"]
        letter = ws.cell(row=1, column=col).column_letter
        safe_cell(ws, 2, col, DOCUMENT_TYPES[0])  # seed one example; rest genuinely blank
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(DOCUMENT_TYPES) + '"',
            allow_blank=True,
        )
        dv.error = "Изаберите једну од понуђених вредности."
        dv.errorTitle = "Неисправна вредност"
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}{last_row}")

    if "ЈМБГ" in col_index:
        col = col_index["ЈМБГ"]
        letter = ws.cell(row=1, column=col).column_letter
        checksum = jmbg_mod.excel_validation_formula(f"{letter}2")
        # Row 2's formula only; the per-row CF loop below re-anchors it
        # for every row — see oik-excel-skill.md's note on why a single
        # relative-reference rule across a range is unreliable in Excel.
        for row in range(2, last_row + 1):
            ref = f"{letter}{row}"
            check = jmbg_mod.excel_validation_formula(ref)
            ws.conditional_formatting.add(
                ref,
                FormulaRule(
                    formula=[f'=AND({ref}<>"",NOT({check}))'],
                    fill=PatternFill("solid", fgColor=_INVALID_FILL_COLOR),
                    font=Font(color="9C0006"),
                ),
            )
            ws.conditional_formatting.add(
                ref,
                FormulaRule(
                    formula=[f'=AND({ref}<>"",{check})'],
                    fill=PatternFill("solid", fgColor=_VALID_FILL_COLOR),
                    font=Font(color="006100"),
                ),
            )

    widths = {"Име": 16, "Презиме": 16, "ЈМБГ": 15, "Датум рођења": 14, "Место": 16,
              "Адреса": 28, "Врста документа": 16, "Број документа": 16,
              "Датум издавања": 14, "Издавалац": 22}
    for label, col in col_index.items():
        letter = ws.cell(row=1, column=col).column_letter
        ws.column_dimensions[letter].width = widths.get(label, 20)

    wb.save(path)


def _read_xlsx(path: Path) -> list[dict[str, str]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return []
        headers = [str(h).strip() if h is not None else "" for h in header_row]
        out = []
        for values in rows_iter:
            row = {
                headers[i]: ("" if values[i] is None else str(values[i]).strip())
                for i in range(min(len(headers), len(values)))
                if headers[i]
            }
            out.append(row)
        return out
    finally:
        wb.close()


# ── Public API ───────────────────────────────────────────────────────

SUPPORTED_SUFFIXES = (".xlsx", ".csv")


def write_template(template: CalibratedTemplate | None, path: Path | str) -> Path:
    """Write a blank, column-matched template at `path`. Format is
    chosen by `path`'s own extension (.xlsx or .csv) — callers offer
    both as separate "Save as" options rather than this function
    guessing which the operator wants."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        _write_xlsx_template(template, path)
    elif path.suffix.lower() == ".csv":
        _write_csv_template(template, path)
    else:
        raise ValueError(f"Неподржан формат фајла: {path.suffix}")
    return path


def read_entries(path: Path | str, template: CalibratedTemplate | None) -> ImportResult:
    """Parse `path` (.xlsx or .csv) into VoterEntry rows, each already
    validated the same way a single manual entry is before it can
    print. Never raises for a bad *row* — only for a file that could
    not be opened/parsed at all, reported via `ImportResult.file_error`
    so the dialog has one thing to show either way."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".xlsx":
            raw_rows = _read_xlsx(path)
        elif path.suffix.lower() == ".csv":
            raw_rows = _read_csv(path)
        else:
            return ImportResult(file_error=f"Неподржан формат фајла: {path.suffix}")
    except Exception as e:  # noqa: BLE001 — a malformed/locked file is a user-facing message, not a crash
        return ImportResult(file_error=f"Фајл се не може прочитати: {e}")

    if not raw_rows:
        return ImportResult(file_error="Фајл не садржи ниједан ред са подацима.")
    return _rows_from_headers(raw_rows, template)
