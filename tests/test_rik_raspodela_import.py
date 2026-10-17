"""Tests for core.rik_raspodela_import — consuming RIK's own
multi-municipality RASPODELA/UKUPNO exports directly.

Fixture (`tests/fixtures/rik_raspodela.py`) mirrors the real shape
confirmed against an actual 2023 RIK export, including the one
real-world gotcha found by inspection: one municipality block uses
`Општина` without a trailing colon.
"""

from __future__ import annotations

from pathlib import Path

from biracki_odbor.core.models import FUNCTIONS
from biracki_odbor.core.rik_raspodela_import import (
    extract_opstina_registry,
    find_municipality_block,
    read_municipality_allocation,
    read_party_full_names,
)
from tests.fixtures.rik_raspodela import (
    build_combined_2026_workbook,
    build_raspodela_workbook,
    build_raspodela_workbook_no_spacer,
    build_skracenice_workbook,
    build_ukupno_workbook,
)


def test_extract_opstina_registry_finds_both_blocks(tmp_path: Path) -> None:
    """No fixed-count assumption anywhere — this just checks the two
    blocks actually present in this specific fixture are both found,
    including the colon-less one."""
    path = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    reg = extract_opstina_registry(path)
    assert len(reg) == 2
    by_sifra = {b.sifra: b for b in reg}
    assert by_sifra["71218"].name == "Уб"
    assert by_sifra["71218"].okrug == "КОЛУБАРСКИ"
    # The colon-less "Општина" block must still be found by name+okrug.
    assert by_sifra["71129"].name == "Сокобања"
    assert by_sifra["71129"].okrug == "ЗАЈЕЧАРСКИ"


def test_find_municipality_block_by_code(tmp_path: Path) -> None:
    path = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    blk = find_municipality_block(path, "71218")
    assert blk is not None
    assert blk.name == "Уб"

    assert find_municipality_block(path, "00000") is None


def test_read_municipality_allocation_ub(tmp_path: Path) -> None:
    path = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(path, "71218")
    assert result.errors == []
    assert len(result.stations) == 3
    assert [s.bm_number for s in result.stations] == [1, 2, 3]
    assert len(result.allocations) == 3 * len(FUNCTIONS)
    assert {a.function for a in result.allocations} == set(FUNCTIONS)

    assert set(result.quotas) == {"СНС", "СПС", "ССП"}
    q = result.quotas["СНС"]
    assert q.predsednik == 1
    assert q.zamenik == 1
    assert q.clan_i_zamenik == 4


def test_read_municipality_allocation_tolerates_missing_colon(tmp_path: Path) -> None:
    """Real-world gotcha: одна block used `Општина` with no trailing
    colon in an actual RIK export. Must parse cleanly, not silently
    produce an empty/nameless result."""
    path = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(path, "71129")
    assert result.errors == []
    assert len(result.stations) == 2
    assert set(result.quotas) == {"СНС", "СПС", "ССП"}


def test_read_municipality_allocation_unknown_code(tmp_path: Path) -> None:
    path = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(path, "99999")
    assert result.errors
    assert result.stations == []
    assert result.allocations == []
    assert result.quotas == {}


def test_extract_opstina_registry_reads_the_2026_no_spacer_shape(tmp_path: Path) -> None:
    """RIK dropped the blank spacer column this cycle — a marker's value
    moved from column C into column B. Confirmed against a real 2026
    RASPODELA export; must not silently read an empty cell and produce
    an empty/wrong sifra."""
    path = build_raspodela_workbook_no_spacer(tmp_path / "raspodela.xlsx")
    reg = extract_opstina_registry(path)
    assert len(reg) == 1
    assert reg[0].sifra == "70092"
    assert reg[0].name == "Београд-Барајево"
    assert reg[0].okrug == "ГРАД БЕОГРАД"


def test_read_municipality_allocation_the_2026_no_spacer_shape(tmp_path: Path) -> None:
    """Same fixture also pins the quota table's 3rd-row label — spelled
    out as "Чланови +Заменици чланова" this cycle instead of the older
    "Чл.+Зам.чл." — and the party-column start shifting from column C
    to column B alongside the marker-value shift."""
    path = build_raspodela_workbook_no_spacer(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(path, "70092")
    assert result.errors == []
    assert len(result.stations) == 3
    assert set(result.quotas) == {"СНС", "СПС", "ССП"}
    q = result.quotas["СНС"]
    assert q.predsednik == 1
    assert q.zamenik == 1
    assert q.clan_i_zamenik == 4


def test_read_party_full_names(tmp_path: Path) -> None:
    path = build_ukupno_workbook(tmp_path / "ukupno.xlsx")
    names = read_party_full_names(path)
    assert names == {
        "СНС": "Посланичка група СНС — пуни назив",
        "СПС": "Посланичка група СПС — пуни назив",
        "ССП": "Посланичка група ССП — пуни назив",
    }


def test_read_party_full_names_2026_standalone_legend(tmp_path: Path) -> None:
    """Confirmed against a real standalone "skracenice.xlsx": marker
    "Легенда:" in column A, short/long pairs in columns A/B — not the
    older "Напомена:" in column B with pairs in B/C."""
    path = build_skracenice_workbook(tmp_path / "skracenice.xlsx")
    names = read_party_full_names(path)
    assert names == {
        "СНС": "Посланичка група СНС — пуни назив",
        "СПС": "Посланичка група СПС — пуни назив",
        "ССП": "Посланичка група ССП — пуни назив",
    }


def test_read_party_full_names_2026_combined_workbook(tmp_path: Path) -> None:
    """Confirmed against a real "Raspodela_Parlamentarni_rik.xlsx": the
    legend sits on a later sheet, not sheet 0 (RASPODELA data is sheet
    0 there). An operator pointing both file pickers at this same
    combined file must still get the real mapping."""
    path = build_combined_2026_workbook(tmp_path / "combined.xlsx")
    names = read_party_full_names(path)
    assert names == {
        "СНС": "Посланичка група СНС — пуни назив",
        "СПС": "Посланичка група СПС — пуни назив",
        "ССП": "Посланичка група ССП — пуни назив",
    }


def test_read_party_full_names_no_napomena_section(tmp_path: Path) -> None:
    """A workbook with no «Напомена:» marker at all — must return an
    empty mapping, not raise."""
    import openpyxl
    p = tmp_path / "no_napomena.xlsx"
    wb = openpyxl.Workbook()
    wb.active.cell(row=1, column=1, value="ничег овде нема")
    wb.save(p)
    wb.close()
    assert read_party_full_names(p) == {}
