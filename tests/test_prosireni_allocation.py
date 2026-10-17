"""Tests for Phase E — prosireni_allocation.py.

Covers:
  - `canonical_entity()` returns the entity at the highest level in the
    link group (mirrors canonical_entity_name behaviour but returns Entity).
  - `canonical_slots()` deduplicates linked entities and sorts by
    (level_priority, submission_order, entity_id).
  - `build_prosireni_allocation()` produces 2 slots per canonical entity
    per BM in the correct function-string format.
  - `parse_slot_function()` / `func_sort_key()` parse and sort correctly.
  - Phase D backward compat: `aggregate_party_files()` still accepts
    `template_path` for stalni (no regression).
  - E3 dedup: `aggregate_party_files()` with `allocations_override` works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.config.candidacies import (
    Candidate, CandidaciesRegistry, Entity,
    canonical_entity,
)
from biracki_odbor.core.prosireni_allocation import (
    MEMBER_LABEL, SUBSTITUTE_LABEL,
    CanonicalSlot, build_prosireni_allocation, canonical_slots,
    func_sort_key, parse_slot_function, slot_function,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _e(eid: str, level: str, order: int = 1, linked_to: str = "") -> Entity:
    return Entity(
        entity_id=eid, name=f"Ентитет {eid}",
        entity_type="party", level=level,
        submission_order=order, linked_to_entity_id=linked_to,
    )


def _registry(*entities: Entity, candidates: list[Candidate] | None = None) -> CandidaciesRegistry:
    return CandidaciesRegistry(
        entities=list(entities),
        candidates=candidates or [],
    )


# ── canonical_entity() ────────────────────────────────────────────────


def test_canonical_entity_standalone() -> None:
    """Standalone entity is its own canonical."""
    e = _e("e1", "local")
    assert canonical_entity(e, [e]).entity_id == "e1"


def test_canonical_entity_higher_level_wins() -> None:
    """Parliamentary beats local — canonical is the parliamentary entity."""
    parl = _e("sns-parl", "parliamentary")
    loc = _e("sns-loc", "local", linked_to="sns-parl")
    # Querying from either side returns parliamentary.
    assert canonical_entity(loc, [parl, loc]).entity_id == "sns-parl"
    assert canonical_entity(parl, [parl, loc]).entity_id == "sns-parl"


def test_canonical_entity_presidential_wins_chain() -> None:
    pres = _e("sns-pres", "presidential")
    parl = _e("sns-parl", "parliamentary", linked_to="sns-pres")
    loc = _e("sns-loc", "local", linked_to="sns-parl")
    assert canonical_entity(loc, [pres, parl, loc]).entity_id == "sns-pres"


def test_canonical_entity_dangling_link_returns_self() -> None:
    orphan = _e("e1", "local", linked_to="missing")
    assert canonical_entity(orphan, [orphan]).entity_id == "e1"


def test_canonical_entity_cycle_safe() -> None:
    a = _e("a", "presidential", linked_to="b")
    b = _e("b", "local", linked_to="a")
    # Presidential wins regardless of cycle direction.
    result = canonical_entity(b, [a, b])
    assert result.entity_id == "a"


# ── slot_function / parse_slot_function / func_sort_key ──────────────


def test_slot_function_format() -> None:
    assert slot_function(MEMBER_LABEL, 1) == "Члан [1]"
    assert slot_function(SUBSTITUTE_LABEL, 3) == "Заменик члана [3]"


def test_parse_slot_function_member() -> None:
    assert parse_slot_function("Члан [2]") == (2, 0)


def test_parse_slot_function_substitute() -> None:
    assert parse_slot_function("Заменик члана [5]") == (5, 1)


def test_parse_slot_function_stalni_returns_none() -> None:
    """Stalni function strings should not parse as prosireni slots."""
    assert parse_slot_function("Председник") is None
    assert parse_slot_function("Члан 1") is None


def test_func_sort_key_ordering() -> None:
    """Члан [1] < Заменик члана [1] < Члан [2] < Заменик члана [2]."""
    keys = [
        func_sort_key("Заменик члана [2]"),
        func_sort_key("Члан [1]"),
        func_sort_key("Члан [2]"),
        func_sort_key("Заменик члана [1]"),
    ]
    assert sorted(keys) == [
        (1, 0),   # Члан [1]
        (1, 1),   # Заменик члана [1]
        (2, 0),   # Члан [2]
        (2, 1),   # Заменик члана [2]
    ]


def test_func_sort_key_unknown_falls_back() -> None:
    assert func_sort_key("Председник") == (99, 99)


# ── canonical_slots() ─────────────────────────────────────────────────


def test_canonical_slots_standalone() -> None:
    """One standalone entity → one slot."""
    reg = _registry(_e("e1", "local"))
    slots = canonical_slots(reg)
    assert len(slots) == 1
    assert slots[0].slot_index == 1
    assert slots[0].entity.entity_id == "e1"


def test_canonical_slots_deduplicates_linked_entities() -> None:
    """SNS parliamentary + SNS local → ONE canonical slot (parliamentary)."""
    parl = _e("sns-parl", "parliamentary", order=1)
    loc = _e("sns-loc", "local", order=1, linked_to="sns-parl")
    reg = _registry(parl, loc)
    slots = canonical_slots(reg)
    assert len(slots) == 1
    assert slots[0].entity.entity_id == "sns-parl"


def test_canonical_slots_sort_order_level_priority() -> None:
    """Presidential before parliamentary before local."""
    pres = _e("pres", "presidential", order=1)
    parl = _e("parl", "parliamentary", order=1)
    loc = _e("loc", "local", order=1)
    reg = _registry(pres, parl, loc)
    slots = canonical_slots(reg)
    assert [s.entity.entity_id for s in slots] == ["pres", "parl", "loc"]
    assert [s.slot_index for s in slots] == [1, 2, 3]


def test_canonical_slots_sort_order_submission_order_tie_break() -> None:
    """Same level → lower submission_order gets the lower slot index."""
    a = _e("a", "local", order=2)
    b = _e("b", "local", order=1)
    reg = _registry(a, b)
    slots = canonical_slots(reg)
    assert slots[0].entity.entity_id == "b"
    assert slots[1].entity.entity_id == "a"


def test_canonical_slots_empty_registry() -> None:
    reg = _registry()
    assert canonical_slots(reg) == []


# ── canonical_slots() stability under later registrations ─────────────
#
# Field report (2026-07-30): the law requires OIK to start accepting
# prosireni nominations as soon as the first list registers -- so by
# the time a later list registers, earlier lists may already have
# generated templates, been filled in, and been imported (all keyed by
# their locked "Члан [N]" function string). Slot numbers used to be
# recomputed fresh from a sort every call, which meant a later-
# registering entity landing between two already-slotted ones shifted
# every later entity's number -- and since aggregation matches already-
# imported files by that literal string, the shift silently reattributed
# one list's real submitted members to a DIFFERENT list.


def test_canonical_slots_persists_slot_index_on_the_entity() -> None:
    """First call assigns slot_index and mutates the Entity object in
    place (registry.entities holds the same objects, not copies) --
    callers persist the registry afterward so it sticks."""
    a = _e("a", "local", order=5)
    b = _e("b", "local", order=10)
    reg = _registry(a, b)
    assert a.slot_index == 0 and b.slot_index == 0
    canonical_slots(reg)
    assert a.slot_index == 1
    assert b.slot_index == 2


def test_canonical_slots_does_not_renumber_already_assigned_entities() -> None:
    """The exact corruption scenario: B is already slotted (and, in the
    real flow, already has submitted/imported data under "Члан [2]").
    C registers later with a submission_order that would sort BETWEEN
    A and B under the old fresh-sort behavior. B's slot must not move."""
    a = _e("a", "local", order=5)
    b = _e("b", "local", order=10)
    reg = _registry(a, b)
    canonical_slots(reg)  # a=1, b=2 -- simulates b already having filed data
    assert b.slot_index == 2

    c = _e("c", "local", order=7)  # sorts between a (5) and b (10)
    reg.entities.append(c)
    slots = canonical_slots(reg)

    assert b.slot_index == 2, "B's already-assigned slot must never change"
    assert a.slot_index == 1
    assert c.slot_index == 3, "new entity gets the next free slot, not an in-between one"
    by_id = {s.entity.entity_id: s.slot_index for s in slots}
    assert by_id == {"a": 1, "b": 2, "c": 3}


