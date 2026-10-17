"""Tests for Phase C — Кандидати tab data plumbing.

Phase C adds a 4th inner tab to ElectionSettingsTab. Its data lives
on ElectionConfig.candidacies (CandidaciesRegistry) and is exposed
in the GUI via parent-owned lists `_entity_rows` + `_candidate_rows`.

These tests cover the parts we can verify without instantiating Qt:
  - CandidaciesRegistry ↔ ElectionConfig round-trip through to_dict /
    from_dict (the same path that _build_election / _load_from_state use).
  - Entities with the full set of field values survive round-trip.
  - Candidates survive round-trip including JMBG.
  - Legacy ElectionConfig (no "candidacies" key) loads empty registry.
  - Excel I/O round-trip: build_candidacies_workbook → read_candidacies_workbook.
  - read_candidacies_workbook surfaces errors for bad level/type while
    still loading valid rows.

The GUI method _collect_candidacies() is indirectly exercised by the
ElectionConfig round-trip tests — the same dataclass shape.
"""

from __future__ import annotations

from pathlib import Path

from biracki_odbor.config.candidacies import (
    Candidate, CandidaciesRegistry, Entity,
    ENTITY_TYPES, LEVEL_KEYS,
)
from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.core.template import (
    build_candidacies_workbook, read_candidacies_workbook,
)


def _sample_registry() -> CandidaciesRegistry:
    """Realistic registry: SNS on parliamentary + local, one candidate each."""
    return CandidaciesRegistry(
        entities=[
            Entity(
                entity_id="sns-parl",
                name="Српска напредна странка — парламентарне изборе",
                entity_type="party",
                level="parliamentary",
                submission_order=1,
                linked_to_entity_id="",
            ),
            Entity(
                entity_id="sns-local",
                name="Српска напредна странка — локалне изборе",
                entity_type="party",
                level="local",
                submission_order=1,
                linked_to_entity_id="sns-parl",
            ),
            Entity(
                entity_id="sps-local",
                name="Социјалистичка партија Србије",
                entity_type="party",
                level="local",
                submission_order=2,
                linked_to_entity_id="",
            ),
        ],
        candidates=[
            Candidate(
                name="Ана Анић",
                jmbg="1605991774818",
                endorsed_by_entity_id="sns-parl",
            ),
            Candidate(
                name="Бора Борић",
                jmbg="2706994779807",
                endorsed_by_entity_id="sns-local",
            ),
        ],
    )


# ── CandidaciesRegistry round-trip ────────────────────────────────


def test_registry_round_trip_via_election_config() -> None:
    """Full chain: registry → ElectionConfig.to_dict → from_dict → registry."""
    ec = ElectionConfig(candidacies=_sample_registry())
    rt = ElectionConfig.from_dict(ec.to_dict())

    assert len(rt.candidacies.entities) == 3
    assert len(rt.candidacies.candidates) == 2

    ent = rt.candidacies.entity_by_id("sns-parl")
    assert ent is not None
    assert ent.name == "Српска напредна странка — парламентарне изборе"
    assert ent.level == "parliamentary"
    assert ent.submission_order == 1
    assert ent.linked_to_entity_id == ""

    linked = rt.candidacies.entity_by_id("sns-local")
    assert linked is not None
    assert linked.linked_to_entity_id == "sns-parl"

    cands = rt.candidacies.candidates_for_entity("sns-parl")
    assert len(cands) == 1
    assert cands[0].jmbg == "1605991774818"


def test_registry_defaults_empty_on_legacy_config() -> None:
    """Pre-Phase-C election_config.json lacks the key — loader defaults
    to an empty CandidaciesRegistry, not a crash."""
    ec = ElectionConfig.from_dict({})
    assert ec.candidacies.entities == []
    assert ec.candidacies.candidates == []


def test_jmbg_index_from_loaded_registry() -> None:
    """jmbg_index() is the Phase B1 cross-check input — it must survive
    the round-trip intact so the set doesn't silently lose entries."""
    ec = ElectionConfig(candidacies=_sample_registry())
    rt = ElectionConfig.from_dict(ec.to_dict())
    idx = rt.candidacies.jmbg_index()
    assert "1605991774818" in idx
    assert "2706994779807" in idx
    assert len(idx) == 2


