"""Tests for core.corrections (Phase 2.5)."""

from __future__ import annotations

import json
from pathlib import Path

from biracki_odbor.core.corrections import (
    CorrectionsState,
    detect_conflicts,
    read_log,
)
from biracki_odbor.core.models import Person
from tests.test_jmbg import VALID_SAMPLES


def _slot(bm: int, func: str, party: str, *, name: str = "", jmbg: str = "") -> Person:
    text = name.strip()
    if " " in text:
        first, last = text.rsplit(" ", 1)
    else:
        first, last = text, ""
    return Person(
        bm_number=bm, function=func, party=party,
        first_name=first, last_name=last, jmbg=jmbg,
        mesto="Уб", adresa="Адр", telefon="0641234567", email="x@y",
    )


def test_detect_conflict_simple() -> None:
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар Других", jmbg=VALID_SAMPLES[0]),
        _slot(3, "Председник", "ДС", name="Друга Особа", jmbg=VALID_SAMPLES[1]),
    ]
    conflicts = detect_conflicts(persons)
    assert len(conflicts) == 1
    assert conflicts[0].jmbg == VALID_SAMPLES[0]
    assert len(conflicts[0].submissions) == 2


def test_detect_no_conflicts_when_unique() -> None:
    persons = [
        _slot(1, "Председник", "СНС", name="A", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Председник", "СПС", name="B", jmbg=VALID_SAMPLES[1]),
    ]
    assert detect_conflicts(persons) == []


def test_cross_workflow_conflict_surfaces_even_with_single_occurrence() -> None:
    """A person seated exactly once in THIS workflow isn't a same-workflow
    conflict by itself, but must still surface if the same JMBG also holds
    a filled seat in the OTHER workflow."""
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
    ]
    other_persons = [
        _slot(5, "Члан [1]", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
    ]
    conflicts = detect_conflicts(
        persons, other_workflow_persons=other_persons,
        other_workflow_label="Проширени састав",
    )
    assert len(conflicts) == 1
    assert len(conflicts[0].submissions) == 1, "must not merge into one same-workflow submission"
    assert len(conflicts[0].cross_workflow) == 1
    assert conflicts[0].cross_workflow[0].bm_number == 5
    assert conflicts[0].other_workflow_label == "Проширени састав"


def test_no_cross_workflow_label_when_no_cross_match() -> None:
    """A real same-workflow conflict with no other-workflow overlap must
    not carry a stale other_workflow_label from a prior/unrelated jmbg."""
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар Других", jmbg=VALID_SAMPLES[0]),
    ]
    conflicts = detect_conflicts(
        persons, other_workflow_persons=[], other_workflow_label="Проширени састав",
    )
    assert len(conflicts) == 1
    assert conflicts[0].cross_workflow == []
    assert conflicts[0].other_workflow_label == ""


def test_submission_times_populated_from_cache(tmp_path, monkeypatch) -> None:
    from biracki_odbor.core import popunjeni_cache

    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    election_uuid = "test-uuid-xyz"
    entry = popunjeni_cache.CacheEntry(
        mtime_ns=0, size=0, received_time_iso="2026-10-01T10:00:00+00:00", party="СНС",
    )
    dummy = tmp_path / "home" / "СНС.xlsx"
    dummy.parent.mkdir(parents=True, exist_ok=True)
    dummy.write_bytes(b"x")
    popunjeni_cache.save(popunjeni_cache.CacheData(
        election_uuid=election_uuid, entries={str(dummy): entry},
    ))

    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар Других", jmbg=VALID_SAMPLES[0]),
    ]
    conflicts = detect_conflicts(persons, election_uuid=election_uuid)
    assert len(conflicts) == 1
    sns_person = next(p for p in conflicts[0].submissions if p.party == "СНС")
    assert conflicts[0].submission_times[id(sns_person)] == "2026-10-01T10:00:00+00:00"
    sps_person = next(p for p in conflicts[0].submissions if p.party == "СПС")
    assert conflicts[0].submission_times.get(id(sps_person), "") == ""


