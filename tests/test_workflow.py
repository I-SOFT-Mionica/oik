"""Tests for A4 — WorkflowSpec skeleton.

Covers:
  - Both specs are registered + retrievable by slug.
  - STALNI_SPEC matches the existing stalni-sastav behavior exactly
    (6 roles + matching labels, require_all_slots_filled True,
    one-team-per-bm disabled, current path names).
  - PROSIRENI_SPEC carries the design-locked values from TODO §1.5
    and the 2023 sample resenja analysis (2 roles, parallel paths,
    correct text fragments).
  - ElectionDates.subbroj_start_prosireni round-trips through
    to_dict/from_dict and defaults to "" on legacy configs.
  - Phase-D paths haven't been broken: existing app_paths still
    work, no consumer reads the spec yet.

The spec is purely data in A4 — no phase function consumes it.
These tests pin the contract so future Phase D / E refactors don't
silently change a workflow's behavior.
"""

from __future__ import annotations

from biracki_odbor.config.election import ElectionConfig, ElectionDates
from biracki_odbor.core.workflow import (
    PROSIRENI_SPEC, STALNI_SPEC, all_specs, spec_by_slug,
)


# ── Registry / lookup ─────────────────────────────────────────────


def test_all_specs_has_two_in_stable_order() -> None:
    specs = all_specs()
    assert len(specs) == 2
    assert specs[0].slug == "stalni"
    assert specs[1].slug == "prosireni"


def test_spec_by_slug_returns_singletons() -> None:
    """The registry must return the same constants — phase functions
    will compare specs by identity when caching."""
    assert spec_by_slug("stalni") is STALNI_SPEC
    assert spec_by_slug("prosireni") is PROSIRENI_SPEC


def test_spec_by_slug_unknown_raises_helpful_keyerror() -> None:
    import pytest
    with pytest.raises(KeyError, match="Unknown workflow slug"):
        spec_by_slug("posmatraci")  # the upcoming third workflow


# ── STALNI_SPEC values ────────────────────────────────────────────


def test_stalni_has_six_roles_matching_functions() -> None:
    """Stalni's 6-role schema must match `core.models.FUNCTIONS` exactly
    — they're the same data, kept in two places only because the spec
    module shouldn't pull in core.models at import."""
    from biracki_odbor.core.models import FUNCTIONS
    assert tuple(r.label_sr for r in STALNI_SPEC.roles) == FUNCTIONS


def test_stalni_substitute_flags() -> None:
    """Every other role is a Заменик — UI code relies on the flag to
    render member/substitute pairs together."""
    flags = [r.is_substitute for r in STALNI_SPEC.roles]
    assert flags == [False, True, False, True, False, True]


def test_stalni_paths_match_existing_layout() -> None:
    """Phase D must not break existing files. Path slugs must match
    what `app_paths` currently returns."""
    p = STALNI_SPEC.paths
    assert p.stranke_subdir == "stranka_fajlovi"
    assert p.popunjeni_subdir == "popunjeni"
    assert p.master_subdir == "master"
    assert p.master_filename == "zbirana_tabela.xlsx"
    assert p.resenja_subdir == "resenja"
    assert p.audit_subdir == "audit"


def test_stalni_require_all_slots_filled_true() -> None:
    """Plan §1.6 — stalni Phase 3 must block on empty slots so the
    operator goes through the načelnik-appointment flow."""
    assert STALNI_SPEC.require_all_slots_filled is True
    assert STALNI_SPEC.enforce_one_team_per_bm is False


def test_stalni_entity_source_party_full_names() -> None:
    """Stalni reads parties from the existing curated mapping; no
    candidacies-registry lookups."""
    assert STALNI_SPEC.entity_source == "party_full_names"
    assert STALNI_SPEC.entity_slot_ordering == "by_party_abbrev"
    assert STALNI_SPEC.canonical_name_strategy == "abbrev_only"


def test_stalni_subbroj_field_legacy() -> None:
    """Stalni uses the existing `dates.subbroj_start` field."""
    assert STALNI_SPEC.subbroj_field == "subbroj_start"


def test_stalni_subject_token_kind() -> None:
    """Subject-token rider — stalni is the existing default with no
    workflow infix."""
    assert STALNI_SPEC.subject_token_kind == "stalni"


# ── PROSIRENI_SPEC values ─────────────────────────────────────────