def test_canonical_slots_repeated_calls_are_idempotent() -> None:
    """Calling canonical_slots() again with no registry changes must not
    reassign anything (e.g. a GUI refresh calling this on every repaint)."""
    a = _e("a", "local", order=1)
    b = _e("b", "local", order=2)
    reg = _registry(a, b)
    canonical_slots(reg)
    first = (a.slot_index, b.slot_index)
    canonical_slots(reg)
    canonical_slots(reg)
    assert (a.slot_index, b.slot_index) == first


def test_canonical_slots_new_entities_still_sort_among_themselves() -> None:
    """Two NEW entities registering in the same batch (neither slotted
    yet) still get ordered by (level, submission_order, entity_id)
    relative to EACH OTHER -- stability only protects entities that
    already have a real slot, not the relative order of fresh ones."""
    a = _e("a", "local", order=1)
    reg = _registry(a)
    canonical_slots(reg)  # a=1
    assert a.slot_index == 1

    c = _e("c", "local", order=9)
    d = _e("d", "local", order=3)
    reg.entities.extend([c, d])
    canonical_slots(reg)
    assert a.slot_index == 1
    assert d.slot_index == 2  # lower submission_order among the new ones
    assert c.slot_index == 3


# ── build_prosireni_allocation() ──────────────────────────────────────


