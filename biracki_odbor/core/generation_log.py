"""Persistent per-election-cycle generation log.

Tracks which phases have run (and when) for both stalni and prosireni
workflows.  Used to:
  - gate the Измене tab (needs phase3 done + past cutoff)
  - gate Решења tab after izmena mode activates
  - assign correct amendment index numbers when auto-generating izmene

Keyed by ``election_uuid`` so the log resets automatically when the
operator starts a new election cycle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class WorkflowLog:
    phase1_last: str = ""   # ISO timestamp or ""
    phase2_last: str = ""
    phase3_last: str = ""
    izmene_per_bm: dict[str, int] = field(default_factory=dict)  # str(bm) → count
    # Unix epoch of the first Phase 1 run in this cycle. Embedded in every
    # Phase 1 .xlsx marker as part of the compound file UID. Stays fixed on
    # normal re-runs ("Поново покрени"); advances only when the operator
    # explicitly clicks "Поништи и поново генериши", making old distributed
    # files identifiable as stale at Phase 2 import time.
    phase1_run_ts: int = 0
    # Unix epoch of when the operator clicked "Предато РИК-у". Zero = not yet
    # submitted. Once set, Phase 3 regeneration is disabled and every
    # correction produces a formal Решење о измени решења.
    submitted_to_rik_ts: int = 0
    # Unix epoch of when the operator clicked "Заустави пријем пријава"
    # (stalni only). Zero = not yet declared. Once set: the chief's
    # authority to fill empty slots starts, Phase 2 party-file imports
    # are hard-blocked, and the nacelnik xlsx template is generated
    # exactly once. Deliberately NOT derived from cutoff_stalni alone —
    # the date only gates whether the button *can* be clicked; the
    # click itself is the actual legal event (see TODO.md §21 history —
    # a pure date check can't account for e.g. accepted late submissions
    # by post/CD at the operator's discretion).
    nacelnik_takeover_ts: int = 0
    # Count of nacelnik appointments made since takeover — revert guard,
    # same role as izmene_per_bm plays for submitted_to_rik.
    nacelnik_appointments: int = 0

    def phase3_done(self) -> bool:
        return bool(self.phase3_last)

    def submitted_to_rik(self) -> bool:
        return self.submitted_to_rik_ts != 0

    def submit_to_rik(self) -> None:
        import time as _time
        if self.submitted_to_rik_ts == 0:
            self.submitted_to_rik_ts = int(_time.time())

    def revert_rik_submission(self) -> None:
        """Only valid when zero amendments have been generated."""
        self.submitted_to_rik_ts = 0

    def nacelnik_takeover_started(self) -> bool:
        return self.nacelnik_takeover_ts != 0

    def start_nacelnik_takeover(self) -> None:
        import time as _time
        if self.nacelnik_takeover_ts == 0:
            self.nacelnik_takeover_ts = int(_time.time())

    def revert_nacelnik_takeover(self) -> None:
        """Only valid when zero nacelnik appointments have been made."""
        self.nacelnik_takeover_ts = 0
        self.nacelnik_appointments = 0

    def record_nacelnik_appointment(self, count: int = 1) -> None:
        self.nacelnik_appointments += count

    def next_amendment_index(self, bm_number: int) -> int:
        return self.izmene_per_bm.get(str(bm_number), 0) + 1

    def record_izmena(self, bm_number: int) -> None:
        key = str(bm_number)
        self.izmene_per_bm[key] = self.izmene_per_bm.get(key, 0) + 1


def _wl_to_dict(wl: WorkflowLog) -> dict:
    return {
        "phase1_last": wl.phase1_last,
        "phase2_last": wl.phase2_last,
        "phase3_last": wl.phase3_last,
        "izmene_per_bm": dict(wl.izmene_per_bm),
        "phase1_run_ts": wl.phase1_run_ts,
        "submitted_to_rik_ts": wl.submitted_to_rik_ts,
        "nacelnik_takeover_ts": wl.nacelnik_takeover_ts,
        "nacelnik_appointments": wl.nacelnik_appointments,
    }


def _wl_from_dict(d: dict) -> WorkflowLog:
    return WorkflowLog(
        phase1_last=d.get("phase1_last") or "",
        phase2_last=d.get("phase2_last") or "",
        phase3_last=d.get("phase3_last") or "",
        izmene_per_bm={
            str(k): int(v)
            for k, v in (d.get("izmene_per_bm") or {}).items()
        },
        phase1_run_ts=int(d.get("phase1_run_ts") or 0),
        submitted_to_rik_ts=int(d.get("submitted_to_rik_ts") or 0),
        nacelnik_takeover_ts=int(d.get("nacelnik_takeover_ts") or 0),
        nacelnik_appointments=int(d.get("nacelnik_appointments") or 0),
    )


@dataclass
class GenerationLog:
    election_uuid: str = ""
    stalni: WorkflowLog = field(default_factory=WorkflowLog)
    prosireni: WorkflowLog = field(default_factory=WorkflowLog)

    def workflow(self, slug: str) -> WorkflowLog:
        return self.prosireni if slug == "prosireni" else self.stalni

    def record_phase(self, slug: str, phase: str) -> None:
        """Set {phase}_last to now for the given workflow."""
        wl = self.workflow(slug)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        setattr(wl, f"{phase}_last", ts)

    def is_izmena_mode(self, slug: str) -> bool:
        """True when phase3 has run AND the operator has confirmed RIK submission."""
        wl = self.workflow(slug)
        return wl.phase3_done() and wl.submitted_to_rik()

    def to_dict(self) -> dict:
        return {
            "election_uuid": self.election_uuid,
            "stalni": _wl_to_dict(self.stalni),
            "prosireni": _wl_to_dict(self.prosireni),
        }

    @classmethod
    def from_dict(cls, d: dict) -> GenerationLog:
        return cls(
            election_uuid=d.get("election_uuid", ""),
            stalni=_wl_from_dict(d.get("stalni") or {}),
            prosireni=_wl_from_dict(d.get("prosireni") or {}),
        )


def load(path: Path, election_uuid: str) -> GenerationLog:
    """Load from disk; return a fresh log if file absent or UUID mismatch."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return GenerationLog(election_uuid=election_uuid)
    gl = GenerationLog.from_dict(data)
    if gl.election_uuid != election_uuid:
        return GenerationLog(election_uuid=election_uuid)
    return gl


def save(log: GenerationLog, path: Path) -> None:
    path.write_text(
        json.dumps(log.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