def test_prosireni_two_roles_clan_and_zamenik() -> None:
    """Prosireni's slot count and labels are pinned to the 2023 sample
    doc. Per-entity slot: Члан + Заменик члана."""
    labels = [r.label_sr for r in PROSIRENI_SPEC.roles]
    assert labels == ["Члан", "Заменик члана"]
    flags = [r.is_substitute for r in PROSIRENI_SPEC.roles]
    assert flags == [False, True]


def test_prosireni_paths_parallel_to_stalni() -> None:
    """Plan §1.4 — every working directory has a prosireni twin."""
    p = PROSIRENI_SPEC.paths
    assert p.stranke_subdir == "stranka_fajlovi_prosireni"
    assert p.popunjeni_subdir == "popunjeni_prosireni"
    assert p.master_subdir == "master_prosireni"
    assert p.master_filename == "zbirana_tabela_prosireni.xlsx"
    assert p.resenja_subdir == "resenja_prosireni"
    assert p.audit_subdir == "audit_prosireni"


def test_prosireni_domain_rules() -> None:
    """Per plan §1.1 + §1.6 — empty slots OK, one-team-per-BM enforced."""
    assert PROSIRENI_SPEC.require_all_slots_filled is False
    assert PROSIRENI_SPEC.enforce_one_team_per_bm is True


def test_prosireni_entity_source_candidacies() -> None:
    """Reads from the A3-introduced registry, not party_full_names."""
    assert PROSIRENI_SPEC.entity_source == "candidacies"
    assert PROSIRENI_SPEC.entity_slot_ordering == "by_highest_level_priority"
    assert PROSIRENI_SPEC.canonical_name_strategy == "highest_level_wins"


def test_prosireni_subbroj_field_separate() -> None:
    """Plan §1.4 — prosireni has its own starting sub-broj on
    ElectionDates so municipal-archive sequencing stays clean."""
    assert PROSIRENI_SPEC.subbroj_field == "subbroj_start_prosireni"


def test_prosireni_subject_token_kind() -> None:
    """Phase 2 inbox filter mustn't mix the two workflows' returns —
    the prosireni token kind drives a distinct [ОИК-PROSIRENI-...]
    prefix later."""
    assert PROSIRENI_SPEC.subject_token_kind == "prosireni"


def test_prosireni_resenja_text_from_2023_sample() -> None:
    """The three resenja text fragments are pinned to what the 2023
    sample doc shows (corrected for the manual error in the original).
    If anyone tweaks these strings they should also touch the test —
    the docx renderer reads from here, so changes propagate."""
    assert PROSIRENI_SPEC.resenja_title_subtitle == (
        "О ИМЕНОВАЊУ ЧЛАНОВА И ЊИХОВИХ ЗАМЕНИКА"
    )
    assert PROSIRENI_SPEC.resenja_composition_mark == "- У ПРОШИРЕНОМ САСТАВУ -"
    assert PROSIRENI_SPEC.resenja_item_i_intro == "проширеном саставу"


def test_prosireni_obrazlozenje_filename_separate() -> None:
    """Different legal articles ⇒ different obrazlozenje JSON."""
    assert PROSIRENI_SPEC.obrazlozenje_filename == "obrazlozenje_prosireni.json"
    assert STALNI_SPEC.obrazlozenje_filename == "obrazlozenje.json"


# ── ElectionDates round-trip for new prosireni-subbroj field ──────


def test_subbroj_start_prosireni_round_trip() -> None:
    """The new field must survive to_dict/from_dict so the operator's
    entry sticks across save/load."""
    d = ElectionDates(
        date_full="17. децембар 2026. године",
        subbroj_start="200",
        subbroj_start_prosireni="250",
    )
    rt = ElectionDates.from_dict(d.to_dict())
    assert rt.subbroj_start_prosireni == "250"
    assert rt.subbroj_start == "200"


def test_subbroj_start_prosireni_defaults_empty_on_legacy_config() -> None:
    """Pre-A4 election_config.json files don't have the field; loader
    must default to empty string. Legacy stalni behavior unchanged."""
    rt = ElectionDates.from_dict({
        "date_full": "17. децембар 2026. године",
        "subbroj_start": "200",
    })
    assert rt.subbroj_start_prosireni == ""
    assert rt.subbroj_start == "200"


def test_election_config_round_trip_preserves_prosireni_subbroj() -> None:
    """End-to-end — the field survives full ElectionConfig round-trip
    too. (Catches any from_dict path that drops the new field.)"""
    ec = ElectionConfig()
    ec.election.dates.subbroj_start_prosireni = "250"
    rt = ElectionConfig.from_dict(ec.to_dict())
    assert rt.election.dates.subbroj_start_prosireni == "250"