def test_resolve_conflict_clears_loser(tmp_path: Path) -> None:
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар Других", jmbg=VALID_SAMPLES[0]),
    ]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    conflicts = detect_conflicts(persons)
    state.resolve_conflict(
        conflicts[0], keep_slot_key=(1, "Председник"), note="Прва пријава",
    )

    # СНС slot intact
    sns = next(p for p in persons if p.party == "СНС")
    assert sns.name == "Петар"
    assert sns.jmbg == VALID_SAMPLES[0]
    # СПС slot cleared
    sps = next(p for p in persons if p.party == "СПС")
    assert sps.name == ""
    assert sps.jmbg == ""
    # Log has at least 2 events (one clear, one kept)
    events = read_log(state.log_path)
    assert len(events) >= 2
    types = {e["event_type"] for e in events}
    assert "resolve_conflict" in types


def test_resolve_conflict_same_party_keeps_by_slot(tmp_path: Path) -> None:
    """v0.5.1 regression: a party listing the same JMBG twice was unfixable.

    v0.5.0's `resolve_conflict(keep_party=...)` matched submissions by
    party name. When BOTH submissions came from the same party (e.g.
    СНС appearing at БМ 1 Председник AND at БМ 3 Члан 1 with the same
    JMBG — a paste-from-CRM mistake), both submissions matched
    `keep_party` and neither got cleared. The conflict card disappeared
    from the list (UI re-rendered) but the underlying data was
    unchanged, and the user saw no effect after clicking 'Задржи'.

    The fix: resolve by slot_key, which is globally unique
    (`(bm_number, function)`). Whatever slot the operator clicked is
    the one we keep; every other slot in the conflict gets cleared,
    same-party or not.
    """
    persons = [
        _slot(1, "Председник", "СНС", name="Душко", jmbg=VALID_SAMPLES[0]),
        _slot(3, "Члан 1",     "СНС", name="Душко", jmbg=VALID_SAMPLES[0]),
    ]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    conflicts = detect_conflicts(persons)
    assert len(conflicts) == 1
    assert len(conflicts[0].submissions) == 2
    # Detection works even when both submissions are same-party.

    # Keep the БМ 3 / Члан 1 slot; БМ 1 / Председник should be cleared.
    state.resolve_conflict(
        conflicts[0], keep_slot_key=(3, "Члан 1"), note="БМ 3 је тачан",
    )
    kept = next(p for p in persons if p.slot_key == (3, "Члан 1"))
    cleared = next(p for p in persons if p.slot_key == (1, "Председник"))
    assert kept.jmbg == VALID_SAMPLES[0], "kept slot must retain its data"
    assert kept.name == "Душко"
    assert cleared.jmbg == "" and cleared.name == "", (
        "the other same-party slot must be cleared — v0.5.0 left it intact"
    )


def test_remove_one_slot_only_clears_that_slot(tmp_path: Path) -> None:
    """Per-slot remove (one of the two per-card buttons) clears just
    that submission and leaves the rest of the conflict for the
    operator to resolve in a subsequent click."""
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(3, "Члан 2", "ДС",  name="Петар", jmbg=VALID_SAMPLES[0]),
    ]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    conflicts = detect_conflicts(persons)
    state.remove_one_slot(conflicts[0], (2, "Члан 1"), note="дупликат")
    sps = next(p for p in persons if p.party == "СПС")
    assert sps.name == "" and sps.jmbg == ""
    # Others untouched.
    sns = next(p for p in persons if p.party == "СНС")
    ds = next(p for p in persons if p.party == "ДС")
    assert sns.jmbg == VALID_SAMPLES[0]
    assert ds.jmbg == VALID_SAMPLES[0]
    # Detection still flags a 2-way conflict.
    assert len(detect_conflicts(persons)[0].submissions) == 2