def test_all_entity_types_round_trip() -> None:
    """Every defined entity_type value must survive to_dict/from_dict
    without coercion to empty string."""
    for etype in ENTITY_TYPES:
        e = Entity(
            entity_id=f"e-{etype}", name="Test", entity_type=etype,
            level="local", submission_order=1,
        )
        rt = Entity.from_dict(e.to_dict())
        assert rt.entity_type == etype


def test_all_level_keys_round_trip() -> None:
    for level in LEVEL_KEYS:
        e = Entity(
            entity_id=f"e-{level}", name="Test", entity_type="party",
            level=level, submission_order=1,
        )
        rt = Entity.from_dict(e.to_dict())
        assert rt.level == level


# ── Excel I/O round-trip ──────────────────────────────────────────


def test_excel_round_trip_entities_and_candidates(tmp_path: Path) -> None:
    """build_candidacies_workbook → read_candidacies_workbook must
    return the exact same registry (no data loss, no type coercion)."""
    reg = _sample_registry()
    xlsx = tmp_path / "kandidati.xlsx"
    build_candidacies_workbook(reg, xlsx)
    rt, errors = read_candidacies_workbook(xlsx)

    assert not errors, f"unexpected errors: {errors}"
    assert len(rt.entities) == 3
    assert len(rt.candidates) == 2

    e = rt.entity_by_id("sns-parl")
    assert e is not None
    assert e.level == "parliamentary"
    assert e.submission_order == 1

    linked = rt.entity_by_id("sns-local")
    assert linked.linked_to_entity_id == "sns-parl"

    cands = rt.candidates_for_entity("sns-parl")
    assert cands[0].jmbg == "1605991774818"


def test_excel_round_trip_jmbg_zero_padding(tmp_path: Path) -> None:
    """JMBG starting with 0 must survive the Excel round-trip without
    losing the leading zero (cells are formatted as text)."""
    reg = CandidaciesRegistry(
        entities=[Entity(
            entity_id="e1", name="Test", entity_type="party",
            level="local", submission_order=1,
        )],
        candidates=[Candidate(
            name="Тест Тестић",
            jmbg="0506008774804",   # born 2008-06-05, starts with 0
            endorsed_by_entity_id="e1",
        )],
    )
    xlsx = tmp_path / "test.xlsx"
    build_candidacies_workbook(reg, xlsx)
    rt, errors = read_candidacies_workbook(xlsx)
    assert rt.candidates[0].jmbg == "0506008774804"


def test_excel_errors_on_bad_level_but_loads_valid_rows(tmp_path: Path) -> None:
    """read_candidacies_workbook surfaces errors for invalid level/type
    values (not in vocabulary) while still loading the good rows.
    This matches the A3 design: permissive loader, explicit errors."""
    from openpyxl import Workbook
    wb = Workbook()
    ws_e = wb.active
    ws_e.title = "Ентитети"
    ws_e.append(["ID листе", "Назив", "Тип", "Ниво",
                  "Редни бр. подношења", "Повезано са"])
    ws_e.append(["e1", "Валидан ентитет", "party", "local", "1", ""])
    ws_e.append(["e2", "Лош ниво", "party", "galakticni", "2", ""])

    from biracki_odbor.core.template import _CANDIDATE_HEADERS
    ws_c = wb.create_sheet("Кандидати")
    ws_c.append(list(_CANDIDATE_HEADERS))
    ws_c.append(["e1", "Ана Анић", "1605991774818"])

    xlsx = tmp_path / "bad_level.xlsx"
    wb.save(xlsx)

    rt, errors = read_candidacies_workbook(xlsx)
    # Good row loaded; bad-level row still loads (permissive) with an error.
    assert any("galakticni" in e or "ниво" in e.lower() for e in errors)
    # The valid entity + candidate still loaded.
    assert any(e.entity_id == "e1" for e in rt.entities)
    assert len(rt.candidates) == 1
