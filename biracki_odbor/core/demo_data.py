"""Generate demo Excel fixtures for end-to-end workflow testing.

Public API: ``generate_all(out_dir)`` — creates five files and returns
their paths.  Usable from the About page button, the CLI helper script,
and (future) automated integration tests.

Scenario: Мионица, combined local+parliamentary elections, 5 BMs, 3
parties (SNS / SPS / ZLF), 18 committee members, 9 prosireni candidates,
5 observers.  Everyone is invented: generic names, "Ulica N" addresses,
060 000 0NNN phones, and JMBGs from core.jmbg.fictional() (valid
checksum, never issued to a real person).
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

# ── Styles ────────────────────────────────────────────────────────────

_BOLD = Font(bold=True)
_HEADER_FILL = PatternFill("solid", fgColor="2F5496")
_HEADER_FONT = Font(bold=True, color="FFFFFF", name="Arial", size=10)
_PARTY_FILLS = {
    "SNS": PatternFill("solid", fgColor="BDD7EE"),
    "SPS": PatternFill("solid", fgColor="E2EFDA"),
    "ZLF": PatternFill("solid", fgColor="FCE4D6"),
}

# ── Demo data ─────────────────────────────────────────────────────────

_BMS = [
    (1, "OS Obrenovc",           "Karadjordjeva 12, Mionica",       "OS Obrenovc — Mionica"),
    (2, "MZ Gornja Gorevnica",   "Glavna b.b., Gornja Gorevnica",   "Mesna zajednica Gornja Gorevnica"),
    (3, "Dom kulture Stublne",   "Skolska 1, Stublne",              "Dom kulture Stublne"),
    (4, "MK Banje",              "Cerska b.b., Banje",              "Mesna kancelarija Banje"),
    (5, "MZ Osljane",            "Glavna 3, Osljane",               "Mesna zajednica Osljane"),
]

_PARTIES = {
    "SNS": "Srpska napredna stranka",
    "SPS": "Socijalisticka partija Srbije",
    "ZLF": "Zajedno za Mionicu",
}

_PARTY_EMAILS = {
    "SNS": "stranka1@email.com",
    "SPS": "stranka2@email.com",
    "ZLF": "",
}

_FUNCTIONS = [
    "Predsednik", "Zamenik predsednika",
    "Clan 1", "Zamenik clana 1",
    "Clan 2", "Zamenik clana 2",
]

# Raspodela: {bm_number: [party_abbrev per function (6)]}
_RASPODELA = {
    1: ["SNS", "SPS", "ZLF", "SNS", "SPS", "ZLF"],
    2: ["SPS", "ZLF", "SNS", "SPS", "ZLF", "SNS"],
    3: ["ZLF", "SNS", "SPS", "ZLF", "SNS", "SPS"],
    4: ["SNS", "SPS", "ZLF", "SNS", "SPS", "ZLF"],
    5: ["ZLF", "SNS", "SPS", "ZLF", "SNS", "SPS"],
}

# (first, last, jmbg, mesto, adresa, telefon, email) — invented; every JMBG
# comes from core.jmbg.fictional() (valid checksum, never issued)
_MEMBERS: dict[str, list[tuple]] = {
    "SNS": [
        ("Petar",   "Petrovic",  "1503975774819", "Mionica",          "Ulica 1", "0600000001", ""),
        ("Marko",   "Markovic",  "2207968774825", "Mionica",          "Ulica 2", "0600000002", ""),
        ("Nikola",  "Nikolic",   "0811982774835", "Gornja Gorevnica", "Ulica 3", "0600000003", ""),
        ("Jelena",  "Jelic",     "1204979779842", "Mionica",          "Ulica 4", "0600000004", ""),
        ("Ana",     "Anic",      "0309988779858", "Stublne",          "Ulica 5", "0600000005", ""),
        ("Jovan",   "Jovic",     "2906971774866", "Mionica",          "Ulica 6", "0600000006", ""),
    ],
    "SPS": [
        ("Milan",   "Milic",     "1402966774872", "Mionica",          "Ulica 7", "0600000007", ""),
        ("Dragan",  "Dragic",    "0705973774887", "Gornja Gorevnica", "Ulica 8", "0600000008", ""),
        ("Stevan",  "Stevic",    "1810961774891", "Banje",            "Ulica 9", "0600000009", ""),
        ("Milica",  "Milicic",   "2508977779902", "Mionica",          "Ulica 10", "0600000010", ""),
        ("Vesna",   "Vesic",     "1112984779913", "Osljane",          "Ulica 11", "0600000011", ""),
        ("Pavle",   "Pavlic",    "0101978774920", "Mionica",          "Ulica 12", "0600000012", ""),
    ],
    "ZLF": [
        ("Goran",   "Goric",     "3004980774933", "Mionica",          "Ulica 13", "0600000013", ""),
        ("Ranko",   "Rankic",    "2309972774942", "Gornja Gorevnica", "Ulica 14", "0600000014", ""),
        ("Zoran",   "Zoric",     "1606986774954", "Stublne",          "Ulica 15", "0600000015", ""),
        ("Maja",    "Majic",     "0903990779961", "Mionica",          "Ulica 16", "0600000016", ""),
        ("Jasna",   "Jasnic",    "1807976779988", "Banje",            "Ulica 17", "0600000017", ""),
        ("Sanja",   "Sanjic",    "0501993779988", "Osljane",          "Ulica 18", "0600000018", ""),
    ],
}

# (bm, function_index_0based, member_index_0based)
_ASSIGNMENTS: dict[str, list[tuple]] = {
    "SNS": [
        (1, 0, 0), (1, 3, 3), (2, 2, 1), (2, 5, 2),
        (3, 1, 4), (3, 4, 5), (4, 0, 0), (4, 3, 3),
        (5, 1, 1), (5, 4, 2),
    ],
    "SPS": [
        (1, 1, 0), (1, 4, 3), (2, 0, 1), (2, 3, 4),
        (3, 2, 2), (3, 5, 5), (4, 1, 0), (4, 4, 3),
        (5, 2, 1), (5, 5, 4),
    ],
    "ZLF": [
        (1, 2, 0), (1, 5, 1), (2, 1, 2), (2, 4, 3),
        (3, 0, 4), (3, 3, 5), (4, 2, 0), (4, 5, 1),
        (5, 0, 2), (5, 3, 3),
    ],
}

# (entity_id, full_ballot_name, entity_type, submission_order, linked_to)
_ENTITIES = [
    ("sns-local", "SRPSKA NAPREDNA STRANKA — ALEKSANDAR VUCIC", "party",             1, ""),
    ("sps-local", "SOCIJALISTICKA PARTIJA SRBIJE — IVICA DACIC", "coalition",        2, ""),
    ("zlf-local", "ZAJEDNO ZA MIONICU",                           "group_of_citizens", 3, ""),
]

# (entity_id, full_name, jmbg) — invented, fictional() JMBGs, no collision with members
_CANDIDATES = [
    ("sns-local", "Luka Lukic",          "0202995774994"),
    ("sns-local", "Vuk Vukic",           "1708998774809"),
    ("sns-local", "Ivana Ivic",          "2211999779814"),
    ("sps-local", "Tamara Tamic",        "0804001779828"),
    ("sps-local", "Nemanja Nemic",       "1306994774838"),
    ("sps-local", "Natasa Natic",        "3010997779858"),
    ("zlf-local", "Bojan Bojic",         "0512997774850"),
    ("zlf-local", "Ena Enic",            "1403000779866"),
    ("zlf-local", "Ognjen Ognjic",       "2809992774879"),
]

# (name, type, contact)
_OBSERVER_ORGS = [
    ("CESID",                       "domaca", "kontakt@cesid.rs"),
    ("Ambasada SR Nemacke u Beogradu", "strana", ""),
]

# (org, first, last, citizenship, bm_assignment, jmbg, doc_type, doc_num)
_OBSERVERS = [
    ("CESID",                          "Stefan", "Stefic", "domaci", "BM 1, BM 2", "1104985774882", "", ""),
    ("CESID",                          "Teodora", "Teodoric", "domaca", "Sva BM", "0308991779897", "", ""),
    ("CESID",                          "Filip", "Filipic", "domaci", "BM 3", "2702995774900", "", ""),
    ("Ambasada SR Nemacke u Beogradu", "John",  "Doe",      "strani", "BM 1",       "",              "pasos",                "X0000001"),
    ("Ambasada SR Nemacke u Beogradu", "Max",   "Mustermann", "strani", "Sva BM",   "",              "licna karta stranca",  "X0000002"),
]


# ── Helpers ───────────────────────────────────────────────────────────

def _header(ws, col: int, text: str) -> None:
    c = ws.cell(row=1, column=col, value=text)
    c.font = _HEADER_FONT
    c.fill = _HEADER_FILL
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


# ── Generators ────────────────────────────────────────────────────────

def generate_sablon(out_path: Path) -> Path:
    """Allocation template — upload in Phase 1 to generate party files."""
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    bm_by_num = {bm[0]: bm for bm in _BMS}

    ws_bm = wb.active
    ws_bm.title = "bm"
    for c, h in enumerate(("BR", "Naziv", "Adresa", "Pun naziv"), start=1):
        ws_bm.cell(row=1, column=c, value=h).font = _BOLD
    for r, (num, name, addr, full) in enumerate(_BMS, start=2):
        ws_bm.cell(row=r, column=1, value=num)
        ws_bm.cell(row=r, column=2, value=name)
        ws_bm.cell(row=r, column=3, value=addr)
        ws_bm.cell(row=r, column=4, value=full)
    for col, w in zip("ABCD", (6, 26, 36, 42)):
        ws_bm.column_dimensions[col].width = w

    ws_r = wb.create_sheet("Raspodela")
    ws_r.cell(row=1, column=1, value="BR BM").font = _BOLD
    for c, func in enumerate(_FUNCTIONS, start=2):
        cell = ws_r.cell(row=1, column=c, value=func)
        cell.font = _BOLD
        cell.alignment = Alignment(wrap_text=True, horizontal="center")
    ws_r.row_dimensions[1].height = 36

    for r, (num, *_) in enumerate(_BMS, start=2):
        ws_r.cell(row=r, column=1, value=num)
        for c, party in enumerate(_RASPODELA[num], start=2):
            cell = ws_r.cell(row=r, column=c, value=party)
            cell.fill = _PARTY_FILLS.get(party, PatternFill())
            cell.alignment = Alignment(horizontal="center")

    ws_r.column_dimensions["A"].width = 8
    for ci in range(2, 2 + len(_FUNCTIONS)):
        ws_r.column_dimensions[get_column_letter(ci)].width = 18

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path


def generate_stranke(out_path: Path) -> Path:
    """Party list for election config import."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "parties"
    for c, h in enumerate(("Kratki naziv", "Pun naziv", "E-posta", "Telefon"), start=1):
        ws.cell(row=1, column=c, value=h).font = _BOLD
    for r, (abbrev, full) in enumerate(_PARTIES.items(), start=2):
        ws.cell(row=r, column=1, value=abbrev)
        ws.cell(row=r, column=2, value=full)
        ws.cell(row=r, column=3, value=_PARTY_EMAILS.get(abbrev, ""))
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 16
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path


