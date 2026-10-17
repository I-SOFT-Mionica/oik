"""Tests for Phase B — cross-check + age + canonical-name resolution.

Three independent helpers, three test groups:

  B1 — `validate_person(candidate_jmbgs=...)` emits
       `PERSON_IS_CANDIDATE` when the member's JMBG appears in the
       set, skips the check when the set is None (legacy callers).
  B2 — `validate_person(election_date=...)` emits `PERSON_UNDER_18`
       when JMBG-encoded DOB leaves the person under 18 on
       election day; skips when election_date is None.
  B3 — `canonical_entity_name` walks the operator-set link chain and
       picks the name from the highest-level entity in the group.
"""

from __future__ import annotations

from datetime import date

from biracki_odbor.config.candidacies import (
    Entity, canonical_entity_name,
)
from biracki_odbor.core.models import Person
from biracki_odbor.validation import rows as row_checks
from biracki_odbor.validation.reports import Codes


def _make_person(*, jmbg: str = "1605991774818", first: str = "Ана") -> Person:
    return Person(
        bm_number=1, function="Председник", party="СНС",
        first_name=first, last_name="Анић", jmbg=jmbg,
    )


# ── B1 — committee/candidate cross-check ──────────────────────────


def test_b1_emits_when_jmbg_is_a_candidate() -> None:
    """Member's JMBG in the candidate set ⇒ PERSON_IS_CANDIDATE error."""
    p = _make_person(jmbg="1605991774818")
    issues = row_checks.validate_person(
        p, candidate_jmbgs={"1605991774818"},
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_IS_CANDIDATE in codes


def test_b1_silent_when_jmbg_not_a_candidate() -> None:
    """Different JMBG ⇒ no PERSON_IS_CANDIDATE."""
    p = _make_person(jmbg="1605991774818")
    issues = row_checks.validate_person(
        p, candidate_jmbgs={"2706994779807"},
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_IS_CANDIDATE not in codes


def test_b1_skipped_when_set_is_none() -> None:
    """Legacy callers pass no `candidate_jmbgs` — must not emit the
    new code. Protects existing 14 validation tests from regressing."""
    p = _make_person()
    issues = row_checks.validate_person(p)
    codes = {i.code for i in issues}
    assert Codes.PERSON_IS_CANDIDATE not in codes


def test_b1_skipped_on_malformed_jmbg() -> None:
    """Don't flag PERSON_IS_CANDIDATE for a typo JMBG — they get a
    JMBG_BAD_* error already and the cross-check would mislead."""
    p = _make_person(jmbg="not-a-jmbg")
    issues = row_checks.validate_person(
        p, candidate_jmbgs={"not-a-jmbg"},  # nonsensical set but still
    )
    codes = {i.code for i in issues}
    # JMBG_BAD_FORMAT is raised (member's JMBG itself bad), but
    # PERSON_IS_CANDIDATE must NOT be — we never reach that branch.
    assert Codes.PERSON_IS_CANDIDATE not in codes


def test_b1_error_carries_jmbg_in_detail() -> None:
    """Audit / Phase 2.5 row-marking key off the issue's `detail`
    field — must contain the offending JMBG, not the name."""
    p = _make_person(jmbg="1605991774818")
    issues = row_checks.validate_person(
        p, candidate_jmbgs={"1605991774818"},
    )
    issue = next(i for i in issues if i.code == Codes.PERSON_IS_CANDIDATE)
    assert issue.detail == "1605991774818"
    assert issue.severity == "error"


# ── B2 — 18+ age check ───────────────────────────────────────────


def test_b2_emits_when_under_18_on_election_day() -> None:
    """JMBG 0506016... = 5 June 2016. Election 5 June 2026 → still 10
    years old → PERSON_UNDER_18."""
    p = _make_person(jmbg="0506016774805")
    issues = row_checks.validate_person(
        p, election_date=date(2026, 6, 5),
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_UNDER_18 in codes


def test_b2_silent_when_exactly_18() -> None:
    """Born 5 June 2008, election day 5 June 2026 → turns 18 on this
    very day → eligible (Serbian convention). No PERSON_UNDER_18."""
    p = _make_person(jmbg="0506008774804")
    issues = row_checks.validate_person(
        p, election_date=date(2026, 6, 5),
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_UNDER_18 not in codes


def test_b2_emits_one_day_before_18th_birthday() -> None:
    """Born 5 June 2008, election day 4 June 2026 → still 17 →
    PERSON_UNDER_18. Common one-day-shy bug operators care about."""
    p = _make_person(jmbg="0506008774804")
    issues = row_checks.validate_person(
        p, election_date=date(2026, 6, 4),
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_UNDER_18 in codes


def test_b2_skipped_when_election_date_is_none() -> None:
    """Pre-Phase-B aggregator calls pass no election_date — the check
    must skip rather than treating every member as under-18."""
    p = _make_person(jmbg="0506016774805")  # really 10 years old
    issues = row_checks.validate_person(p)
    codes = {i.code for i in issues}
    assert Codes.PERSON_UNDER_18 not in codes


def test_b2_silent_on_malformed_jmbg() -> None:
    """Same defensive policy as B1 — JMBG_BAD_FORMAT already fires;
    don't pile on with a phantom PERSON_UNDER_18 from None DOB."""
    p = _make_person(jmbg="abc")
    issues = row_checks.validate_person(
        p, election_date=date(2026, 6, 5),
    )
    codes = {i.code for i in issues}
    assert Codes.PERSON_UNDER_18 not in codes


def test_b2_error_carries_jmbg_in_detail() -> None:
    p = _make_person(jmbg="0506016774805")
    issues = row_checks.validate_person(
        p, election_date=date(2026, 6, 5),
    )
    issue = next(i for i in issues if i.code == Codes.PERSON_UNDER_18)
    assert issue.detail == "0506016774805"
    assert issue.severity == "error"


# ── B3 — canonical-name resolution ───────────────────────────────


def _e(eid: str, name: str, level: str, order: int = 1,
       linked_to: str = "") -> Entity:
    return Entity(
        entity_id=eid, name=name, entity_type="party",
        level=level, submission_order=order,
        linked_to_entity_id=linked_to,
    )


def test_b3_standalone_entity_returns_own_name() -> None:
    """No link ⇒ entity is its own canonical."""
    sole = _e("e1", "Standalone Entity", "local")
    assert canonical_entity_name(sole, [sole]) == "Standalone Entity"


def test_b3_higher_level_name_wins() -> None:
    """Two linked entities, parliamentary (level 2) + local (level 4):
    parliamentary name wins because priority 2 < 4."""
    parl = _e("sns-parl", "СНС - парламентарни", "parliamentary")
    loc = _e("sns-loc", "СНС - локални", "local", linked_to="sns-parl")
    # Querying either returns the same canonical.
    assert canonical_entity_name(parl, [parl, loc]) == "СНС - парламентарни"
    assert canonical_entity_name(loc, [parl, loc]) == "СНС - парламентарни"


def test_b3_presidential_beats_parliamentary_beats_local() -> None:
    """Three-link chain — presidential wins."""
    pres = _e("sns-pres", "СНС - Александар Вучић", "presidential")
    parl = _e("sns-parl", "СНС - парл.", "parliamentary",
              linked_to="sns-pres")
    loc = _e("sns-loc", "СНС - локални", "local",
             linked_to="sns-parl")
    canonical = canonical_entity_name(loc, [pres, parl, loc])
    assert canonical == "СНС - Александар Вучић"


def test_b3_dangling_link_falls_back_to_own_name() -> None:
    """`linked_to_entity_id` points to a missing entity → defensive:
    return the entity's own name rather than raising."""
    orphan = _e("e1", "Orphan", "local", linked_to="missing-id")
    assert canonical_entity_name(orphan, [orphan]) == "Orphan"


def test_b3_handles_circular_link() -> None:
    """Operator misconfiguration: A → B → A. Helper must not infinite-
    loop; it picks the highest-level entity from the cycle."""
    a = _e("a", "A-pres", "presidential", linked_to="b")
    b = _e("b", "B-loc", "local", linked_to="a")
    name = canonical_entity_name(a, [a, b])
    # A is presidential (priority 1) so it wins regardless of the
    # cycle direction.
    assert name == "A-pres"


def test_b3_tie_break_by_submission_order() -> None:
    """When two entities share the same highest level, the smaller
    submission_order wins (the one who submitted first on the ballot)."""
    e1 = _e("e1", "First-submitted", "presidential", order=1)
    e2 = _e("e2", "Second-submitted", "presidential",
            order=2, linked_to="e1")
    # Either entity → "First-submitted" canonical.
    assert canonical_entity_name(e2, [e1, e2]) == "First-submitted"
