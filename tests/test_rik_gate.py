"""Tests for RIK submission gate, cutoff blocking, and related audit events.

Covers:
  - append_rik_submission writes a rik_submission event
  - append_late_submission_blocked writes a late_submission_blocked event
  - count_party_corrections ignores late_submission_blocked (not a tombstone)
  - count_party_corrections still stops at submission_superseded
  - WorkflowLog submit/submitted/revert roundtrip and idempotency
  - GenerationLog.is_izmena_mode() requires phase3_done AND submitted_to_rik
  - GenerationLog to_dict/from_dict preserves submitted_to_rik_ts
  - from_dict({}) defaults submitted_to_rik_ts to 0 (legacy compat)
  - popunjeni_odbijeno_dir() has the correct name and parent
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.core.corrections import (
    CorrectionsState,
    append_late_submission_blocked,
    append_rik_submission,
    append_submission_superseded,
    count_party_corrections,
    read_log,
)
from biracki_odbor.core.generation_log import GenerationLog, WorkflowLog
from biracki_odbor.core.models import Person
from tests.test_jmbg import VALID_SAMPLES


# ── helpers ───────────────────────────────────────────────────────────────────


def _person(bm: int, party: str) -> Person:
    return Person(
        bm_number=bm, function="Председник", party=party,
        first_name="Тест", last_name="Особа",
        jmbg=VALID_SAMPLES[0], mesto="Уб", adresa="Адреса 1",
        telefon="0641234567", email="t@t",
    )


# ── append_rik_submission ─────────────────────────────────────────────────────


def test_append_rik_submission_writes_event(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    append_rik_submission(log_path, "stalni")
    events = read_log(log_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "rik_submission"
    assert "stalni" in events[0]["note"]


def test_append_rik_submission_prosireni_slug(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    append_rik_submission(log_path, "prosireni")
    events = read_log(log_path)
    assert "prosireni" in events[0]["note"]


def test_append_rik_submission_creates_parent_dirs(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "dir" / "audit.log"
    append_rik_submission(log_path, "stalni")
    assert log_path.exists()


# ── append_late_submission_blocked ────────────────────────────────────────────


def test_append_late_submission_blocked_outlook(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    append_late_submission_blocked(
        log_path, "sns.xlsx", "СНС",
        "2026-11-15T10:00:00+01:00", "2026-11-01",
        source="outlook",
    )
    events = read_log(log_path)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "late_submission_blocked"
    assert "СНС" in ev["note"]
    assert "sns.xlsx" in ev["note"]
    assert "outlook" in ev["note"]
    assert "2026-11-01" in ev["note"]


def test_append_late_submission_blocked_file_dialog(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    append_late_submission_blocked(
        log_path, "ds.xlsx", "ДС",
        "2026-11-20T08:00:00+01:00", "2026-11-01",
        source="file_dialog",
    )
    events = read_log(log_path)
    assert "file_dialog" in events[0]["note"]


def test_append_late_submission_blocked_creates_parent_dirs(tmp_path: Path) -> None:
    log_path = tmp_path / "sub" / "audit.log"
    append_late_submission_blocked(
        log_path, "x.xlsx", "X", "2026-11-15T00:00:00+01:00", "2026-11-01",
    )
    assert log_path.exists()


# ── count_party_corrections interaction with new event types ──────────────────


def test_count_party_corrections_ignores_late_submission_blocked(tmp_path: Path) -> None:
    """late_submission_blocked must NOT stop the correction counter.

    A late-blocked file has no bearing on the party's existing
    accepted corrections; only submission_superseded acts as a tombstone.
    """
    log_path = tmp_path / "audit.log"
    state = CorrectionsState(persons=[_person(1, "СНС")], log_path=log_path)

    state.edit_member(1, "Председник", {"telefon": "0651111111"}, note="прва")
    state.edit_member(1, "Председник", {"telefon": "0652222222"}, note="друга")

    # Late-block event for the same party — must NOT stop the counter.
    append_late_submission_blocked(
        log_path, "sns_late.xlsx", "СНС",
        "2026-11-20T10:00:00+01:00", "2026-11-01",
    )

    state.edit_member(1, "Председник", {"telefon": "0653333333"}, note="трећа")

    assert count_party_corrections(log_path, "СНС") == 3


def test_count_party_corrections_stops_at_superseded(tmp_path: Path) -> None:
    """submission_superseded still stops the counter."""
    log_path = tmp_path / "audit.log"
    state = CorrectionsState(persons=[_person(1, "СПС")], log_path=log_path)

    state.edit_member(1, "Председник", {"telefon": "0651111111"}, note="прва")
    state.edit_member(1, "Председник", {"telefon": "0652222222"}, note="друга")
    append_submission_superseded(log_path, "СПС", "sps_v2.xlsx", prior_corrections=2)
    # One more edit after the supersession — only this one counts.
    state.edit_member(1, "Председник", {"telefon": "0653333333"}, note="трећа")

    assert count_party_corrections(log_path, "СПС") == 1


def test_count_party_corrections_rik_submission_not_counted(tmp_path: Path) -> None:
    """rik_submission is not a manual-edit type and must not be counted."""
    log_path = tmp_path / "audit.log"
    state = CorrectionsState(persons=[_person(1, "СНС")], log_path=log_path)

    state.edit_member(1, "Председник", {"telefon": "0651111111"}, note="edit")
    append_rik_submission(log_path, "stalni")

    assert count_party_corrections(log_path, "СНС") == 1


# ── WorkflowLog RIK gate ──────────────────────────────────────────────────────


def test_workflow_log_initial_state() -> None:
    wl = WorkflowLog()
    assert wl.submitted_to_rik_ts == 0
    assert not wl.submitted_to_rik()


def test_workflow_log_submit_sets_nonzero_timestamp() -> None:
    wl = WorkflowLog()
    wl.submit_to_rik()
    assert wl.submitted_to_rik_ts > 0
    assert wl.submitted_to_rik()


def test_workflow_log_submit_is_idempotent() -> None:
    """Calling submit_to_rik() twice must not advance the timestamp."""
    wl = WorkflowLog()
    wl.submit_to_rik()
    first_ts = wl.submitted_to_rik_ts
    wl.submit_to_rik()
    assert wl.submitted_to_rik_ts == first_ts


def test_workflow_log_revert_clears_timestamp() -> None:
    wl = WorkflowLog()
    wl.submit_to_rik()
    wl.revert_rik_submission()
    assert wl.submitted_to_rik_ts == 0
    assert not wl.submitted_to_rik()


# ── GenerationLog.is_izmena_mode gate ────────────────────────────────────────


def test_is_izmena_mode_requires_phase3_and_rik() -> None:
    gl = GenerationLog()

    # Neither condition met.
    assert not gl.is_izmena_mode("stalni")

    # Only phase3 done — not enough.
    gl.record_phase("stalni", "phase3")
    assert not gl.is_izmena_mode("stalni")

    # Both conditions met.
    gl.stalni.submit_to_rik()
    assert gl.is_izmena_mode("stalni")


def test_is_izmena_mode_only_rik_not_enough() -> None:
    """submitted_to_rik without phase3 is not izmena mode — no resenja generated yet."""
    gl = GenerationLog()
    gl.stalni.submit_to_rik()
    assert not gl.is_izmena_mode("stalni")


def test_is_izmena_mode_independent_per_slug() -> None:
    """Stalni in izmena mode must not bleed into prosireni."""
    gl = GenerationLog()
    gl.record_phase("stalni", "phase3")
    gl.stalni.submit_to_rik()
    assert gl.is_izmena_mode("stalni")
    assert not gl.is_izmena_mode("prosireni")


# ── GenerationLog serialization round-trip ───────────────────────────────────


def test_generation_log_roundtrips_submitted_to_rik_ts() -> None:
    gl = GenerationLog(election_uuid="test-uuid")
    gl.stalni.submit_to_rik()
    ts = gl.stalni.submitted_to_rik_ts

    restored = GenerationLog.from_dict(gl.to_dict())
    assert restored.stalni.submitted_to_rik_ts == ts
    assert restored.stalni.submitted_to_rik()
    assert not restored.prosireni.submitted_to_rik()


def test_generation_log_from_empty_dict_defaults_to_zero() -> None:
    """Legacy generation_log.json files without submitted_to_rik_ts load cleanly."""
    gl = GenerationLog.from_dict({})
    assert gl.stalni.submitted_to_rik_ts == 0
    assert gl.prosireni.submitted_to_rik_ts == 0
    assert not gl.stalni.submitted_to_rik()


def test_generation_log_revert_persists_through_roundtrip() -> None:
    gl = GenerationLog()
    gl.prosireni.submit_to_rik()
    gl.prosireni.revert_rik_submission()

    restored = GenerationLog.from_dict(gl.to_dict())
    assert restored.prosireni.submitted_to_rik_ts == 0
    assert not restored.prosireni.submitted_to_rik()


# ── app_paths.popunjeni_odbijeno_dir ─────────────────────────────────────────


def test_popunjeni_odbijeno_dir_name_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import app_paths
    d = app_paths.popunjeni_odbijeno_dir()
    assert d.name == "popunjeni_odbijeno"
    assert d.parent == app_paths.home()
    assert d.is_dir()