def generate_candidacies(out_path: Path) -> Path:
    """Entities + candidates for Prosireni election config import."""
    wb = openpyxl.Workbook()

    ws_e = wb.active
    ws_e.title = "Ентитети"
    entity_hdrs = (
        "ID листе", "Назив", "Тип", "Ниво",
        "Редни бр. подношења", "Повезано са",
    )
    for c, h in enumerate(entity_hdrs, start=1):
        ws_e.cell(row=1, column=c, value=h).font = _BOLD
    for r, (eid, name, etype, order, linked) in enumerate(_ENTITIES, start=2):
        ws_e.cell(row=r, column=1, value=eid)
        ws_e.cell(row=r, column=2, value=name)
        ws_e.cell(row=r, column=3, value=etype)
        ws_e.cell(row=r, column=4, value="local")
        ws_e.cell(row=r, column=5, value=order)
        ws_e.cell(row=r, column=6, value=linked)
    for col, w in zip("ABCDEF", (20, 56, 22, 14, 10, 20)):
        ws_e.column_dimensions[col].width = w

    ws_c = wb.create_sheet("Кандидати")
    cand_hdrs = ("ID листе", "Име и презиме", "ЈМБГ")
    for c, h in enumerate(cand_hdrs, start=1):
        ws_c.cell(row=1, column=c, value=h).font = _BOLD
    for r, (eid, name, jmbg) in enumerate(_CANDIDATES, start=2):
        ws_c.cell(row=r, column=1, value=eid)
        ws_c.cell(row=r, column=2, value=name)
        # Leading apostrophe forces Excel to treat 13-digit string as text
        ws_c.cell(row=r, column=3, value=f"'{jmbg}")
    ws_c.column_dimensions["A"].width = 20
    ws_c.column_dimensions["B"].width = 32
    ws_c.column_dimensions["C"].width = 16
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path


