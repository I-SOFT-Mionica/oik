"""Legal-compliance gate: the Raspodela BM x function grid.

DO NOT weaken, skip, or delete these tests to make a release green.

The BM x function allocation grid (which party gets Председник /
Заменик председника / Члан 1 / Заменик члана 1 / Члан 2 / Заменик
члана 2 at each polling station) is not an app convenience — it is
the legally mandated record of who was appointed to each стални
sastav slot. Product decision (2026-07-11): "we can have
whatever else in there, but that grid needs to be there its the law."
Whatever else changes about Stalni_sastav.xlsx (RIK's party-quota
preamble, header wording variants, extra sheets), this exact grid
must always be:
  - producible by our exporter (build_blank_template), and
  - reliably extractable by our importer (read_template),
for every polling-station count from 1 up to a realistically large
municipality. If a change to core/template.py or core/models.FUNCTIONS
breaks any assertion here, that change must not ship — fix the
regression, don't adjust the test to match broken behavior.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from biracki_odbor.core import template
from biracki_odbor.core.models import FUNCTIONS, PollingStation


# ── The shape itself is a legal constant, not a design choice ──────────

def test_functions_tuple_is_the_legally_mandated_six_roles() -> None:
    """Стални sastav has exactly 6 roles per BM. If this ever changes,
    it's a legal/statutory change, not a refactor — must be a deliberate,
    reviewed edit, never an accidental one.
    """
    assert FUNCTIONS == (
        "Председник",
        "Заменик председника",
        "Члан 1",
        "Заменик члана 1",
        "Члан 2",
        "Заменик члана 2",
    )


# ── Exporter: build_blank_template must always produce the grid ────────
#
# 250 is the documented real-world ceiling (2026-07-11): the
# largest OIK/GIK in Serbia (Belgrade) has never exceeded 250 BMs. Test
# up to and including that real maximum, not an arbitrary round number.

@pytest.mark.parametrize("n_stations", [1, 3, 33, 52, 120, 250])
def test_exported_template_always_has_full_grid(tmp_path: Path, n_stations: int) -> None:
    stations = [
        PollingStation(bm_number=i + 1, name=f"БM {i + 1}")
        for i in range(n_stations)
    ]
    p = template.build_blank_template(tmp_path / "blank.xlsx", stations=stations)
    wb = openpyxl.load_workbook(p)
    ws = wb[template.SHEET_RASPODELA]

    # Header row: BM anchor + all 6 function names, in order, columns B..G.
    assert ws.cell(row=1, column=1).value == "БР БМ"
    header_functions = tuple(
        ws.cell(row=1, column=c).value for c in range(2, 2 + len(FUNCTIONS))
    )
    assert header_functions == FUNCTIONS

    # One row per station, BM numbers present, 6 addressable cells each
    # (blank — ready for short-name entry — but the cells must exist).
    for i, station in enumerate(stations):
        row = i + 2
        assert ws.cell(row=row, column=1).value == station.bm_number
        for c in range(2, 2 + len(FUNCTIONS)):
            # Must be addressable/blank, not missing — a truncated grid
            # (fewer than n_stations rows, or fewer than 6 columns) would
            # silently omit slots from the legal record.
            assert ws.cell(row=row, column=c).value in (None, "")


def test_exported_template_shape_unchanged_when_allocations_prefilled(tmp_path: Path) -> None:
    """The in-app matrix builder pre-fills cells via `allocations` at
    write time instead of an operator typing them into Excel afterward —
    the grid's shape/header contract must be byte-for-byte identical
    either way. If pre-filling ever changed the header row, column
    count, or BM-number placement, the matrix builder would silently
    diverge from the legally mandated shape this whole file guards.
    """
    from biracki_odbor.core.models import Allocation

    stations = [PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(5)]
    allocations = [
        Allocation(bm_number=s.bm_number, function=f, party="СНС")
        for s in stations for f in FUNCTIONS
    ]
    p = template.build_blank_template(
        tmp_path / "prefilled.xlsx", stations=stations, allocations=allocations,
    )
    wb = openpyxl.load_workbook(p)
    ws = wb[template.SHEET_RASPODELA]

    assert ws.cell(row=1, column=1).value == "БР БМ"
    header_functions = tuple(
        ws.cell(row=1, column=c).value for c in range(2, 2 + len(FUNCTIONS))
    )
    assert header_functions == FUNCTIONS
    for i, station in enumerate(stations):
        assert ws.cell(row=i + 2, column=1).value == station.bm_number

    data, report = template.read_template(p)
    assert report.ok, [i.message_sr for i in report.issues]
    assert len(data.allocations) == 5 * len(FUNCTIONS)


def test_exported_template_grid_survives_short_name_entry_and_reimport(tmp_path: Path) -> None:
    """End-to-end: export -> fill in short names (as an operator would) ->
    re-import -> every slot must come back exactly as entered.
    """
    stations = [PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(5)]
    p = template.build_blank_template(tmp_path / "blank.xlsx", stations=stations)

    wb = openpyxl.load_workbook(p)
    ws = wb[template.SHEET_RASPODELA]
    parties = ("СНС", "ССП", "НАДА", "ДС", "СПС", "ЗЛФ")
    for i in range(5):
        row = i + 2
        for c in range(2, 8):
            ws.cell(row=row, column=c, value=parties[(i + c) % len(parties)])
    wb.save(p)
    wb.close()

    data, report = template.read_template(p)
    assert report.ok, [i.message_sr for i in report.issues]
    assert len(data.allocations) == 5 * len(FUNCTIONS)
    # Every BM has all 6 roles filled — no legally-required slot missing.
    by_bm: dict[int, set[str]] = {}
    for a in data.allocations:
        by_bm.setdefault(a.bm_number, set()).add(a.function)
    assert len(by_bm) == 5
    for bm, funcs in by_bm.items():
        assert funcs == set(FUNCTIONS), f"BM {bm} missing roles: {set(FUNCTIONS) - funcs}"


# ── Importer: must find the grid no matter what else is in the file ────

def _write_real_world_shaped_file(
    path: Path, *, n_stations: int, n_preamble_parties: int,
) -> None:
    """Builds a file shaped like an actual RIK-provided Stalni_sastav.xlsx:
    a party-seat-quota summary table of VARIABLE length (more parties
    running this cycle -> longer preamble), a blank separator, THEN the
    real "БР БМ" grid. Confirmed real-world shape, 2026-07-10 session.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = template.SHEET_RASPODELA

    ws.cell(row=1, column=1, value="Посланичка група")
    for r in range(2, 2 + n_preamble_parties):
        ws.cell(row=r, column=1, value=f"Странка {r}")
    ws.cell(row=1 + n_preamble_parties + 1, column=1, value="УКУПНО")
    header_row = 1 + n_preamble_parties + 3  # +1 total row, +1 blank, +1 to land ON header
    ws.cell(row=header_row, column=1, value="БР БМ")
    for c, func in enumerate(FUNCTIONS, start=2):
        ws.cell(row=header_row, column=c, value=func)
    for i in range(n_stations):
        row = header_row + 1 + i
        ws.cell(row=row, column=1, value=i + 1)
        for c in range(2, 2 + len(FUNCTIONS)):
            ws.cell(row=row, column=c, value="СНС")

    wb.save(path)
    wb.close()