def test_build_two_roles_per_entity_per_bm() -> None:
    """2 canonical entities × 3 BMs → 12 allocations (2 roles each)."""
    reg = _registry(
        _e("e1", "parliamentary", order=1),
        _e("e2", "local", order=1),
    )
    allocs = build_prosireni_allocation(reg, [1, 2, 3])
    assert len(allocs) == 12  # 2 entities × 3 BMs × 2 roles


def test_build_function_strings() -> None:
    """Function column values are compound strings matching slot_function()."""
    reg = _registry(_e("e1", "local"))
    allocs = build_prosireni_allocation(reg, [1])
    funcs = {a.function for a in allocs}
    assert funcs == {"Члан [1]", "Заменик члана [1]"}


def test_build_party_is_canonical_entity_id() -> None:
    """Allocation.party carries the canonical entity's short entity_id,
    not its (potentially long) display name — an operational matching
    key, same convention as stalni's party abbreviation. The full name
    is resolved separately, only where a human actually reads it (the
    generated file's title, decision-document proposal text) via
    canonical_entity_name() / ElectionConfig.party_full_name()."""
    parl = Entity(
        entity_id="sns-parl", name="СНС — парламент",
        entity_type="party", level="parliamentary",
        submission_order=1, linked_to_entity_id="",
    )
    loc = Entity(
        entity_id="sns-loc", name="СНС — локал",
        entity_type="party", level="local",
        submission_order=1, linked_to_entity_id="sns-parl",
    )
    reg = CandidaciesRegistry(entities=[parl, loc], candidates=[])
    allocs = build_prosireni_allocation(reg, [1])
    # One canonical entity (parl), so 2 allocations.
    assert len(allocs) == 2
    for a in allocs:
        # canonical_entity() picks parl (higher level) → its entity_id.
        assert a.party == "sns-parl"


def test_build_slot_indices_per_entity() -> None:
    """Two standalone entities get slot_index 1 and 2 respectively."""
    e1 = _e("pres", "presidential", order=1)
    e2 = _e("loc", "local", order=1)
    reg = _registry(e1, e2)
    allocs = build_prosireni_allocation(reg, [1])
    by_func = {a.function: a for a in allocs}
    assert "Члан [1]" in by_func
    assert "Члан [2]" in by_func
    assert by_func["Члан [1]"].party == "pres"
    assert by_func["Члан [2]"].party == "loc"


