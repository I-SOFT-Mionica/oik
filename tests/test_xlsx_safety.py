"""Tests for xlsx_safety.safe_cell() and its use across every Excel writer.

Field concern: openpyxl auto-promotes any string value starting with
"=" into a live formula (data_type='f') the instant .value is set --
Excel then evaluates it the moment the workbook is opened. This isn't
only a hostile-external-input (party file) concern: an OIK operator
typing a name/address/note that happens to start with "=", "+", "-",
or "@" trips the same auto-promotion by accident. Every writer that
puts operator- or party-controlled free text into a cell must route
it through safe_cell() so the value always stays literal text --
verified here per-writer, not just for the shared helper in isolation.
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest

from biracki_odbor.core.xlsx_safety import safe_cell


# ── safe_cell() unit tests ─────────────────────────────────────────


def _reload(wb) -> openpyxl.Workbook:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return openpyxl.load_workbook(buf)


@pytest.mark.parametrize("bad", ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "=cmd|'/c calc'!A1"])
def test_safe_cell_neutralizes_formula_trigger_characters(bad) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    safe_cell(ws, 1, 1, bad)
    reloaded = _reload(wb)
    cell = reloaded.active.cell(row=1, column=1)
    assert cell.data_type == "s"
    assert cell.value == bad  # text preserved verbatim, no visible artifact


def test_safe_cell_leaves_ordinary_strings_untouched() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    safe_cell(ws, 1, 1, "Јован Јовановић")
    reloaded = _reload(wb)
    cell = reloaded.active.cell(row=1, column=1)
    assert cell.data_type == "s"
    assert cell.value == "Јован Јовановић"


def test_safe_cell_passes_through_non_string_values() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    safe_cell(ws, 1, 1, 42)
    safe_cell(ws, 2, 1, None)
    assert ws.cell(row=1, column=1).value == 42
    assert ws.cell(row=2, column=1).value is None


def test_plain_ws_cell_still_lets_intentional_app_formulas_work() -> None:
    """Sanity check that the vulnerability is real and safe_cell is the
    fix -- an ordinary ws.cell() call (used deliberately for the app's
    own COUNTA/COUNTIF/IF helper formulas) still produces a live
    formula, unlike safe_cell()."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="=COUNTA(A1:A2)")
    reloaded = _reload(wb)
    assert reloaded.active.cell(row=1, column=1).data_type == "f"


# ── Per-writer integration checks ──────────────────────────────────
# Each generates a real file with a field starting with "=" and
# confirms the cell that field lands in is NOT a live formula.


def test_master_export_neutralizes_formula_in_person_name(tmp_path: Path) -> None:
    """The internal master store is SQLite now (plain TEXT columns, no
    formula execution risk at all) -- the formula-injection concern only
    applies to export_master_xlsx(), the one place that still produces
    a real .xlsx from Person data."""
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.master_io import export_master_xlsx
    from biracki_odbor.core.models import Person

    persons = [Person(
        bm_number=1, function="Председник", party="СНС",
        first_name="=HYPERLINK(\"http://evil\",\"click\")", last_name="Презиме",
    )]
    out = export_master_xlsx(persons, OikConstants(), tmp_path / "master.xlsx")
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    # Column 5 = Име (see phase2_aggregate._write_xlsx_export's `values` order).
    name_cells = [c for row in ws.iter_rows(min_row=3) for c in row
                  if isinstance(c.value, str) and c.value.startswith("=HYPERLINK")]
    assert name_cells, "expected the malicious name to be present as text"
    assert all(c.data_type == "s" for c in name_cells)


def test_phase1_party_template_neutralizes_formula_in_station_name(tmp_path: Path) -> None:
    from biracki_odbor.config.oik import OikConstants, Municipality
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.core.phase1_generate import generate_party_files
    from tests.fixtures.stalni_sastav import build_template

    template = build_template(tmp_path / "t.xlsx", n_polling_stations=1, parties=("СНС",))
    oik = OikConstants(
        municipality=Municipality(name="Уб", name_genitive="Уба", name_locative="Убу"),
        polling_stations=[
            PollingStation(bm_number=1, name="=1+1 БМ", full_name="=1+1 Бирачко место 1"),
        ],
        lock_password="test1234",
    )
    out_dir = tmp_path / "stranke"
    result = generate_party_files(template, out_dir, oik)
    assert result.report.ok, [i.message_sr for i in result.report.issues]
    assert result.files_written
    wb = openpyxl.load_workbook(result.files_written[0])
    ws = wb.active
    hit = False
    for row in ws.iter_rows(min_row=4):
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("=1+1"):
                hit = True
                assert c.data_type == "s"
    assert hit, "expected the tampered station name to appear as text somewhere"


def test_nacelnik_template_neutralizes_formula_in_station_name(tmp_path: Path) -> None:
    from biracki_odbor.core.models import Person, PollingStation
    from biracki_odbor.core.nacelnik_xlsx import export_nacelnik_template

    persons = [Person(bm_number=1, function="Члан", party="СНС")]
    stations = {1: PollingStation(bm_number=1, name="=1+1 Опасно место")}
    out = export_nacelnik_template(persons, stations, tmp_path / "nacelnik.xlsx")
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    hits = [c for row in ws.iter_rows(min_row=3) for c in row
            if isinstance(c.value, str) and c.value.startswith("=1+1")]
    assert hits
    assert all(c.data_type == "s" for c in hits)


def test_rik_template_neutralizes_formula_in_member_name(tmp_path: Path) -> None:
    from biracki_odbor.config.election import RikBmEntry, RikPerson
    from biracki_odbor.config.oik import PollingStation
    from biracki_odbor.core.rik_xlsx import export_rik_template

    stations = [PollingStation(bm_number=1, name="БМ 1")]
    existing = {1: RikBmEntry(member=RikPerson(name="=1+1 Опасно"))}
    out = export_rik_template(stations, existing, tmp_path / "rik.xlsx")
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    hits = [c for row in ws.iter_rows(min_row=3) for c in row
            if isinstance(c.value, str) and c.value.startswith("=1+1")]
    assert hits
    assert all(c.data_type == "s" for c in hits)


def test_bm_workbook_neutralizes_formula_in_station_fields(tmp_path: Path) -> None:
    from biracki_odbor.config.oik import PollingStation
    from biracki_odbor.core.template import build_bm_workbook

    stations = [PollingStation(bm_number=1, name="=1+1", address="+1+1", full_name="-1+1")]
    out = build_bm_workbook(stations, tmp_path / "bm.xlsx")
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    row = list(ws.iter_rows(min_row=2, max_row=2))[0]
    for c in row[1:]:  # skip col A (bm_number, an int)
        assert c.data_type == "s"


def test_parties_workbook_neutralizes_formula_in_full_name(tmp_path: Path) -> None:
    from biracki_odbor.core.template import build_parties_workbook

    out = build_parties_workbook({"СНС": "=1+1 Пун назив"}, tmp_path / "parties.xlsx")
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    cell = ws.cell(row=2, column=2)
    assert cell.value == "=1+1 Пун назив"
    assert cell.data_type == "s"
