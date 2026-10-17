"""Tests for A3 — Candidacies registry data model + Excel I/O.

Covers:
  - Entity / Candidate / CandidaciesRegistry to_dict / from_dict.
  - Registry lookup helpers (entity_by_id, candidates_for_entity,
    jmbg_index).
  - ElectionConfig integration: round-trip preserves candidacies;
    legacy configs (pre-A3) without the field load as empty registry.
  - Excel round-trip (build → read) preserves every field byte-for-byte.
  - Excel error surfacing: wrong headers, bad level, missing sheet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.config.candidacies import (
    Candidate, CandidaciesRegistry, ENTITY_TYPES, Entity, LEVEL_KEYS,
    LEVEL_PRIORITY,
)
from biracki_odbor.config.election import ElectionConfig


# ── Vocabulary sanity checks ──────────────────────────────────────


def test_level_keys_align_with_priority_map() -> None:
    """Every level in LEVEL_KEYS must have a priority value, and vice
    versa — protects against renames that touch only one side."""
    assert set(LEVEL_KEYS) == set(LEVEL_PRIORITY.keys())


def test_level_priority_presidential_highest() -> None:
    """Plan §1.2 — presidential > parliamentary > provincial > local.
    Lower number = higher priority."""
    assert (
        LEVEL_PRIORITY["presidential"]
        < LEVEL_PRIORITY["parliamentary"]
        < LEVEL_PRIORITY["provincial"]
        < LEVEL_PRIORITY["local"]
    )


def test_entity_types_canonical_set() -> None:
    """The four operator-selectable types — kept in sync with the
    plan §1.1 vocabulary."""
    assert set(ENTITY_TYPES) == {
        "party", "coalition", "group_of_citizens",
    }


# ── Dataclass round-trip ──────────────────────────────────────────


def test_entity_round_trip_preserves_all_fields() -> None:
    e = Entity(
        entity_id="sns-pres",
        name="СНС - Александар Вучић",
        entity_type="coalition",
        level="presidential",
        submission_order=1,
        linked_to_entity_id="",
    )
    rt = Entity.from_dict(e.to_dict())
    assert rt == e


def test_entity_email_phone_round_trip() -> None:
    """A list's own contact info — separate from ElectionConfig.
    party_contacts (стали RIK-party contacts) — must survive save/load,
    the same as every other field. Used by Phase 1's Send flow
    (ProsireniPhase1Tab._send_recipients)."""
    e = Entity(
        entity_id="moja-lista-local", name="Моја листа", entity_type="party",
        level="local", submission_order=1, email="lista@example.rs", phone="060-123",
    )
    rt = Entity.from_dict(e.to_dict())
    assert rt.email == "lista@example.rs"
    assert rt.phone == "060-123"
    assert rt == e


def test_entity_slot_index_round_trips() -> None:
    """slot_index must survive save/load -- it's the whole point of the
    stability fix (see test_prosireni_allocation.py): an in-memory-only
    assignment that resets to 0 on next load would defeat it entirely."""
    e = Entity(
        entity_id="sns-loc", name="СНС Уб", entity_type="party",
        level="local", submission_order=1, slot_index=3,
    )
    rt = Entity.from_dict(e.to_dict())
    assert rt.slot_index == 3
    assert rt == e


def test_entity_from_dict_coerces_missing_fields() -> None:
    """A dict with missing keys must produce default values, not raise —
    so a hand-edited election_config.json with sparse data still loads."""
    rt = Entity.from_dict({"entity_id": "x"})
    assert rt.entity_id == "x"
    assert rt.name == ""
    assert rt.submission_order == 0
    # A pre-slot_index saved config (no such key at all) must load as
    # "unassigned", not error -- canonical_slots() treats 0 as the
    # signal to assign fresh.
    assert rt.slot_index == 0
    # Same for a pre-contact-info config: no email/phone keys at all,
    # not just empty strings.
    assert rt.email == ""
    assert rt.phone == ""


def test_candidate_round_trip() -> None:
    c = Candidate(
        name="Ана Анић",
        jmbg="1605991774818",
        endorsed_by_entity_id="sns-pres",
    )
    assert Candidate.from_dict(c.to_dict()) == c


def test_registry_round_trip() -> None:
    """Whole-registry serialization must preserve order and field
    contents — order matters because slot index later derives from it."""
    reg = CandidaciesRegistry(
        entities=[
            Entity("e1", "Entity 1", "party", "presidential", 1),
            Entity("e2", "Entity 2", "party", "local", 2),
        ],
        candidates=[
            Candidate("Person A", "1605991774818", "e1"),
            Candidate("Person B", "2706994779807", "e2"),
        ],
    )
    rt = CandidaciesRegistry.from_dict(reg.to_dict())
    assert [e.entity_id for e in rt.entities] == ["e1", "e2"]
    assert [c.jmbg for c in rt.candidates] == [
        "1605991774818", "2706994779807",
    ]


def test_registry_from_dict_handles_empty_dict() -> None:
    """An empty dict must produce a fresh empty registry — defensive
    guard for legacy election_config.json files."""
    rt = CandidaciesRegistry.from_dict({})
    assert rt.entities == []
    assert rt.candidates == []


def test_registry_from_dict_skips_non_dict_rows() -> None:
    """Malformed entries (e.g. a stray string in the entities list)
    must be silently dropped — don't fail-closed on a hand-edited file."""
    rt = CandidaciesRegistry.from_dict({
        "entities": [{"entity_id": "ok"}, "garbage", 42],
        "candidates": ["also garbage"],
    })
    assert len(rt.entities) == 1
    assert rt.entities[0].entity_id == "ok"
    assert rt.candidates == []