def test_build_allocation_function_strings_survive_later_registration() -> None:
    """One level up from canonical_slots(): the actual function strings
    build_prosireni_allocation() hands to Phase 1 generation and
    aggregation must not change for an already-slotted entity just
    because a new one registers later. This is what "Члан [2]" baked
    into B's already-generated/already-submitted file must keep meaning."""
    a = _e("a", "local", order=5)
    b = _e("b", "local", order=10)
    reg = _registry(a, b)
    allocs1 = build_prosireni_allocation(reg, [1])
    by_func1 = {a.function: a.party for a in allocs1}
    assert by_func1["Члан [1]"] == "a"
    assert by_func1["Члан [2]"] == "b"

    c = _e("c", "local", order=7)  # sorts between a and b
    reg.entities.append(c)
    allocs2 = build_prosireni_allocation(reg, [1])
    by_func2 = {a.function: a.party for a in allocs2}
    assert by_func2["Члан [1]"] == "a"
    assert by_func2["Члан [2]"] == "b", (
        "b's slot must stay 'Члан [2]' -- otherwise aggregation would "
        "match b's already-imported data against c's allocation and "
        "silently relabel b's real submitted members as belonging to c"
    )
    assert by_func2["Члан [3]"] == "c"


def test_build_empty_registry_returns_empty() -> None:
    reg = _registry()
    assert build_prosireni_allocation(reg, [1, 2]) == []


def test_build_bm_numbers_sorted() -> None:
    """Output is sorted by (slot_index, bm_number) — BM 1 before BM 3."""
    reg = _registry(_e("e1", "local"))
    allocs = build_prosireni_allocation(reg, [3, 1, 2])
    bm_seq = [a.bm_number for a in allocs[::2]]  # every other = Члан rows
    assert bm_seq == [1, 2, 3]


# ── E4: app_paths spec-aware helpers ─────────────────────────────────


def test_app_paths_spec_helpers_exist() -> None:
    """Smoke: spec-aware helpers are importable and callable."""
    import os, tempfile
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BIRACKI_ODBOR_HOME"] = tmp
        try:
            p_stalni = app_paths.popunjeni_dir_for(STALNI_SPEC)
            p_prosireni = app_paths.popunjeni_dir_for(PROSIRENI_SPEC)
            assert p_stalni != p_prosireni
            assert "prosireni" in str(p_prosireni)
            # Both workflows share one committee DB now (see core/master_io.py).
            assert app_paths.master_path_for(PROSIRENI_SPEC) == app_paths.master_path_for(STALNI_SPEC)
            assert app_paths.master_path_for(PROSIRENI_SPEC).name == "committee.db"
            assert (
                app_paths.legacy_xlsx_master_path_for(PROSIRENI_SPEC).name
                == "zbirana_tabela_prosireni.xlsx"
            )
        finally:
            del os.environ["BIRACKI_ODBOR_HOME"]


# ── E3: aggregate_party_files with allocations_override ──────────────


def test_aggregate_with_allocations_override(tmp_path: Path) -> None:
    """aggregate_party_files(template_path=None, allocations_override=...)
    skips template reading and uses the provided allocations directly.
    This is the prosireni aggregate path.
    Verify: output master is written even with zero popunjeni files."""
    from biracki_odbor.config.oik import OikConstants, PollingStation as OikPS
    from biracki_odbor.core.models import Allocation
    from biracki_odbor.core.phase2_aggregate import aggregate_party_files
    from biracki_odbor.core.workflow import PROSIRENI_SPEC

    oik = OikConstants(polling_stations=[
        OikPS(bm_number=1, name="БМ1", full_name="Бирачко место 1"),
    ])
    allocs = [
        Allocation(bm_number=1, function="Члан [1]", party="СНС"),
        Allocation(bm_number=1, function="Заменик члана [1]", party="СНС"),
    ]
    popunjeni_dir = tmp_path / "popunjeni_prosireni"
    popunjeni_dir.mkdir()
    master_out = tmp_path / "master_prosireni" / "zbirana_tabela_prosireni.xlsx"

    result = aggregate_party_files(
        input_dir=popunjeni_dir,
        template_path=None,
        output_path=master_out,
        oik=oik,
        spec=PROSIRENI_SPEC,
        allocations_override=allocs,
    )

    assert master_out.exists(), "master xlsx should be written"
    # With no popunjeni files, persons are all unfilled but present.
    assert len(result.persons) == 2
    assert all(not p.is_filled for p in result.persons)


