"""Per-row validation: JMBG, name, phone, duplicates.

These are pure functions over data already loaded into Person objects.
They return Issue lists that the caller appends to a ValidationReport.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from biracki_odbor.core import gender as gender_mod
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core.models import FUNCTIONS, Issue, Person
from biracki_odbor.validation.reports import Codes, message


# Cyrillic letters (uppercase + lowercase ranges) + space + apostrophe + hyphen
_CYRILLIC_NAME_RE = re.compile(r"^[Ѐ-ӿ\s\-'`’]+$")


def validate_person(
    p: Person, *,
    file: str = "",
    row: int | None = None,
    candidate_jmbgs: set[str] | None = None,
    election_date: date | None = None,
    spec: object = None,
) -> list[Issue]:
    """Return all issues for a single Person record.

    Empty rows (no name) yield no issues — they're "not yet filled",
    not errors. Filled rows must pass JMBG + name shape.

    Optional context:
      candidate_jmbgs: set of JMBGs from `ElectionConfig.candidacies`.
        When the member's JMBG is in this set, emit PERSON_IS_CANDIDATE
        as an error — a candidate cannot also serve on the бирачки
        одбор (plan §1.1, B1). Pass `None` to skip the check entirely;
        legacy callers that haven't been threaded through yet keep
        working unchanged.
      election_date: when set, members whose JMBG-encoded birthdate
        leaves them under 18 on this date get PERSON_UNDER_18 as
        an error (plan B2). `None` skips the check.
      spec: pass the caller's WorkflowSpec so the function-name check
        below recognizes prosireni's dynamic "Члан [N]" / "Заменик
        члана [N]" slots -- without it, EVERY prosireni row previously
        failed FUNCTION_UNKNOWN, since prosireni's function strings
        never appear in the fixed stalni FUNCTIONS tuple. `None`
        (default) keeps the stalni-only FUNCTIONS check.
    """
    if not p.is_filled:
        return []

    issues: list[Issue] = []

    # Name
    name = p.name.strip()
    if not name:
        issues.append(Issue(
            code=Codes.NAME_EMPTY,
            message_sr=message(Codes.NAME_EMPTY),
            severity="error",
            file=file, row=row,
        ))
    elif not _CYRILLIC_NAME_RE.match(name):
        issues.append(Issue(
            code=Codes.NAME_NON_CYRILLIC,
            message_sr=message(Codes.NAME_NON_CYRILLIC, detail=name),
            severity="warning",   # warning not error — bilingual names exist
            file=file, row=row, detail=name,
        ))

    # JMBG
    jmbg_str = jmbg_mod.normalize(p.jmbg)
    if not jmbg_str or len(jmbg_str) != 13:
        issues.append(Issue(
            code=Codes.JMBG_BAD_FORMAT,
            message_sr=message(Codes.JMBG_BAD_FORMAT, detail=p.jmbg or "(празно)"),
            severity="error",
            file=file, row=row, detail=str(p.jmbg or ""),
        ))
    elif not jmbg_mod.is_valid(jmbg_str):
        issues.append(Issue(
            code=Codes.JMBG_BAD_CHECKSUM,
            message_sr=message(Codes.JMBG_BAD_CHECKSUM, detail=jmbg_str),
            severity="error",
            file=file, row=row, detail=jmbg_str,
        ))
    else:
        # Only cross-check gender when JMBG itself is structurally valid —
        # no point comparing a typo to the name. Both sides may be
        # undetermined (foreign first name, or rare exception); only emit
        # the warning when both sides resolve and disagree.
        jmbg_sex = jmbg_mod.gender(jmbg_str)
        name_sex = gender_mod.infer_from_first_name(p.first_name)
        if jmbg_sex and name_sex and jmbg_sex != name_sex:
            issues.append(Issue(
                code=Codes.JMBG_GENDER_MISMATCH,
                message_sr=message(Codes.JMBG_GENDER_MISMATCH, detail=name),
                severity="warning",
                file=file, row=row, detail=name,
            ))

        # B1 — committee/candidate cross-check. Block this person if
        # their JMBG appears in the candidacies registry. Hard reject
        # because the law doesn't allow simultaneous service.
        if candidate_jmbgs and jmbg_str in candidate_jmbgs:
            issues.append(Issue(
                code=Codes.PERSON_IS_CANDIDATE,
                message_sr=message(Codes.PERSON_IS_CANDIDATE, detail=jmbg_str),
                severity="error",
                file=file, row=row, detail=jmbg_str,
            ))

        # B2 — age ≥ 18 on election day. Runs only when the caller
        # provides election_date; pre-Phase-D callers (e.g. existing
        # phase2_aggregate without the new arg) skip this check, so
        # the existing test suite stays green by design.
        if election_date is not None and not jmbg_mod.is_at_least_18_on(
            jmbg_str, election_date,
        ):
            issues.append(Issue(
                code=Codes.PERSON_UNDER_18,
                message_sr=message(Codes.PERSON_UNDER_18, detail=jmbg_str),
                severity="error",
                file=file, row=row, detail=jmbg_str,
            ))

    # Phone (only when present — phone may legitimately be left blank)
    phone = p.telefon.strip()
    if phone and len(re.sub(r"\D", "", phone)) < 6:
        issues.append(Issue(
            code=Codes.PHONE_TOO_SHORT,
            message_sr=message(Codes.PHONE_TOO_SHORT, detail=phone),
            severity="warning",
            file=file, row=row, detail=phone,
        ))

    # Function
    if spec is not None and getattr(spec, "slug", None) == "prosireni":
        from biracki_odbor.core.prosireni_allocation import parse_slot_function
        function_ok = parse_slot_function(p.function) is not None
    else:
        function_ok = p.function in FUNCTIONS
    if not function_ok:
        issues.append(Issue(
            code=Codes.FUNCTION_UNKNOWN,
            message_sr=message(Codes.FUNCTION_UNKNOWN, detail=p.function),
            severity="error",
            file=file, row=row, detail=p.function,
        ))

    return issues


def find_duplicate_jmbgs(persons: list[Person]) -> list[Issue]:
    """Cross-row check: same JMBG appearing in multiple rows (any party).

    This is the input for Phase 2.5 conflict resolution.
    Returns one issue per duplicated JMBG (not per duplicate row).
    """
    seen: dict[str, list[Person]] = {}
    for p in persons:
        if not p.is_filled:
            continue
        key = jmbg_mod.normalize(p.jmbg)
        if not key or not jmbg_mod.is_valid(key):
            continue
        seen.setdefault(key, []).append(p)

    issues: list[Issue] = []
    for j, occurrences in seen.items():
        if len(occurrences) > 1:
            issues.append(Issue(
                code=Codes.JMBG_DUPLICATE,
                message_sr=message(Codes.JMBG_DUPLICATE, detail=j),
                severity="error",
                detail=j,
            ))
    return issues


def find_cross_workflow_duplicate_jmbgs(
    persons: list[Person],
    other_workflow_jmbgs: set[str],
    other_workflow_label: str,
) -> list[Issue]:
    """A person already holding a filled seat in the OTHER workflow's
    committee (стални vs проширени) can't also hold one here.

    `other_workflow_jmbgs` — normalized JMBGs already filled in the other
    workflow's master. `other_workflow_label` — the other workflow's
    locative composition phrase (`WorkflowSpec.resenja_item_i_intro`,
    e.g. "сталном саставу"), substituted directly into the message.
    """
    issues: list[Issue] = []
    for p in persons:
        if not p.is_filled:
            continue
        key = jmbg_mod.normalize(p.jmbg)
        if not key or not jmbg_mod.is_valid(key):
            continue
        if key in other_workflow_jmbgs:
            issues.append(Issue(
                code=Codes.PERSON_IN_OTHER_WORKFLOW,
                message_sr=message(
                    Codes.PERSON_IN_OTHER_WORKFLOW,
                    detail=key, other_workflow=other_workflow_label,
                ),
                severity="error",
                detail=key,
            ))
    return issues


def other_workflow_filled_jmbgs(master_path: Path | str, other_spec: object) -> set[str]:
    """Normalized JMBGs already filled in the OTHER workflow's committee,
    read live from the shared master DB.

    Shared by Phase 2's soft check (flags a cross-workflow collision as
    an error the operator can still save past and resolve in
    Corrections — never a hard block) and Phase 3's preflight gate
    (the actual block: producing a решење that appoints an
    already-double-seated person is the costly mistake, not importing
    the data). A DB-level trigger used to hard-block this at Phase 2's
    own write instead — the only way to "recover" from that abort was
    to mutate the colliding person's JMBG to blank, which hid the
    collision from every downstream duplicate-detection mechanism
    instead of surfacing it. See core/master_io.py's schema history.
    """
    from biracki_odbor.core.master_io import read_master as _read_master
    try:
        other_persons = _read_master(Path(master_path), spec=other_spec)
    except Exception:  # noqa: BLE001 — best-effort cross-check, never block on a read error
        return set()
    result = {
        jmbg_mod.normalize(p.jmbg)
        for p in other_persons if p.is_filled and p.jmbg
    }
    result.discard("")
    return result