# ── Lookup helpers ────────────────────────────────────────────────


def test_entity_by_id() -> None:
    reg = CandidaciesRegistry(entities=[
        Entity("e1", "E1", "party", "presidential", 1),
        Entity("e2", "E2", "party", "local", 2),
    ])
    assert reg.entity_by_id("e1").name == "E1"
    assert reg.entity_by_id("missing") is None


def test_candidates_for_entity_preserves_order() -> None:
    reg = CandidaciesRegistry(candidates=[
        Candidate("First", "1", "e1"),
        Candidate("Other", "2", "e2"),
        Candidate("Third", "3", "e1"),
    ])
    e1_cands = reg.candidates_for_entity("e1")
    assert [c.name for c in e1_cands] == ["First", "Third"]


def test_jmbg_index_dedupes_and_strips() -> None:
    """Empty JMBGs (rare, but seen in partial entries) must NOT land
    in the index — Phase B1 uses this as a "running for office" set
    and an empty entry would block every committee member with no JMBG."""
    reg = CandidaciesRegistry(candidates=[
        Candidate("A", "1605991774818", "e1"),
        Candidate("B", "", "e2"),
        Candidate("C", "  2706994779807  ", "e3"),  # whitespace
    ])
    idx = reg.jmbg_index()
    assert idx == {"1605991774818", "2706994779807"}


# ── ElectionConfig integration ────────────────────────────────────


def test_election_config_serializes_candidacies() -> None:
    ec = ElectionConfig()
    ec.candidacies.entities.append(
        Entity("sns-pres", "СНС", "coalition", "presidential", 1),
    )
    d = ec.to_dict()
    assert "candidacies" in d
    assert d["candidacies"]["entities"][0]["name"] == "СНС"


def test_election_config_legacy_loads_empty_registry() -> None:
    """Pre-A3 election_config.json files don't carry the 'candidacies'
    key. The loader must default to an empty registry rather than
    raising — operators don't get forced to migrate."""
    rt = ElectionConfig.from_dict({})
    assert rt.candidacies.entities == []
    assert rt.candidacies.candidates == []


def test_election_config_round_trip_preserves_candidacies() -> None:
    ec = ElectionConfig()
    ec.candidacies.entities.append(
        Entity("e1", "E1", "party", "presidential", 1),
    )
    ec.candidacies.candidates.append(
        Candidate("Person", "1605991774818", "e1"),
    )
    rt = ElectionConfig.from_dict(ec.to_dict())
    assert rt.candidacies.entities[0].entity_id == "e1"
    assert rt.candidacies.candidates[0].jmbg == "1605991774818"


# ── Excel I/O round-trip ──────────────────────────────────────────


@pytest.fixture
def tmp_xlsx(tmp_path: Path) -> Path:
    return tmp_path / "candidacies.xlsx"


def test_excel_round_trip_preserves_everything(tmp_xlsx: Path) -> None:
    """Build → read round-trip must yield a registry equal to the
    source. This is the contract Phase C's UI will rely on for export
    + re-import."""
    from biracki_odbor.core.template import (
        build_candidacies_workbook, read_candidacies_workbook,
    )
    src = CandidaciesRegistry(
        entities=[
            Entity("sns-pres", "СНС - Александар Вучић", "coalition",
                   "presidential", 1, ""),
            Entity("sps-loc", "СПС Уб", "party", "local", 3, ""),
        ],
        candidates=[
            Candidate("Ана Анић", "1605991774818", "sns-pres"),
            Candidate("Бора Борић", "2706994779807", "sps-loc"),
        ],
    )
    build_candidacies_workbook(src, tmp_xlsx)
    rt, errors = read_candidacies_workbook(tmp_xlsx)
    assert errors == []
    assert rt == src