@pytest.mark.parametrize("n_preamble_parties", [1, 5, 17, 40])
def test_importer_finds_grid_regardless_of_preamble_length(
    tmp_path: Path, n_preamble_parties: int,
) -> None:
    """A cycle with more parties running produces a longer party-quota
    preamble above the grid. However many parties, the grid must still
    be found — this must never regress to the old fixed-10-row scan
    window that silently HEADER_MISMATCHed real files.
    """
    p = tmp_path / "real_shape.xlsx"
    _write_real_world_shaped_file(p, n_stations=10, n_preamble_parties=n_preamble_parties)

    data, report = template.read_template(p)
    assert report.ok, [i.message_sr for i in report.issues]
    assert len(data.allocations) == 10 * len(FUNCTIONS)


def test_importer_finds_grid_alongside_unrelated_extra_sheets(tmp_path: Path) -> None:
    """'Whatever else in there' — extra sheets elsewhere in the workbook
    must not interfere with finding/reading the grid.
    """
    stations = [PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(4)]
    p = template.build_blank_template(tmp_path / "blank.xlsx", stations=stations)

    wb = openpyxl.load_workbook(p)
    ws = wb[template.SHEET_RASPODELA]
    for i in range(4):
        row = i + 2
        for c in range(2, 8):
            ws.cell(row=row, column=c, value="СНС")
    extra = wb.create_sheet("Напомене")
    extra.cell(row=1, column=1, value="Ово је ирелевантан лист.")
    wb.save(p)
    wb.close()

    data, report = template.read_template(p)
    assert report.ok, [i.message_sr for i in report.issues]
    assert len(data.allocations) == 4 * len(FUNCTIONS)
