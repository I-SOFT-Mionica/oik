"""Sample data for the guided tour (demo mode).

Prospective users have this cycle's RIK РАСПОДЕЛА file, but their
parties submitted on RIK's own forms or on paper, never in our Phase 1
template -- so a tour on their own data would stall at Обједињавање.
This fills the Phase 1 party files in place with fictional people, so
the rest of the flow (import, conflicts, decisions) runs on their real
polling stations and parties.

Filled in place (not rebuilt) so each file keeps its Phase 1 identity
marker and passes the normal import checks unchanged. Everyone is
fictional: random name + surname, a never-issued JMBG (core.jmbg.fictional)
and a 060 000 0NNN phone; adult on any
date after 2016. A couple of people are deliberately repeated across
two parties so Корекције → Конфликти has something to show.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from biracki_odbor.core.jmbg import fictional

_MALE = ("Марко", "Никола", "Стефан", "Милош", "Лазар", "Душан", "Петар", "Александар",
         "Иван", "Немања", "Драган", "Зоран", "Горан", "Милан", "Владимир", "Небојша")
_FEMALE = ("Јелена", "Марија", "Ана", "Милица", "Јована", "Ивана", "Драгана", "Тамара",
           "Снежана", "Гордана", "Сандра", "Катарина", "Невена", "Бојана", "Мирјана", "Сања")
_SURNAMES = ("Јовановић", "Петровић", "Николић", "Марковић", "Ђорђевић", "Стојановић",
             "Илић", "Станковић", "Павловић", "Милошевић", "Стевановић", "Ђурић",
             "Томић", "Костић", "Радовановић", "Филиповић", "Лукић", "Савић", "Митровић",
             "Живковић", "Обрадовић", "Тодоровић", "Ристић", "Вуковић")
_STREETS = ("Карађорђева", "Немањина", "Цара Душана", "Војводе Мишића", "Кнеза Милоша",
            "Светог Саве", "Таковска", "Вука Караџића", "Николе Тесле", "Браће Недића")

_FUNCTION_COL = 4   # D
_FIRST_DATA_ROW = 4


@dataclass(frozen=True)
class SamplePerson:
    first_name: str
    last_name: str
    jmbg: str
    place: str
    address: str
    phone: str
    email: str


def _jmbg(rng: random.Random, female: bool) -> str:
    """Valid checksum, never issued to a real person (core.jmbg.fictional)."""
    return fictional(rng.randint(1, 28), rng.randint(1, 12), rng.randint(1955, 1998),
                     female, rng.randint(0, 19))


def _person(rng: random.Random, place: str, used_jmbg: set[str]) -> SamplePerson:
    female = rng.random() < 0.5
    first = rng.choice(_FEMALE if female else _MALE)
    last = rng.choice(_SURNAMES)
    jmbg = _jmbg(rng, female)
    while jmbg in used_jmbg:
        jmbg = _jmbg(rng, female)
    used_jmbg.add(jmbg)
    phone = f"0600000{rng.randint(0, 999):03d}"  # 060 000 0NNN, see demo_data
    email = "" if rng.random() < 0.3 else f"primer{rng.randint(100, 999)}@example.com"
    address = f"{rng.choice(_STREETS)} {rng.randint(1, 120)}"
    return SamplePerson(first, last, jmbg, place, address, phone, email)


def _is_slot_row(ws, row: int) -> bool:
    from biracki_odbor.core.popunjeni_io import FUNCTIONS
    from biracki_odbor.core.prosireni_allocation import parse_slot_function
    bm = ws.cell(row=row, column=2).value
    func = ws.cell(row=row, column=_FUNCTION_COL).value
    if bm is None or func is None:
        return False
    f = str(func).strip()
    return f in FUNCTIONS or parse_slot_function(f) is not None


def _write(ws, row: int, p: SamplePerson, combined_name: bool) -> None:
    if combined_name:
        ws.cell(row=row, column=5, value=f"{p.first_name} {p.last_name}")
    else:
        ws.cell(row=row, column=5, value=p.first_name)
        ws.cell(row=row, column=6, value=p.last_name)
    ws.cell(row=row, column=7, value=p.jmbg)
    ws.cell(row=row, column=8, value=p.place)
    ws.cell(row=row, column=9, value=p.address)
    ws.cell(row=row, column=10, value=p.phone)
    ws.cell(row=row, column=11, value=p.email or None)


def fill_party_files(
    party_files: list[Path], *, place: str, seed: int = 2026, conflicts: int = 2,
) -> int:
    """Fill every empty slot row of each Phase 1 party file in place with
    a fictional person; then repeat `conflicts` people from the first file
    into the second (cross-party JMBG conflicts). Returns rows filled."""
    rng = random.Random(seed)
    used: set[str] = set()
    filled = 0
    first_people: list[SamplePerson] = []
    books = []
    for path in sorted(party_files):
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        combined = bool(ws["E3"].value) and not ws["F3"].value
        rows = [r for r in range(_FIRST_DATA_ROW, ws.max_row + 1) if _is_slot_row(ws, r)]
        for r in rows:
            p = _person(rng, place, used)
            _write(ws, r, p, combined)
            filled += 1
            if not books:
                first_people.append(p)
        books.append((path, wb, ws, combined, rows))
    if len(books) >= 2 and first_people:
        _, _, ws2, combined2, rows2 = books[1]
        for p, r in zip(first_people[:conflicts], reversed(rows2)):
            _write(ws2, r, p, combined2)
    for path, wb, *_ in books:
        wb.save(path)
        wb.close()
    return filled