def test_excel_read_rejects_wrong_first_sheet(tmp_xlsx: Path) -> None:
    """A workbook without an 'Ентитети' sheet must fail closed, not
    silently produce an empty registry — that's the misclick guard."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "wrong"
    wb.save(tmp_xlsx)
    wb.close()
    from biracki_odbor.core.template import read_candidacies_workbook
    rt, errors = read_candidacies_workbook(tmp_xlsx)
    assert rt.entities == []
    assert any("Ентитети" in e for e in errors)


def test_excel_read_surfaces_bad_level_value(tmp_xlsx: Path) -> None:
    """A row with a level value not in LEVEL_KEYS must still load (so
    the operator can fix it on the next pass) but surface a Cyrillic
    error message."""
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ентитети"
    headers = ("ID листе", "Назив", "Тип", "Ниво",
               "Редни бр. подношења", "Повезано са")
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
    ws.cell(row=2, column=1, value="e1")
    ws.cell(row=2, column=2, value="Entity")
    ws.cell(row=2, column=3, value="party")
    ws.cell(row=2, column=4, value="federal")  # not in LEVEL_KEYS
    ws.cell(row=2, column=5, value=1)
    wb.create_sheet("Кандидати")
    wb.save(tmp_xlsx)
    wb.close()
    from biracki_odbor.core.template import read_candidacies_workbook
    rt, errors = read_candidacies_workbook(tmp_xlsx)
    assert len(rt.entities) == 1  # row still loaded
    assert any("Ниво" in e and "federal" in e for e in errors)


def test_excel_jmbg_int_form_padded(tmp_xlsx: Path) -> None:
    """JMBGs starting with leading zero stored as Excel numbers lose
    the zero. The reader must pad back to 13 digits via the canonical
    jmbg.normalize helper so cross-checks find them later."""
    import openpyxl
    from openpyxl.styles import Font
    from biracki_odbor.core.template import read_candidacies_workbook
    wb = openpyxl.Workbook()
    ws_e = wb.active
    ws_e.title = "Ентитети"
    for c, h in enumerate(("ID листе", "Назив", "Тип", "Ниво",
                           "Редни бр. подношења", "Повезано са"), start=1):
        cell = ws_e.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
    ws_e.cell(row=2, column=1, value="e1")
    ws_e.cell(row=2, column=2, value="E1")
    ws_e.cell(row=2, column=3, value="party")
    ws_e.cell(row=2, column=4, value="presidential")
    ws_e.cell(row=2, column=5, value=1)
    ws_c = wb.create_sheet("Кандидати")
    for c, h in enumerate(("ID листе", "Име и презиме", "ЈМБГ"), start=1):
        cell = ws_c.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True)
    ws_c.cell(row=2, column=1, value="e1")
    ws_c.cell(row=2, column=2, value="Person")
    # Pick a JMBG with leading zero and store as integer (Excel's
    # native numeric type).
    ws_c.cell(row=2, column=3, value=506008770010)  # leads with 0
    wb.save(tmp_xlsx)
    wb.close()
    rt, errors = read_candidacies_workbook(tmp_xlsx)
    assert rt.candidates[0].jmbg == "0506008770010"


# ── build_entities_template — «Generate template…» button ─────────


def test_template_blank_shows_hint_rows_and_all_levels(tmp_xlsx: Path) -> None:
    """No registry passed -> still the old fill-in-the-blanks behavior,
    with a dropdown covering every level (no cycle info to narrow it)."""
    import openpyxl
    from biracki_odbor.core.template import build_entities_template

    build_entities_template(tmp_xlsx)
    wb = openpyxl.load_workbook(tmp_xlsx)
    ws = wb["Листе"]
    assert ws.cell(row=1, column=6).value == "Повезано са"
    assert ws.cell(row=2, column=2).value  # hint row present
    dv_ranges = {str(r) for dv in ws.data_validations.dataValidation for r in dv.sqref.ranges}
    assert "C2:C1000" in dv_ranges  # Тип dropdown
    assert "D2:D1000" in dv_ranges  # Ниво dropdown
    lookup = wb["_lookup"]
    assert lookup.sheet_state == "hidden"
    levels_in_lookup = [lookup.cell(row=r, column=2).value for r in range(1, 5)]
    assert levels_in_lookup == list(LEVEL_KEYS)
    wb.close()


def test_template_with_registry_writes_actual_rows_not_hints(tmp_xlsx: Path) -> None:
    """Field report: 'Generate template' silently dropped lists the
    operator already entered manually instead of including them."""
    import openpyxl
    from biracki_odbor.core.template import build_entities_template

    reg = CandidaciesRegistry(
        entities=[Entity("sns-loc", "СНС Уб", "party", "local", 1, "")],
        candidates=[Candidate("Ана Анић", "1234567890123", "sns-loc")],
    )
    build_entities_template(tmp_xlsx, registry=reg)
    wb = openpyxl.load_workbook(tmp_xlsx)
    ws = wb["Листе"]
    assert ws.cell(row=2, column=1).value == "sns-loc"
    assert ws.cell(row=2, column=2).value == "СНС Уб"
    # No leftover grey hint row once real data exists.
    assert ws.cell(row=3, column=1).value is None
    wb.close()


def test_template_has_no_candidates_sheet(tmp_xlsx: Path) -> None:
    """The «Увези листе» reader paired with this template
    (read_entities_sheet) only ever reads the first sheet -- a
    candidates sheet here would silently promise something this import
    path never delivers. Candidates have their own file
    (build_candidacies_workbook)."""
    import openpyxl
    from biracki_odbor.core.template import build_entities_template

    reg = CandidaciesRegistry(
        entities=[Entity("sns-loc", "СНС Уб", "party", "local", 1, "")],
        candidates=[Candidate("Ана Анић", "1234567890123", "sns-loc")],
    )
    build_entities_template(tmp_xlsx, registry=reg)
    wb = openpyxl.load_workbook(tmp_xlsx)
    assert "Кандидати" not in wb.sheetnames
    assert wb.sheetnames == ["Листе", "_lookup"]
    wb.close()


def test_candidacies_workbook_hides_entities_sheet_and_opens_on_candidates(
    tmp_xlsx: Path,
) -> None:
    """The «kandidati.xlsx» export is candidate-entry-focused -- the
    Ентитети sheet exists only to back the ID-листе dropdown, so it's
    hidden and Кандидати is the sheet the operator actually sees."""
    import openpyxl
    from biracki_odbor.core.template import build_candidacies_workbook

    reg = CandidaciesRegistry(
        entities=[
            Entity("sns-loc", "СНС Уб", "party", "local", 1, ""),
            Entity("sps-loc", "СПС Уб", "party", "local", 2, ""),
        ],
        candidates=[Candidate("Ана Анић", "1234567890123", "sns-loc")],
    )
    build_candidacies_workbook(reg, tmp_xlsx)
    wb = openpyxl.load_workbook(tmp_xlsx)
    assert wb["Ентитети"].sheet_state == "hidden"
    assert wb["Кандидати"].sheet_state == "visible"
    assert wb.active.title == "Кандидати"
    ws_c = wb["Кандидати"]
    dv_ranges = {str(r) for dv in ws_c.data_validations.dataValidation for r in dv.sqref.ranges}
    assert "A2:A1000" in dv_ranges
    wb.close()


def test_candidacies_workbook_no_dropdown_when_no_entities(tmp_xlsx: Path) -> None:
    import openpyxl
    from biracki_odbor.core.template import build_candidacies_workbook

    build_candidacies_workbook(CandidaciesRegistry(), tmp_xlsx)
    wb = openpyxl.load_workbook(tmp_xlsx)
    ws_c = wb["Кандидати"]
    assert len(ws_c.data_validations.dataValidation) == 0
    wb.close()


def test_template_available_levels_narrows_dropdown(tmp_xlsx: Path) -> None:
    """A cycle with only local elections configured shouldn't make the
    operator pick "local" from a 4-option dropdown every single row."""
    import openpyxl
    from biracki_odbor.core.template import build_entities_template

    build_entities_template(tmp_xlsx, available_levels=["local"])
    wb = openpyxl.load_workbook(tmp_xlsx)
    lookup = wb["_lookup"]
    levels = [lookup.cell(row=r, column=2).value for r in range(1, 3)]
    assert levels == ["local", None]
    wb.close()


def test_template_hides_linked_column_for_single_level_cycle(tmp_xlsx: Path) -> None:
    """Cross-level linking is meaningless with only one election level
    active this cycle -- the column should disappear, not sit there
    doing nothing."""
    import openpyxl
    from biracki_odbor.core.template import build_entities_template

    build_entities_template(tmp_xlsx, show_linked_column=False)
    wb = openpyxl.load_workbook(tmp_xlsx)
    ws = wb["Листе"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, 7)]
    assert headers == ["ID листе", "Назив", "Тип", "Ниво", "Редни бр. подношења", None]
    wb.close()


def test_template_entities_import_round_trips_through_read_entities_sheet(
    tmp_xlsx: Path,
) -> None:
    """The populated template must be re-importable via the lenient
    'Увези листе' reader, not just human-readable."""
    from biracki_odbor.core.template import build_entities_template, read_entities_sheet

    reg = CandidaciesRegistry(
        entities=[
            Entity("sns-loc", "СНС Уб", "party", "local", 1, ""),
            Entity("sps-loc", "СПС Уб", "coalition", "local", 2, "sns-loc"),
        ],
    )
    build_entities_template(tmp_xlsx, registry=reg)
    read_back, errors = read_entities_sheet(tmp_xlsx)
    assert errors == []
    assert [e.entity_id for e in read_back] == ["sns-loc", "sps-loc"]
    assert read_back[1].linked_to_entity_id == "sns-loc"
