"""Demo and sample data must contain no personal data, not even by
accident: every JMBG is one no real person holds, phones are 060 000 0NNN,
addresses are generic. The code is public, so a realistic
JMBG here could belong to someone."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from biracki_odbor.core import demo_data, jmbg

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo"


def test_fictional_numbers_are_valid_adults_and_never_issued() -> None:
    for female in (False, True):
        for n in range(20):
            j = jmbg.fictional(15, 3, 1975, female, n)
            assert jmbg.is_valid(j) and jmbg.is_fictional(j)
            assert jmbg.gender(j) == ("F" if female else "M")
            assert jmbg.extract_date_of_birth(j) == date(1975, 3, 15)
            assert jmbg.is_at_least_18_on(j, date(2026, 10, 25))


def _with_serial(first9: str, serial: int) -> str:
    """Valid JMBG with a realistic serial -- built here, never written out."""
    first12 = f"{first9}{serial:03d}"
    remainder = sum(int(c) * w for c, w in zip(first12, jmbg._WEIGHTS)) % 11  # noqa: SLF001
    return first12 + str(0 if remainder == 0 else 11 - remainder)


@pytest.mark.parametrize("serial", [0, 1, 123, 501])
def test_realistic_numbers_are_not_fictional(serial: int) -> None:
    j = _with_serial("010199077", serial)
    if jmbg.is_valid(j):
        assert not jmbg.is_fictional(j)


def _all_jmbgs_in_demo_module() -> list[str]:
    rows = [r for party in demo_data._MEMBERS.values() for r in party]  # noqa: SLF001
    found = [r[2] for r in rows]
    found += [c[2] for c in demo_data._CANDIDATES]  # noqa: SLF001
    found += [o[5] for o in demo_data._OBSERVERS if o[5]]  # noqa: SLF001
    return found


def test_demo_module_people_are_fictional() -> None:
    found = _all_jmbgs_in_demo_module()
    assert len(found) == 30
    assert all(jmbg.is_fictional(j) for j in found), [j for j in found if not jmbg.is_fictional(j)]
    for party in demo_data._MEMBERS.values():  # noqa: SLF001
        for _first, _last, _j, _mesto, address, phone, _email in party:
            assert re.fullmatch(r"Ulica \d+", address)
            assert phone.startswith("0600000") and phone.isdigit()


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.xlsx")))
def test_fixture_files_hold_only_fictional_jmbgs(name: str) -> None:
    wb = openpyxl.load_workbook(FIXTURES / name, data_only=True)
    text = " ".join(str(c) for ws in wb.worksheets for r in ws.iter_rows(values_only=True)
                    for c in r if c is not None)
    for candidate in re.findall(r"(?<!\d)\d{13}(?!\d)", text):
        if jmbg.is_valid(candidate):
            assert jmbg.is_fictional(candidate), f"{name}: {candidate}"
    assert "@gmail.com" not in text


def test_tour_sample_people_are_fictional() -> None:
    import random

    from biracki_odbor.core import sample_fill
    rng = random.Random(7)
    used: set[str] = set()
    for _ in range(200):
        p = sample_fill._person(rng, "Мионица", used)  # noqa: SLF001
        assert jmbg.is_fictional(p.jmbg)
        assert p.phone.startswith("0600000") and p.phone.isdigit()