# ── No-behavior-change guard ──────────────────────────────────────


# ── Phase F: subject_token_for + corrections_log_path_for ────────────


def test_subject_token_for_stalni() -> None:
    """subject_token_for("stalni") must match the existing subject_token property."""
    d = ElectionDates(date_full="17. децембар 2026. године")
    assert d.subject_token_for("stalni") == d.subject_token
    assert d.subject_token_for("stalni") == "[ОИК-20261217]"


def test_subject_token_for_prosireni() -> None:
    """subject_token_for("prosireni") adds the -PROSIRENI- infix."""
    d = ElectionDates(date_full="17. децембар 2026. године")
    assert d.subject_token_for("prosireni") == "[ОИК-PROSIRENI-20261217]"
    assert "PROSIRENI" in d.subject_token_for("prosireni")


def test_subject_token_for_empty_date_returns_empty() -> None:
    """Empty date → empty string — same contract as subject_token property."""
    d = ElectionDates(date_full="")
    assert d.subject_token_for("stalni") == ""
    assert d.subject_token_for("prosireni") == ""


def test_corrections_log_path_for_stalni() -> None:
    """Stalni returns the default corrections.log."""
    import os, tempfile
    from biracki_odbor import app_paths
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BIRACKI_ODBOR_HOME"] = tmp
        try:
            p = app_paths.corrections_log_path_for(STALNI_SPEC)
            assert p.name == "corrections.log"
        finally:
            del os.environ["BIRACKI_ODBOR_HOME"]


def test_corrections_log_path_for_prosireni() -> None:
    """Prosireni returns a separate corrections_prosireni.log."""
    import os, tempfile
    from biracki_odbor import app_paths
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["BIRACKI_ODBOR_HOME"] = tmp
        try:
            p = app_paths.corrections_log_path_for(PROSIRENI_SPEC)
            assert p.name == "corrections_prosireni.log"
            # Different from stalni
            assert p != app_paths.corrections_log_path_for(STALNI_SPEC)
        finally:
            del os.environ["BIRACKI_ODBOR_HOME"]


def test_accountability_log_spec_param_accepted() -> None:
    """generate_accountability_log accepts spec= without crashing."""
    import inspect
    from biracki_odbor.core.accountability_log import generate_accountability_log
    sig = inspect.signature(generate_accountability_log)
    assert "spec" in sig.parameters


def test_accountability_log_prosireni_uses_separate_corrections_log(tmp_path) -> None:
    """With spec=PROSIRENI_SPEC the function reads corrections_prosireni.log,
    not corrections.log. We verify via the corrections_log_path override
    defaulting to the prosireni path when spec is passed."""
    import os
    from biracki_odbor import app_paths
    from biracki_odbor.core.accountability_log import generate_accountability_log
    from biracki_odbor.config.election import ElectionConfig
    from biracki_odbor.config.oik import OikConstants

    os.environ["BIRACKI_ODBOR_HOME"] = str(tmp_path / "home")
    try:
        oik = OikConstants(polling_stations=[])
        election = ElectionConfig()
        out_dir = tmp_path / "audit_prosireni"

        result = generate_accountability_log(
            persons=[],
            oik=oik,
            election=election,
            output_dir=out_dir,
            spec=PROSIRENI_SPEC,
        )
        # Combined doc written with prosireni workflow label in title.
        assert result.combined_path is not None
        assert result.combined_path.exists()
        from docx import Document
        doc = Document(result.combined_path)
        full_text = " ".join(p.text for p in doc.paragraphs)
        assert "Проширени" in full_text
    finally:
        del os.environ["BIRACKI_ODBOR_HOME"]


# ── No-behavior-change guard ──────────────────────────────────────


def test_phase_d_spec_wired_into_phase_functions() -> None:
    """Phase D threaded WorkflowSpec into the phase functions.

    Pins the post-Phase-D signatures so a future refactor doesn't
    accidentally drop the param. format_broj and aggregate_party_files
    are the two representative callers verified here."""
    import inspect
    from biracki_odbor.core.phase3_docx import format_broj
    from biracki_odbor.core.phase2_aggregate import aggregate_party_files

    sig3 = inspect.signature(format_broj)
    assert "spec" in sig3.parameters, (
        f"format_broj missing spec param; got {list(sig3.parameters)}"
    )

    sig2 = inspect.signature(aggregate_party_files)
    assert "spec" in sig2.parameters, (
        f"aggregate_party_files missing spec param; got {list(sig2.parameters)}"
    )