# ── generate_entity_files() demo-mode limit ────────────────────────────


def test_generate_entity_files_demo_mode_restricts_to_one_bm(tmp_path: Path) -> None:
    """Field report: prosireni had NO demo limit at all -- generate_party_files
    (stalni) restricts demo output to a single BM, but generate_entity_files
    ignored demo_mode entirely, so a demo user could collect a full
    committee for every BM through the prosireni workflow regardless of
    the stalni-side limit."""
    from biracki_odbor.config.oik import OikConstants, PollingStation as OikPS
    from biracki_odbor.core.phase1_generate import generate_entity_files
    from biracki_odbor.validation.reports import Codes

    reg = _registry(_e("ent1", "local", order=1))
    oik = OikConstants(polling_stations=[
        OikPS(bm_number=1, name="БМ1", full_name="Бирачко место 1"),
        OikPS(bm_number=2, name="БМ2", full_name="Бирачко место 2"),
    ])
    result = generate_entity_files(
        registry=reg, bm_numbers=[1, 2], output_dir=tmp_path / "out",
        oik=oik, demo_mode=True,
    )
    assert result.files_written
    codes = {i.code for i in result.report.issues}
    assert Codes.DEMO_MODE_LIMIT in codes

    import openpyxl
    wb = openpyxl.load_workbook(result.files_written[0])
    ws = wb.active
    assert ws.cell(row=3, column=2).value == "БМ бр.", "column layout assumption broken"
    bm_values = {
        ws.cell(row=r, column=2).value
        for r in range(4, ws.max_row + 1)
        if ws.cell(row=r, column=2).value is not None
    }
    wb.close()
    assert bm_values == {1}, "demo mode must restrict prosireni output to a single BM"


# ── Cross-workflow JMBG duplicate check ────────────────────────────────


def test_prosireni_aggregation_rejects_jmbg_already_in_stalni_master(tmp_path, monkeypatch) -> None:
    """Field report: a person already holding a filled стални committee
    seat could also be appointed in проширени -- aggregate_party_files
    never checked the JMBG against the OTHER workflow's master at all."""
    import openpyxl
    from biracki_odbor import app_paths
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.core.models import Allocation, Person
    from biracki_odbor.core.phase2_aggregate import aggregate_party_files
    from biracki_odbor.core.phase1_generate import generate_entity_files
    from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
    from biracki_odbor.validation.reports import Codes
    from tests.test_jmbg import VALID_SAMPLES
    from tests.test_phase1 import _make_oik

    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    shared_jmbg = VALID_SAMPLES[0]

    # Стални already has this person filled in a real committee seat.
    write_master(
        [Person(bm_number=1, function="Председник", party="СНС",
                first_name="Ана", last_name="Анић", jmbg=shared_jmbg)],
        _make_oik(1), app_paths.master_path_for(STALNI_SPEC),
    )

    # Проширени: generate a real template, fill it in with the SAME JMBG.
    reg = _registry(_e("ent1", "local", order=1))
    result = generate_entity_files(
        registry=reg, bm_numbers=[1], output_dir=tmp_path / "sablon_prosireni",
        oik=_make_oik(1),
    )
    tpl_file = result.files_written[0]
    wb = openpyxl.load_workbook(tpl_file)
    ws = wb.active
    ws.cell(row=4, column=5, value="Пера")
    ws.cell(row=4, column=6, value="Перић")
    ws.cell(row=4, column=7, value=shared_jmbg)
    wb.save(tpl_file)
    wb.close()

    allocs = [
        Allocation(bm_number=1, function="Члан [1]", party="ent1"),
        Allocation(bm_number=1, function="Заменик члана [1]", party="ent1"),
    ]
    master_out = app_paths.master_path_for(PROSIRENI_SPEC)
    result = aggregate_party_files(
        input_dir=tmp_path / "sablon_prosireni",
        template_path=None,
        output_path=master_out,
        oik=_make_oik(1),
        spec=PROSIRENI_SPEC,
        allocations_override=allocs,
        max_workers=1,
    )

    codes = {i.code for i in result.report.issues}
    assert Codes.PERSON_IN_OTHER_WORKFLOW in codes
    detail_blob = " ".join(i.detail or "" for i in result.report.issues)
    assert shared_jmbg in detail_blob


