"""Tests for A5 — načelnik-appointment flow + empty-slot gate.

Covers:
  - `CorrectionsState.appoint_by_nacelnik` writes a
    `nacelnik_appointment` event with the «Именовао начелник» prefix
    in the note, and mutates the slot's Person in place.
  - The audit log generator's split between
    «Именовања од стране начелника» and «Ручне измене» — events of
    the new type land in the načelnik section, not the manual-edits
    one.
  - The Phase 2.5 button enable/disable rule: enabled iff the
    selected slot is empty.
  - End-to-end: appoint → master row goes from empty → filled →
    Phase 3 empty-slot count drops by one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datetime import date

from biracki_odbor.config.oik import Municipality, OikConstants
from biracki_odbor.core.corrections import (
    CorrectionsState, NACELNIK_NOTE_PREFIX, NacelnikTakeoverNotStartedError,
    cutoff_passed, read_log,
)
from biracki_odbor.core.models import Person


def _make_person(
    bm: int, fn: str, *, party: str = "СНС",
    first: str = "", last: str = "", jmbg: str = "",
) -> Person:
    return Person(
        bm_number=bm, function=fn, party=party,
        first_name=first, last_name=last, jmbg=jmbg,
    )


# ── CorrectionsState.appoint_by_nacelnik ──────────────────────────


def test_appoint_writes_nacelnik_event_type(tmp_path: Path) -> None:
    """Sanity: the new method writes the new event type, not
    `edit_member`. Audit log readers + Phase 3 gate count rely on this."""
    log_path = tmp_path / "corrections.log"
    persons = [_make_person(1, "Председник")]  # empty slot
    state = CorrectionsState(persons=persons, log_path=log_path)
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    events = read_log(log_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "nacelnik_appointment"


def test_appoint_prefixes_note_with_marker(tmp_path: Path) -> None:
    """The note is rewritten to start with «Именовао начелник» — log
    readers scan for this to spot načelnik fills visually."""
    log_path = tmp_path / "corrections.log"
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=log_path,
    )
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
        note="странка није предложила",
    )
    events = read_log(log_path)
    assert events[0]["note"].startswith(NACELNIK_NOTE_PREFIX)
    assert "странка није предложила" in events[0]["note"]


def test_appoint_writes_prefix_only_when_no_reason(tmp_path: Path) -> None:
    """Empty reason → note is just the prefix, no trailing separator."""
    log_path = tmp_path / "corrections.log"
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=log_path,
    )
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    events = read_log(log_path)
    assert events[0]["note"] == NACELNIK_NOTE_PREFIX


def test_appoint_mutates_slot_in_place(tmp_path: Path) -> None:
    """End-to-end: after appoint the slot's Person becomes
    `is_filled == True`, which is exactly what Phase 3's empty-slot
    gate consults."""
    log_path = tmp_path / "corrections.log"
    persons = [_make_person(1, "Председник")]
    assert not persons[0].is_filled
    state = CorrectionsState(persons=persons, log_path=log_path)
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    assert persons[0].is_filled
    assert persons[0].first_name == "Ана"
    assert persons[0].jmbg == "1605991774818"


def test_appoint_marks_person_as_nacelnik_appointed(tmp_path: Path) -> None:
    """The whole point of the flag: a slot filled via appoint_by_nacelnik
    must be distinguishable from one the allocated party filled itself,
    so Решења/Измене generation can attribute it correctly instead of
    silently crediting the original party (the bug this flag fixes)."""
    log_path = tmp_path / "corrections.log"
    persons = [_make_person(1, "Председник", party="СНС")]
    state = CorrectionsState(persons=persons, log_path=log_path)
    assert persons[0].appointed_by_nacelnik is False
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    assert persons[0].appointed_by_nacelnik is True
    # party stays the RIK allocation — needed elsewhere for quota stats.
    assert persons[0].party == "СНС"


def test_clear_member_resets_nacelnik_flag(tmp_path: Path) -> None:
    """Once a nacelnik-appointed slot is cleared back to empty, the flag
    must not survive — an empty slot has no attribution."""
    log_path = tmp_path / "corrections.log"
    persons = [_make_person(1, "Председник", party="СНС")]
    state = CorrectionsState(persons=persons, log_path=log_path)
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    assert persons[0].appointed_by_nacelnik is True
    state.clear_member(1, "Председник")
    assert persons[0].appointed_by_nacelnik is False


def test_appoint_returns_none_for_unknown_slot(tmp_path: Path) -> None:
    """Defensive: a (bm, function) that doesn't match any Person
    returns None, doesn't crash, doesn't log a phantom event."""
    log_path = tmp_path / "corrections.log"
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=log_path,
    )
    out = state.appoint_by_nacelnik(
        99, "Председник",
        {"first_name": "X"},
    )
    assert out is None
    assert not log_path.exists() or not read_log(log_path)


def test_appoint_event_records_before_after(tmp_path: Path) -> None:
    """before/after snapshots are required by the accountability log
    table — its diff cells read from them."""
    log_path = tmp_path / "corrections.log"
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=log_path,
    )
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић"},
    )
    ev = read_log(log_path)[0]
    assert ev["before"]["first_name"] == ""
    assert ev["after"]["first_name"] == "Ана"


# ── Accountability log section split ──────────────────────────────


def test_audit_log_separates_nacelnik_from_other_edits(tmp_path: Path) -> None:
    """The audit doc must render two distinct sections — the načelnik
    appointments under «2. Именовања од стране начелника», everything
    else under «3. Ручне измене (Фаза 2.5)»."""
    from biracki_odbor.config.election import (
        ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.config.oik import OikConstants, Municipality
    from biracki_odbor.core.accountability_log import (
        generate_accountability_log,
    )

    # Synthesize a corrections.log with one nacelnik event + one regular edit.
    log_path = tmp_path / "corrections.log"
    state = CorrectionsState(
        persons=[
            _make_person(1, "Председник"),
            _make_person(1, "Члан 1", first="Бора", last="Борић", jmbg="2706994779807"),
        ],
        log_path=log_path,
    )
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )
    state.edit_member(
        1, "Члан 1",
        {"first_name": "Бора (исправљено)"},
    )

    out_dir = tmp_path / "audit"
    oik = OikConstants(municipality=Municipality(
        name="Уб", full_committee_name="ОИК Уб",
    ))
    election = ElectionConfig(election=ElectionInfo(
        dates=ElectionDates(date_full="17. децембар 2026. године"),
    ))
    generate_accountability_log(
        persons=state.persons, oik=oik, election=election,
        output_dir=out_dir,
        corrections_log_path=log_path,
    )
    combined = out_dir / "Аудит траг.docx"
    assert combined.exists(), "combined audit doc must be written"

    # Verify the rendered text contains both section headers in order.
    from docx import Document
    doc = Document(combined)
    paragraphs = [p.text for p in doc.paragraphs]
    nac_idx = next(
        (i for i, t in enumerate(paragraphs)
         if "Именовања од стране начелника" in t),
        -1,
    )
    edits_idx = next(
        (i for i, t in enumerate(paragraphs)
         if "Ручне измене" in t),
        -1,
    )
    assert nac_idx >= 0, "expected načelnik section header"
    assert edits_idx >= 0, "expected manual-edits section header"
    assert nac_idx < edits_idx, (
        "načelnik section must precede manual-edits section"
    )


# ── cutoff_passed() — still used, now only to gate the takeover BUTTON ──


def test_cutoff_passed_helper() -> None:
    today = date(2026, 7, 13)
    assert cutoff_passed("2026-07-12", today=today) is True
    assert cutoff_passed("2026-07-13", today=today) is False  # same day: not yet
    assert cutoff_passed("2026-07-14", today=today) is False  # future
    assert cutoff_passed("", today=today) is False  # unset ⇒ blocked
    assert cutoff_passed("not-a-date", today=today) is False  # unparseable ⇒ blocked


# ── Nacelnik hard-stop gate: explicit takeover flag, not a date check ──


def test_gate_disabled_by_default_ignores_takeover_flag(tmp_path: Path) -> None:
    """Regression guard: every existing/other CorrectionsState caller
    (and prošireni, which has no nacelnik-takeover concept at all) must
    keep working exactly as before — the gate is opt-in."""
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=tmp_path / "corrections.log",
        # nacelnik_gate_enabled defaults to False; nacelnik_takeover_active too.
    )
    out = state.appoint_by_nacelnik(1, "Председник", {"first_name": "Ана"})
    assert out is not None
    assert out.first_name == "Ана"


def test_gate_enabled_blocks_before_takeover(tmp_path: Path) -> None:
    """No date is involved at all — a pure boolean flag. Blocked until
    the operator has explicitly declared submissions closed."""
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=tmp_path / "corrections.log",
        nacelnik_takeover_active=False,
        nacelnik_gate_enabled=True,
    )
    with pytest.raises(NacelnikTakeoverNotStartedError):
        state.appoint_by_nacelnik(1, "Председник", {"first_name": "Ана"})
    # No audit event was written for the rejected attempt.
    assert not (tmp_path / "corrections.log").exists()


def test_gate_enabled_allows_after_takeover(tmp_path: Path) -> None:
    state = CorrectionsState(
        persons=[_make_person(1, "Председник")],
        log_path=tmp_path / "corrections.log",
        nacelnik_takeover_active=True,
        nacelnik_gate_enabled=True,
    )
    out = state.appoint_by_nacelnik(1, "Председник", {"first_name": "Ана"})
    assert out is not None
    assert out.first_name == "Ана"


# ── Decision-text attribution — the actual bug this flag fixes ────
#
# Регресион guard for: "resenja show the original party holding the
# slot instead of nacelnik". Person.party always stays the RIK
# allocation (needed for quota stats elsewhere), so decision-text
# generation must consult `appointed_by_nacelnik` explicitly rather
# than inferring attribution from `party` alone.


_NACELNIK_NAME = "начелника Општинске управе општине Уб"


def _election_with_parties() -> "ElectionConfig":
    from biracki_odbor.config.election import ElectionConfig

    ec = ElectionConfig()
    ec.party_full_names["СНС"] = "Посланичке групе СРПСКА НАПРЕДНА СТРАНКА"
    return ec


def test_proposal_text_uses_real_party_when_not_nacelnik_appointed() -> None:
    from biracki_odbor.core.phase3_docx import _proposal_text

    election = _election_with_parties()
    label, name = _proposal_text(
        "СНС", election, _NACELNIK_NAME, appointed_by_nacelnik=False,
    )
    assert name == "СРПСКА НАПРЕДНА СТРАНКА"


def test_proposal_text_uses_nacelnik_fallback_when_appointed() -> None:
    """Even though `party` still says "СНС" (the allocation), the
    appointed_by_nacelnik flag must override attribution to the chief."""
    from biracki_odbor.core.phase3_docx import _proposal_text

    election = _election_with_parties()
    label, name = _proposal_text(
        "СНС", election, _NACELNIK_NAME, appointed_by_nacelnik=True,
    )
    assert name == _NACELNIK_NAME
    assert "СРПСКА НАПРЕДНА СТРАНКА" not in name


def test_party_proposal_text_izmene_uses_nacelnik_fallback_when_appointed() -> None:
    from biracki_odbor.core.izmene_docx import _party_proposal_text

    election = _election_with_parties()
    text = _party_proposal_text(
        "СНС", election, "stalni", "12. децембра 2026. године", _NACELNIK_NAME,
        appointed_by_nacelnik=True,
    )
    assert _NACELNIK_NAME in text
    assert "СРПСКА НАПРЕДНА СТРАНКА" not in text


def test_party_proposal_text_izmene_uses_real_party_when_not_appointed() -> None:
    from biracki_odbor.core.izmene_docx import _party_proposal_text

    election = _election_with_parties()
    text = _party_proposal_text(
        "СНС", election, "stalni", "12. децембра 2026. године", _NACELNIK_NAME,
        appointed_by_nacelnik=False,
    )
    assert "СРПСКА НАПРЕДНА СТРАНКА" in text


def test_master_xlsx_roundtrip_preserves_nacelnik_flag(tmp_path: Path) -> None:
    """The flag must survive Save -> reload, since Решења generation
    reads Person objects back from master.xlsx, not the live in-memory
    CorrectionsState."""
    from biracki_odbor.core.master_io import read_master, write_master

    log_path = tmp_path / "corrections.log"
    persons = [
        _make_person(1, "Председник", party="СНС"),
        _make_person(1, "Члан 1", party="СПС", first="Бора", last="Борић",
                      jmbg="2706994779807"),
    ]
    state = CorrectionsState(persons=persons, log_path=log_path)
    state.appoint_by_nacelnik(
        1, "Председник",
        {"first_name": "Ана", "last_name": "Анић", "jmbg": "1605991774818"},
    )

    oik = OikConstants(municipality=Municipality(
        name="Уб", full_committee_name="ОИК Уб",
    ))
    out_path = tmp_path / "zbirna_tabela.xlsx"
    write_master(state.persons, oik, out_path)

    reloaded = read_master(out_path)
    by_slot = {p.slot_key: p for p in reloaded}
    assert by_slot[(1, "Председник")].appointed_by_nacelnik is True
    assert by_slot[(1, "Председник")].party == "СНС"  # allocation preserved
    assert by_slot[(1, "Члан 1")].appointed_by_nacelnik is False


# ── Phase 3 gate (logic level) ────────────────────────────────────


def test_phase3_gate_counts_empty_slots() -> None:
    """Pre-A5 the gate didn't exist; the new behaviour: any Person
    with `is_filled == False` counts as an empty slot that must be
    appointed before Phase 3 runs.

    This pins the count semantics — the GUI banner reads it
    directly. Whole-tab GUI integration is exercised in manual
    smoke; here we keep the logic test pure."""
    persons = [
        _make_person(1, "Председник"),  # empty
        _make_person(1, "Члан 1", first="X", last="Y", jmbg="1605991774818"),
        _make_person(2, "Председник", first="A", last="B", jmbg="2706994779807"),
        _make_person(2, "Члан 1"),  # empty
    ]
    empty = [p for p in persons if not p.is_filled]
    assert len(empty) == 2
    # After appointing one, the count drops by one (this is exactly
    # what the gate consults on the next preflight refresh).
    persons[0].first_name = "Ана"
    persons[0].last_name = "Анић"
    persons[0].jmbg = "1605991774818"
    empty = [p for p in persons if not p.is_filled]
    assert len(empty) == 1