def generate_member_reference(out_path: Path) -> Path:
    """Per-party fill-in guide: one sheet per party, rows = BM / function / person."""
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    bm_by_num = {bm[0]: bm for bm in _BMS}
    first = True

    for party, assignments in _ASSIGNMENTS.items():
        ws = wb.active if first else wb.create_sheet(party)
        if first:
            ws.title = party
            first = False

        hdrs = ["BM br.", "BM naziv", "Funkcija", "Ime", "Prezime",
                "JMBG", "Mesto", "Adresa", "Telefon", "E-posta"]
        for c, h in enumerate(hdrs, start=1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = Alignment(horizontal="center")
        ws.row_dimensions[1].height = 24

        members = _MEMBERS[party]
        for r, (bm_num, func_idx, mem_idx) in enumerate(
            sorted(assignments, key=lambda x: (x[0], x[1])), start=2
        ):
            bm_info = bm_by_num[bm_num]
            m = members[mem_idx]
            ws.cell(row=r, column=1, value=bm_num)
            ws.cell(row=r, column=2, value=bm_info[1])
            ws.cell(row=r, column=3, value=_FUNCTIONS[func_idx])
            ws.cell(row=r, column=4, value=m[0])
            ws.cell(row=r, column=5, value=m[1])
            ws.cell(row=r, column=6, value=f"'{m[2]}")
            ws.cell(row=r, column=7, value=m[3])
            ws.cell(row=r, column=8, value=m[4])
            ws.cell(row=r, column=9, value=m[5])
            ws.cell(row=r, column=10, value=m[6])
            fill = _PARTY_FILLS.get(party, PatternFill())
            for ci in range(1, 11):
                ws.cell(row=r, column=ci).fill = fill

        for ci, w in enumerate([6, 22, 22, 14, 16, 16, 18, 26, 14, 26], start=1):
            ws.column_dimensions[get_column_letter(ci)].width = w

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path


def generate_observer_reference(out_path: Path) -> Path:
    """Observer reference list for manual entry in Posmatraci tab."""
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    ws_o = wb.active
    ws_o.title = "Organizacije"
    for c, h in enumerate(("Naziv", "Vrsta (domaca/strana)", "Kontakt"), start=1):
        ws_o.cell(row=1, column=c, value=h).font = _BOLD
    for r, (name, otype, contact) in enumerate(_OBSERVER_ORGS, start=2):
        ws_o.cell(row=r, column=1, value=name)
        ws_o.cell(row=r, column=2, value=otype)
        ws_o.cell(row=r, column=3, value=contact)
    ws_o.column_dimensions["A"].width = 44
    ws_o.column_dimensions["B"].width = 18
    ws_o.column_dimensions["C"].width = 32

    ws_p = wb.create_sheet("Posmatraci")
    obs_hdrs = ["Organizacija", "Ime", "Prezime", "Drzavljanstvo",
                "Rasp. BM", "JMBG", "Vrsta str.dokumenta", "Br. str.dokumenta"]
    for c, h in enumerate(obs_hdrs, start=1):
        cell = ws_p.cell(row=1, column=c, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    ws_p.row_dimensions[1].height = 32

    for r, (org, first, last, cit, bm, jmbg, doc_type, doc_num) in enumerate(_OBSERVERS, start=2):
        ws_p.cell(row=r, column=1, value=org)
        ws_p.cell(row=r, column=2, value=first)
        ws_p.cell(row=r, column=3, value=last)
        ws_p.cell(row=r, column=4, value=cit)
        ws_p.cell(row=r, column=5, value=bm)
        ws_p.cell(row=r, column=6, value=f"'{jmbg}" if jmbg else "")
        ws_p.cell(row=r, column=7, value=doc_type)
        ws_p.cell(row=r, column=8, value=doc_num)

    for ci, w in enumerate([44, 12, 14, 12, 14, 16, 22, 20], start=1):
        ws_p.column_dimensions[get_column_letter(ci)].width = w

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path


# ── Public API ────────────────────────────────────────────────────────

def generate_all(out_dir: Path) -> list[Path]:
    """Generate all five demo fixture files into *out_dir*.

    Returns the list of created file paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return [
        generate_sablon(out_dir / "sablon_stalni.xlsx"),
        generate_stranke(out_dir / "stranke.xlsx"),
        generate_candidacies(out_dir / "candidacies_prosireni.xlsx"),
        generate_member_reference(out_dir / "clanovi_referenca.xlsx"),
        generate_observer_reference(out_dir / "posmatraci_referenca.xlsx"),
    ]
