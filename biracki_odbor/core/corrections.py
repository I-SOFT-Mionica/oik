"""Phase 2.5: conflict detection, manual edits, and audit log.

Real-world blockers this module addresses:

  1. Two parties submit the same person. A person can only fill one
     slot, so one party must replace; the OIK must record which.

  2. After party returns are in, a person withdraws (illness, refusal,
     legal disqualification). The OIK must record the swap.

  3. Pure typo fixes — name, phone, address — without re-running Phase 1
     or asking the party to resubmit.

Every edit is appended to `corrections.log` (JSON Lines), which is an
append-only audit trail. The corrected state lives in memory as a list
of Person objects; the GUI calls `write_master()` to flush it to disk.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Literal

from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core.models import Conflict, Person


EventType = Literal[
    "resolve_conflict", "replace_member", "edit_member",
    "remove_member", "add_member",
    # Стални workflow only — set when načelnik fills an empty slot
    # after the party either failed to submit or sent ineligible
    # personnel. Distinct event so the accountability log can call
    # these out separately from regular party-side edits.
    "nacelnik_appointment",
    # Party re-submitted a newer file; prior corrections for that
    # party are no longer reflected in the master. Appended as a
    # marker so the audit log can show why earlier edits disappeared.
    "submission_superseded",
    # File arrived after the submission cutoff date. Hard-blocked for
    # email imports; operator-confirmed for manual file dialog imports.
    # The file is moved to popunjeni_odbijeno/ either way.
    "late_submission_blocked",
    # Operator clicked "Предато РИК-у". Locks Phase 3 re-run and
    # activates izmena mode for the workflow.
    "rik_submission",
    # Operator clicked "Заустави пријем пријава" (стални only). Locks
    # party-file imports in Phase 2 and activates the chief's authority
    # to fill remaining empty slots.
    "nacelnik_takeover",
    # Operator used "Састави повратни мејл…" (Сви чланови) to draft a
    # correction request back to a party with Phase 2 validation errors.
    # Logged per party the moment drafts are successfully created —
    # purely informational (unlike submission_superseded, doesn't
    # invalidate anything), so the audit trail shows the round-trip
    # happened without the operator having to remember to note it.
    "reply_email_sent",
]


# Prefix the operator's note always gets when appointing via the
# načelnik action so log readers can scan for it visually. The
# remainder of the note (free-text reason) is appended by the caller.
NACELNIK_NOTE_PREFIX = "Именовао начелник"


class NacelnikTakeoverNotStartedError(Exception):
    """Raised by `appoint_by_nacelnik` when `nacelnik_gate_enabled` is True
    and `nacelnik_takeover_active` is False — the chief only gains legal
    authority to fill unfilled slots once the operator has explicitly
    declared submissions closed (Закон о избору народних посланика, чл.
    37 ст. 2). Deliberately NOT derived from `cutoff_passed()` alone — a
    calendar date can't account for a municipality still accepting late
    submissions by some other means at the operator's discretion; the
    explicit declaration (`WorkflowLog.start_nacelnik_takeover`) is the
    actual legal event. Unlike overwriting an already-filled slot
    (deliberately allowed, see `appoint_by_nacelnik`'s docstring), this
    is a hard block with no manual override."""


def cutoff_passed(cutoff_stalni: str, *, today: date | None = None) -> bool:
    """True iff `today` is strictly after the ISO date `cutoff_stalni`.

    An empty or unparseable cutoff returns False. Used only as a
    precondition on the "stop accepting submissions" button itself
    (can't be clicked before the deadline) — NOT as the nacelnik
    appointment gate directly; see `NacelnikTakeoverNotStartedError`.
    """
    if not cutoff_stalni:
        return False
    try:
        cutoff = date.fromisoformat(cutoff_stalni)
    except ValueError:
        return False
    return (today or date.today()) > cutoff


@dataclass
class AuditEvent:
    """One row in corrections.log."""

    timestamp: str             # ISO 8601 with timezone
    operator: str              # Windows username
    event_type: EventType
    conflict_id: str = ""      # filled when relevant
    slot_bm: int | None = None
    slot_function: str = ""
    before: dict | None = None
    after: dict | None = None
    note: str = ""
    # чл. 14. став 1. тачка 8) / чл. 15 cross-municipality double
    # appointment (see core.prestanak_docx) — the OTHER appointment's BM
    # and municipality, when the operator flagged this person with that
    # Напомена reason. Real fields rather than parsing them back out of
    # `note`'s free-text sentence — old log lines without them just read
    # as None/"".
    other_bm: int | None = None
    other_municipality: str = ""
    # The other municipality's own decision number for that appointment,
    # when the operator already knows it (RIK's notice or the list
    # submitter usually names it) — the existing seat's decision DATE
    # still isn't captured here, since that's less reliably known at
    # flagging time; see gui.tabs.prestanak_panel.load_draft.
    other_decision_broj: str = ""

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _operator() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "(непознат)"


# ── Conflict detection ────────────────────────────────────────────────

def _conflict_id(jmbg: str) -> str:
    return hashlib.sha1(jmbg.encode("utf-8")).hexdigest()[:12]


def _by_jmbg(persons: Iterable[Person]) -> dict[str, list[Person]]:
    grouped: dict[str, list[Person]] = {}
    for p in persons:
        if not p.is_filled:
            continue
        key = jmbg_mod.normalize(p.jmbg)
        if not key or not jmbg_mod.is_valid(key):
            continue
        grouped.setdefault(key, []).append(p)
    return grouped


def detect_conflicts(
    persons: Iterable[Person],
    *,
    other_workflow_persons: Iterable[Person] = (),
    election_uuid: str = "",
    other_workflow_label: str = "",
) -> list[Conflict]:
    """Group filled persons by JMBG and return groups with > 1 occurrence,
    plus (when `other_workflow_persons` is given) any person who also
    holds a filled seat in the OTHER workflow (стални vs проширени) —
    attached as `Conflict.cross_workflow`, read-only here since
    resolving it means editing the other workflow's own data.

    Each conflict gets a stable conflict_id (sha1 prefix of the JMBG) so
    the GUI can persist its 'resolved' state across reloads.

    `election_uuid`, when given, additionally populates
    `Conflict.submission_times` (slot -> the submitting party's latest
    received_time_iso from popunjeni_cache) so the operator can see
    submission order when deciding which to keep — omitted (empty
    dict) when not given, since not every caller tracks an election
    cycle (e.g. legacy/test callers with no cache to query)."""
    by_jmbg = _by_jmbg(persons)
    other_by_jmbg = _by_jmbg(other_workflow_persons)

    def _times_for(people: list[Person]) -> dict[int, str]:
        if not election_uuid:
            return {}
        from biracki_odbor.core import popunjeni_cache
        out: dict[int, str] = {}
        for p in people:
            if p.party:
                out[id(p)] = popunjeni_cache.latest_submission_received_time_for_party(
                    election_uuid, p.party,
                )
        return out

    conflicts: list[Conflict] = []
    for jmbg, occurrences in by_jmbg.items():
        cross = other_by_jmbg.get(jmbg, [])
        if len(occurrences) > 1 or cross:
            times = _times_for(occurrences)
            times.update(_times_for(cross))
            conflicts.append(Conflict(
                conflict_id=_conflict_id(jmbg),
                jmbg=jmbg,
                name=occurrences[0].name,
                submissions=list(occurrences),
                cross_workflow=list(cross),
                submission_times=times,
                other_workflow_label=other_workflow_label if cross else "",
            ))
    conflicts.sort(key=lambda c: (c.name, c.jmbg))
    return conflicts


def errors_by_jmbg(report) -> dict[str, list]:
    """Index a ValidationReport's error-severity issues by JMBG.

    Shared by Phase 2 (reply-email / export-errors — built right after
    a run, from `Phase2Result.report`) and Corrections' Сви чланови
    table (row highlighting — built from the last report AppState
    cached). Only issues whose `.detail` is a 13-digit JMBG participate;
    codes that put a filename/column name into `.detail` are ignored.
    """
    result: dict[str, list] = {}
    if report is None:
        return result
    for issue in report.issues:
        if issue.severity != "error":
            continue
        jmbg = (issue.detail or "").strip()
        if not jmbg or not jmbg.isdigit() or len(jmbg) != 13:
            continue
        result.setdefault(jmbg, []).append(issue)
    return result


# ── Mutations ────────────────────────────────────────────────────────

@dataclass
class CorrectionsState:
    """In-memory state managed by the Corrections tab.

    persons: the aggregated list from Phase 2 (mutated in place).
    log_path: where to append audit events.
    """

    persons: list[Person]
    log_path: Path
    events: list[AuditEvent] = field(default_factory=list)
    # §21 gate for appoint_by_nacelnik. nacelnik_gate_enabled is opt-in
    # and off by default so existing/other callers that don't care are
    # unaffected — only CorrectionsTab's stalni workflow turns it on;
    # prošireni has no legal nacelnik concept, so it stays ungated.
    # nacelnik_takeover_active reflects the operator's explicit "stop
    # accepting submissions" declaration (WorkflowLog.nacelnik_takeover_ts),
    # NOT a calendar-date check — see NacelnikTakeoverNotStartedError.
    nacelnik_takeover_active: bool = False
    nacelnik_gate_enabled: bool = False

    def _append(self, event: AuditEvent) -> None:
        self.events.append(event)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(event.to_jsonl() + "\n")

    # ── Conflict resolution ──

    def resolve_conflict(
        self,
        conflict: Conflict,
        *,
        keep_slot_key: tuple[int, str],
        note: str = "",
    ) -> None:
        """Keep the submission at `keep_slot_key`; clear the other slots.

        Identifying the winner by `(bm_number, function)` instead of by
        party name correctly handles the case where the SAME party listed
        the same JMBG twice (e.g. once at БМ 1 Председник, once at БМ 3
        Члан 1). Matching only on party name would have left both rows
        untouched — the v0.5.0 bug a field user hit.

        Cleared submissions become empty slots (preserving bm/function/party
        scaffolding) so the responsible party can re-submit a replacement.
        """
        target: Person | None = None
        for sub in conflict.submissions:
            for p in self.persons:
                if p.slot_key == sub.slot_key and p.party == sub.party:
                    if p.slot_key == keep_slot_key and p.party == sub.party:
                        target = p
                        continue
                    before = p.to_dict()
                    p.name = ""
                    p.jmbg = p.mesto = p.adresa = p.telefon = p.email = ""
                    p.appointed_by_nacelnik = False
                    self._append(AuditEvent(
                        timestamp=_now_iso(),
                        operator=_operator(),
                        event_type="resolve_conflict",
                        conflict_id=conflict.conflict_id,
                        slot_bm=p.bm_number,
                        slot_function=p.function,
                        before=before,
                        after=p.to_dict(),
                        note=(
                            f"Чисти се у корист слота БМ {keep_slot_key[0]},"
                            f" {keep_slot_key[1]}. {note}"
                        ).strip(),
                    ))
        # Also log the kept side for traceability.
        if target is not None:
            self._append(AuditEvent(
                timestamp=_now_iso(),
                operator=_operator(),
                event_type="resolve_conflict",
                conflict_id=conflict.conflict_id,
                slot_bm=target.bm_number,
                slot_function=target.function,
                before=None,
                after=target.to_dict(),
                note=(
                    f"Задржава се слот БМ {target.bm_number},"
                    f" {target.function} ({target.party}). {note}"
                ).strip(),
            ))

    def remove_one_slot(
        self,
        conflict: Conflict,
        slot_key: tuple[int, str],
        *,
        note: str = "",
    ) -> None:
        """Clear a single slot involved in a conflict; leave the others.

        Useful when a multi-way conflict needs piecemeal resolution —
        e.g. three submissions and the operator wants to drop just one
        without committing to which of the remaining two to keep. The
        audit trail tags the event with the conflict_id so the log
        groups cleanly with the rest of the resolution flow.
        """
        for p in self.persons:
            if p.slot_key == slot_key:
                before = p.to_dict()
                p.name = ""
                p.jmbg = p.mesto = p.adresa = p.telefon = p.email = ""
                p.appointed_by_nacelnik = False
                self._append(AuditEvent(
                    timestamp=_now_iso(),
                    operator=_operator(),
                    event_type="resolve_conflict",
                    conflict_id=conflict.conflict_id,
                    slot_bm=p.bm_number,
                    slot_function=p.function,
                    before=before,
                    after=p.to_dict(),
                    note=f"Уклоњен само овај слот из конфликта. {note}".strip(),
                ))
                return

    def remove_from_all(self, conflict: Conflict, *, note: str = "") -> None:
        """Resolve by clearing the person from every submitting party."""
        for sub in conflict.submissions:
            for p in self.persons:
                if p.slot_key == sub.slot_key and p.party == sub.party:
                    before = p.to_dict()
                    p.name = p.jmbg = p.mesto = p.adresa = p.telefon = p.email = ""
                    p.appointed_by_nacelnik = False
                    self._append(AuditEvent(
                        timestamp=_now_iso(),
                        operator=_operator(),
                        event_type="resolve_conflict",
                        conflict_id=conflict.conflict_id,
                        slot_bm=p.bm_number,
                        slot_function=p.function,
                        before=before,
                        after=p.to_dict(),
                        note=f"Уклоњено из свих странака. {note}".strip(),
                    ))

    # ── Manual edits ──

    def edit_member(
        self,
        bm_number: int,
        function: str,
        new_values: dict,
        *,
        note: str = "",
        other_bm: int | None = None,
        other_municipality: str = "",
        other_decision_broj: str = "",
    ) -> Person | None:
        """Edit a single slot in place. Returns the updated Person."""
        for p in self.persons:
            if p.slot_key == (bm_number, function):
                before = p.to_dict()
                for k, v in new_values.items():
                    if hasattr(p, k):
                        setattr(p, k, str(v).strip() if isinstance(v, str) else v)
                self._append(AuditEvent(
                    timestamp=_now_iso(),
                    operator=_operator(),
                    event_type="edit_member",
                    slot_bm=bm_number,
                    slot_function=function,
                    before=before,
                    after=p.to_dict(),
                    note=note,
                    other_bm=other_bm,
                    other_municipality=other_municipality,
                    other_decision_broj=other_decision_broj,
                ))
                return p
        return None

    def replace_member(
        self,
        bm_number: int,
        function: str,
        replacement: dict,
        *,
        note: str = "",
        other_bm: int | None = None,
        other_municipality: str = "",
        other_decision_broj: str = "",
    ) -> Person | None:
        """Swap a person out (e.g. illness, withdrawal). Same as edit_member
        but logged with a distinct event_type so audit trails read cleanly.
        """
        for p in self.persons:
            if p.slot_key == (bm_number, function):
                before = p.to_dict()
                for k, v in replacement.items():
                    if hasattr(p, k):
                        setattr(p, k, str(v).strip() if isinstance(v, str) else v)
                self._append(AuditEvent(
                    timestamp=_now_iso(),
                    operator=_operator(),
                    event_type="replace_member",
                    slot_bm=bm_number,
                    slot_function=function,
                    before=before,
                    after=p.to_dict(),
                    note=note,
                    other_bm=other_bm,
                    other_municipality=other_municipality,
                    other_decision_broj=other_decision_broj,
                ))
                return p
        return None

    def appoint_by_nacelnik(
        self,
        bm_number: int,
        function: str,
        new_values: dict,
        *,
        note: str = "",
        other_bm: int | None = None,
        other_municipality: str = "",
        other_decision_broj: str = "",
    ) -> Person | None:
        """Fill an empty slot with a načelnik appointment.

        Same write path as `edit_member` — the slot's Person record
        is mutated in place — but the audit event uses the
        `nacelnik_appointment` type AND the note is rewritten to
        carry the standard prefix so log readers can scan for it.

        Returns the updated `Person` or None when no slot matches
        the `(bm_number, function)` key (defensive guard for callers
        that compute the key from stale state).

        Pre-v1 callers should ONLY use this when the slot is actually
        empty — the Phase 2.5 UI gates the action accordingly. The
        method itself doesn't refuse to overwrite a non-empty slot,
        though, so power-users can correct a mistake by clearing the
        slot first and re-appointing.

        Raises `NacelnikTakeoverNotStartedError` when `nacelnik_gate_enabled`
        is True and `nacelnik_takeover_active` is False — this check has
        NO manual override, unlike the overwrite-a-filled-slot allowance
        above: the chief simply has no legal authority yet.
        """
        if self.nacelnik_gate_enabled and not self.nacelnik_takeover_active:
            raise NacelnikTakeoverNotStartedError(
                "Operater još nije zaustavio prijem prijava od stranaka —"
                " načelnik nema ovlašćenje da popunjava slotove."
            )
        for p in self.persons:
            if p.slot_key == (bm_number, function):
                before = p.to_dict()
                for k, v in new_values.items():
                    if hasattr(p, k):
                        setattr(
                            p, k,
                            str(v).strip() if isinstance(v, str) else v,
                        )
                p.appointed_by_nacelnik = True
                # Compose the note: always carries the prefix; the
                # operator's free-text reason (when given) follows
                # a thin em-dash separator.
                reason = (note or "").strip()
                logged_note = (
                    f"{NACELNIK_NOTE_PREFIX} — {reason}"
                    if reason else NACELNIK_NOTE_PREFIX
                )
                self._append(AuditEvent(
                    timestamp=_now_iso(),
                    operator=_operator(),
                    event_type="nacelnik_appointment",
                    slot_bm=bm_number,
                    slot_function=function,
                    before=before,
                    after=p.to_dict(),
                    note=logged_note,
                    other_bm=other_bm,
                    other_municipality=other_municipality,
                    other_decision_broj=other_decision_broj,
                ))
                return p
        return None

    def clear_member(self, bm_number: int, function: str, *, note: str = "") -> None:
        """Empty a slot without removing it from the schedule."""
        for p in self.persons:
            if p.slot_key == (bm_number, function):
                before = p.to_dict()
                p.name = p.jmbg = p.mesto = p.adresa = p.telefon = p.email = ""
                p.appointed_by_nacelnik = False
                self._append(AuditEvent(
                    timestamp=_now_iso(),
                    operator=_operator(),
                    event_type="remove_member",
                    slot_bm=bm_number,
                    slot_function=function,
                    before=before,
                    after=p.to_dict(),
                    note=note,
                ))
                return


# ── Audit log helpers ─────────────────────────────────────────────────

def read_log(log_path: Path | str) -> list[dict]:
    p = Path(log_path)
    if not p.exists():
        return []
    events: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def count_party_corrections(log_path: Path | str, party: str) -> int:
    """Count active (non-superseded) manual-edit events for a specific party.

    An event "belongs to" a party when its before or after snapshot has a
    matching ``party`` field. Stops counting at any ``submission_superseded``
    event for the same party (those mark the point at which corrections were
    invalidated by a re-submission, so anything before them is already
    acknowledged as superseded).
    """
    events = read_log(log_path)
    count = 0
    manual_types = {"resolve_conflict", "replace_member", "edit_member",
                    "remove_member", "add_member", "nacelnik_appointment"}
    for ev in reversed(events):
        et = ev.get("event_type", "")
        if et == "submission_superseded" and ev.get("note", "").find(party) != -1:
            break
        if et not in manual_types:
            continue
        before = ev.get("before") or {}
        after = ev.get("after") or {}
        if before.get("party") == party or after.get("party") == party:
            count += 1
    return count


def append_submission_superseded(
    log_path: Path | str,
    party: str,
    new_filename: str,
    prior_corrections: int,
) -> None:
    """Append a submission_superseded tombstone event to the corrections log."""
    event = AuditEvent(
        timestamp=_now_iso(),
        operator=_operator(),
        event_type="submission_superseded",
        note=(
            f"Нова пријава странке '{party}' увезена ({new_filename}). "
            f"Поништено {prior_corrections} ручних исправки."
        ),
    )
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_jsonl() + "\n")


def append_rik_submission(log_path: Path | str, slug: str) -> None:
    """Append a rik_submission audit event when the operator marks решења as submitted to RIK."""
    event = AuditEvent(
        timestamp=_now_iso(),
        operator=_operator(),
        event_type="rik_submission",
        note=f"Решења сталног састава предата РИК-у (workflow={slug}).",
    )
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_jsonl() + "\n")


def append_nacelnik_takeover(log_path: Path | str, slug: str) -> None:
    """Append a nacelnik_takeover audit event when the operator declares
    party submissions closed and the chief takes over unfilled slots."""
    event = AuditEvent(
        timestamp=_now_iso(),
        operator=_operator(),
        event_type="nacelnik_takeover",
        note=f"Начелник преузима непопуњене слотове (workflow={slug}).",
    )
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_jsonl() + "\n")


def append_reply_email_sent(log_path: Path | str, party: str, n_errors: int) -> None:
    """Append a reply_email_sent audit event after a correction-request
    draft was successfully created for `party`."""
    event = AuditEvent(
        timestamp=_now_iso(),
        operator=_operator(),
        event_type="reply_email_sent",
        note=(
            f"Повратни мејл састављен за странку '{party}'"
            f" — {n_errors} грешка(е) у последњем увозу."
        ),
    )
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_jsonl() + "\n")


def append_late_submission_blocked(
    log_path: Path | str,
    filename: str,
    party: str,
    received_iso: str,
    cutoff_iso: str,
    *,
    source: str = "outlook",
) -> None:
    """Append a late_submission_blocked event to the corrections log.

    Called when a file's received timestamp falls after the submission cutoff.
    For email (Outlook) imports this is always a hard block; for file-dialog
    imports it is operator-confirmed (still logged so the audit trail is clear).
    """
    event = AuditEvent(
        timestamp=_now_iso(),
        operator=_operator(),
        event_type="late_submission_blocked",
        note=(
            f"Фајл '{filename}' странке '{party}' одбачен — примљен {received_iso[:10]},"
            f" рок је истекао {cutoff_iso}. Извор: {source}."
        ),
    )
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(event.to_jsonl() + "\n")