def test_replace_member_logs_event(tmp_path: Path) -> None:
    persons = [_slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0])]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    state.replace_member(1, "Председник", {
        "name": "Замена Петрова", "jmbg": VALID_SAMPLES[1],
    }, note="Болест")
    p = persons[0]
    assert p.name == "Замена Петрова"
    assert p.jmbg == VALID_SAMPLES[1]
    events = read_log(state.log_path)
    assert any(e["event_type"] == "replace_member" for e in events)


def test_clear_member(tmp_path: Path) -> None:
    persons = [_slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0])]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    state.clear_member(1, "Председник", note="Одустао")
    assert persons[0].name == ""
    assert not persons[0].is_filled


def test_remove_from_all(tmp_path: Path) -> None:
    persons = [
        _slot(1, "Председник", "СНС", name="Петар", jmbg=VALID_SAMPLES[0]),
        _slot(2, "Члан 1", "СПС", name="Петар", jmbg=VALID_SAMPLES[0]),
    ]
    state = CorrectionsState(persons=persons, log_path=tmp_path / "corr.log")
    conflicts = detect_conflicts(persons)
    state.remove_from_all(conflicts[0], note="дисквалификован")
    assert all(not p.is_filled for p in persons)


def test_log_is_appendable_jsonl(tmp_path: Path) -> None:
    persons = [_slot(1, "Председник", "СНС", name="A", jmbg=VALID_SAMPLES[0])]
    log = tmp_path / "corr.log"
    state = CorrectionsState(persons=persons, log_path=log)
    state.edit_member(1, "Председник", {"telefon": "0651112222"})
    state.edit_member(1, "Председник", {"telefon": "0653334444"})
    # Two lines, both valid JSON
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # must parse


def test_edit_member_logs_other_bm_and_municipality(tmp_path: Path) -> None:
    """чл. 14(1)(8)/чл. 15 double-appointment flagging — real fields on
    the audit event (not just folded into the free-text note), so the
    Измене tab's Престанак track can detect and pre-fill from the log
    without parsing a sentence back apart."""
    persons = [_slot(1, "Председник", "СНС", name="A", jmbg=VALID_SAMPLES[0])]
    log = tmp_path / "corr.log"
    state = CorrectionsState(persons=persons, log_path=log)
    state.edit_member(
        1, "Председник", {},
        note="по члану 14. став 1. тачка 8)",
        other_bm=5, other_municipality="Ваљево",
    )
    line = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert line["other_bm"] == 5
    assert line["other_municipality"] == "Ваљево"


def test_edit_member_other_bm_defaults_absent(tmp_path: Path) -> None:
    """An ordinary edit (no чл. 14(1)(8) flag) must not grow spurious
    other_bm/other_municipality noise in the log."""
    persons = [_slot(1, "Председник", "СНС", name="A", jmbg=VALID_SAMPLES[0])]
    log = tmp_path / "corr.log"
    state = CorrectionsState(persons=persons, log_path=log)
    state.edit_member(1, "Председник", {"telefon": "0651112222"})
    line = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert line["other_bm"] is None
    assert line["other_municipality"] == ""


def test_edit_member_logs_other_decision_broj(tmp_path: Path) -> None:
    """The other municipality's own decision number, when the operator
    already knows it — a real field alongside other_bm/other_municipality,
    so Престанак can pre-fill the existing seat's broj too."""
    persons = [_slot(1, "Председник", "СНС", name="A", jmbg=VALID_SAMPLES[0])]
    log = tmp_path / "corr.log"
    state = CorrectionsState(persons=persons, log_path=log)
    state.edit_member(
        1, "Председник", {},
        note="по члану 14. став 1. тачка 8)",
        other_bm=5, other_municipality="Ваљево",
        other_decision_broj="013-9-1-4/2026",
    )
    line = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert line["other_decision_broj"] == "013-9-1-4/2026"