def test_aggregate_normalizes_stale_cached_zamenik_typo(tmp_path, monkeypatch) -> None:
    """Field report: a client's прошиени roster lost every zamenik entry
    right after this session's "Заменик клана" (missing "ч") typo fix
    shipped. master_io's schema v3 migration rewrites already-persisted
    committee.db rows, but it can't reach two other places the old
    spelling survives verbatim: (1) popunjeni_cache.json entries parsed
    before the fix, never re-parsed because a cache hit means the .xlsx
    is never re-opened, and (2) Phase 1 .xlsx files already sent to
    parties, whose Функција column literally still reads the old
    spelling when filled in and returned. Either path left a "Заменик
    клана [N]" function string that no longer matched the allocation
    keys built from the now-corrected SUBSTITUTE_LABEL, so
    aggregate_party_files silently treated every such seat as
    unfilled -- the exact failure confirmed in the field."""
    from biracki_odbor import app_paths
    from biracki_odbor.config.election import ElectionConfig
    from biracki_odbor.core import popunjeni_cache
    from biracki_odbor.core.models import Allocation, Person
    from biracki_odbor.core.phase2_aggregate import aggregate_party_files
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from tests.test_jmbg import VALID_SAMPLES
    from tests.test_phase1 import _make_oik

    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    popunjeni_dir = tmp_path / "home" / "popunjeni_prosireni"
    popunjeni_dir.mkdir(parents=True)
    dummy = popunjeni_dir / "ent1__2026-09-01T00-00-00Z.xlsx"
    dummy.write_bytes(b"cache hit means this is never actually opened")
    st = dummy.stat()

    election_uuid = "test-uuid-1234"
    entry = popunjeni_cache.CacheEntry(
        mtime_ns=st.st_mtime_ns, size=st.st_size,
        records=[
            {
                "bm": 1, "function": "Члан [1]",
                "person": Person(
                    bm_number=1, function="Члан [1]", party="ent1",
                    first_name="Пера", last_name="Перић",
                    jmbg=VALID_SAMPLES[0],
                ).to_dict(),
            },
            {
                # The pre-fix spelling, frozen in the cache exactly as a
                # file generated/parsed before 2026-10-12 would have it.
                "bm": 1, "function": "Заменик клана [1]",
                "person": Person(
                    bm_number=1, function="Заменик клана [1]", party="ent1",
                    first_name="Мика", last_name="Микић",
                    jmbg=VALID_SAMPLES[1],
                ).to_dict(),
            },
        ],
        received_time_iso="2026-09-01T00:00:00+00:00", party="ent1",
    )
    popunjeni_cache.save(popunjeni_cache.CacheData(
        election_uuid=election_uuid, entries={str(dummy): entry},
    ))

    allocs = [
        Allocation(bm_number=1, function="Члан [1]", party="ent1"),
        Allocation(bm_number=1, function="Заменик члана [1]", party="ent1"),
    ]
    result = aggregate_party_files(
        input_dir=popunjeni_dir, template_path=None,
        output_path=app_paths.master_path_for(PROSIRENI_SPEC),
        oik=_make_oik(1), spec=PROSIRENI_SPEC,
        allocations_override=allocs,
        election=ElectionConfig(election_uuid=election_uuid),
        max_workers=1,
    )

    by_func = {p.function: p for p in result.persons}
    assert by_func["Члан [1]"].is_filled
    assert by_func["Заменик члана [1]"].is_filled
    assert by_func["Заменик члана [1]"].jmbg == VALID_SAMPLES[1]
