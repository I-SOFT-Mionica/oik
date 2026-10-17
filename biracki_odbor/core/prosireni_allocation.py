"""Prošireni-sastav allocation: compute slot structure from candidacies registry.

Each canonical entity (resolved via B3 link-chain) receives two slots per BM:
  - "Члан [N]"          — primary member (Члан)
  - "Заменик клана [N]" — substitute (Заменик клана)

where N is the 1-based canonical-entity slot index, determined by:
  sort key = (LEVEL_PRIORITY[canonical.level], canonical.submission_order, canonical.entity_id)

These function strings are written into the locked Функција column of each
entity's popunjeni workbook and are later read back by phase2_aggregate
exactly as stalni function strings are — no special-case parsing needed
until sort time.

Two helpers:
  - `func_sort_key(func)` → (slot_index, role_index) for phase2_aggregate's
    inner-BM sort (replaces the stalni func_order dict).
  - `parse_slot_function(func)` → (slot, role_idx) | None — same data,
    useful for validation passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from biracki_odbor.config.candidacies import (
    CandidaciesRegistry,
    Entity,
    LEVEL_PRIORITY,
    canonical_entity,
    canonical_entity_name,
)
from biracki_odbor.core.models import Allocation


# ── Role labels (must match PROSIRENI_SPEC.roles[*].label_sr) ─────────

MEMBER_LABEL = "Члан"
SUBSTITUTE_LABEL = "Заменик члана"

# "Заменик клана" (missing "ч") was baked into SUBSTITUTE_LABEL since
# прошиени's first commit and only fixed 2026-10-12 (see master_io.py's
# schema v3 migration). That migration rewrites already-persisted
# committee.db rows, but it can't touch Phase 1 .xlsx files already sent
# to parties, nor already-cached parsed records in popunjeni_cache.json
# -- both still carry the old spelling verbatim. Any code that reads a
# function string from an external source (a popunjeni file, live-parsed
# or cache-hit) must normalize through this before using it as a slot
# key or display text, or an old-format submission's zamenik rows
# silently mismatch the now-corrected allocation keys and get dropped
# as "unfilled". Confirmed in the field: a client's full prošireni
# zamenik roster vanished on the next aggregation after this fix shipped.
_TYPO_SUBSTITUTE_LABEL = "Заменик клана"


def normalize_function_typo(func: str) -> str:
    """Rewrite a stale "Заменик клана" function string to the correct
    "Заменик члана" spelling. A no-op for every other string (stalni
    functions, already-correct prosireni functions)."""
    if _TYPO_SUBSTITUTE_LABEL in func:
        return func.replace(_TYPO_SUBSTITUTE_LABEL, SUBSTITUTE_LABEL)
    return func


_FUNC_RE = re.compile(r"^(.+) \[(\d+)\]$")


# ── Function-string helpers ───────────────────────────────────────────


def slot_function(role_label: str, slot_index: int) -> str:
    """Build the compound function string for a prosireni slot.

    Examples: slot_function("Члан", 1) → "Члан [1]"
              slot_function("Заменик члана", 3) → "Заменик члана [3]"
    """
    return f"{role_label} [{slot_index}]"


def parse_slot_function(func: str) -> tuple[int, int] | None:
    """Parse a prosireni compound function string.

    Returns (slot_index, role_index) or None if `func` is not a
    prosireni compound string (i.e., it's a stalni function).

    role_index: 0 = Члан, 1 = Заменик клана, 99 = unknown.
    """
    m = _FUNC_RE.match(func.strip())
    if not m:
        return None
    role = m.group(1).strip()
    slot = int(m.group(2))
    role_idx = {MEMBER_LABEL: 0, SUBSTITUTE_LABEL: 1}.get(role, 99)
    return (slot, role_idx)


def func_sort_key(func: str) -> tuple[int, int]:
    """Sort key for prosireni function strings.

    Returns (slot_index, role_index). Unknown/stalni strings fall back to
    (99, 99) so they sort last (consistent with func_order.get(..., 99)).
    """
    parsed = parse_slot_function(func)
    return parsed if parsed is not None else (99, 99)


# ── Canonical entity ordering ─────────────────────────────────────────


@dataclass(frozen=True)
class CanonicalSlot:
    """One canonical entity's slot in the prosireni allocation.

    slot_index: 1-based position in the sorted canonical-entity list.
    entity:     the canonical entity object (highest-level in the link group).
    name:       canonical name (same as entity.name at the canonical entity).
    """

    slot_index: int
    entity: Entity
    name: str


def canonical_slots(registry: CandidaciesRegistry) -> list[CanonicalSlot]:
    """Return the ordered list of canonical entity slots.

    Deduplication: multiple linked entities resolve to one canonical entry
    (the one at the highest level).

    Slot numbers are STABLE, not recomputed from a sort every call. The
    law requires OIK to start accepting/processing prosireni nominations
    as soon as the first list registers -- so by the time a later list
    registers, earlier lists may already have generated templates,
    collected filled-in submissions, and been aggregated into the master
    workbook, all keyed by their locked "Члан [N]"/"Заменик клана [N]"
    function strings. If slot numbers were recomputed fresh from
    (level, submission_order, entity_id) on every call, a new list
    registering with a submission_order that sorts between two already-
    slotted entities would shift every later entity's slot number --
    and since aggregation matches already-imported files by that exact
    literal function string, the shift silently reattributes one list's
    real, already-submitted committee members to a DIFFERENT list (see
    2026-07-30 field report). So: once assigned, an entity's slot_index
    (persisted on the Entity itself -- see its docstring) is never
    touched again. New/never-before-seen entities are assigned the next
    free numbers, in (level, submission_order, entity_id) order among
    themselves only -- that ordering only ever applies to entities that
    haven't been slotted yet, never to reshuffle existing ones.

    Mutates `slot_index` in place on newly-assigned entities (they're
    the actual objects living in `registry.entities`, not copies) --
    callers that go on to generate real files/aggregate real data from
    this result MUST persist the registry afterward (`state.save_election()`)
    so the assignment sticks for next time.
    """
    all_entities = registry.entities
    seen_ids: set[str] = set()
    unique: list[Entity] = []

    for entity in all_entities:
        root = canonical_entity(entity, all_entities)
        if root.entity_id not in seen_ids:
            seen_ids.add(root.entity_id)
            unique.append(root)

    assigned = [e for e in unique if e.slot_index > 0]
    unassigned = [e for e in unique if e.slot_index <= 0]

    unassigned.sort(key=lambda e: (
        LEVEL_PRIORITY.get(e.level, 99),
        e.submission_order,
        e.entity_id,
    ))
    next_slot = max((e.slot_index for e in assigned), default=0) + 1
    for e in unassigned:
        e.slot_index = next_slot
        next_slot += 1

    ordered = sorted(assigned + unassigned, key=lambda e: e.slot_index)
    return [
        CanonicalSlot(
            slot_index=ent.slot_index,
            entity=ent,
            name=canonical_entity_name(ent, all_entities),
        )
        for ent in ordered
    ]


# ── Allocation builder ────────────────────────────────────────────────


def build_prosireni_allocation(
    registry: CandidaciesRegistry,
    bm_numbers: list[int],
) -> list[Allocation]:
    """Compute the prosireni allocation grid from the candidacies registry.

    Each canonical entity × BM pair generates two Allocation entries:
      function="Члан [N]"          party=<canonical entity_id>
      function="Заменик клана [N]" party=<canonical entity_id>

    `party` holds the entity's short `entity_id`, not its display name —
    matching how stalni's `party` field always holds the abbreviation
    (e.g. "СНС"), never the full legal party name. `Allocation.party` /
    `Person.party` feed filenames, the hidden Phase-1↔Phase-2 identity
    marker, and the master workbook's own party column — all operational
    matching keys, not places a human reads prose. A full legal-entity
    name can be long enough to blow past Windows path-length limits and
    Thunderbird's search/subject handling; the short id doesn't have that
    problem. Display contexts (decision-document proposal text, the
    generated file's own title) resolve the id back to the full name via
    `ElectionConfig.party_full_name()` / `canonical_entity_name()`.

    Output is sorted by (slot_index, bm_number, role) — natural reading
    order for the master workbook and popunjeni files.

    When the registry is empty (no entities yet), returns an empty list so
    the caller (Phase 1 GUI) can detect and prompt the operator to fill in
    candidacies first.
    """
    slots = canonical_slots(registry)
    allocations: list[Allocation] = []
    for cs in slots:
        for bm in sorted(bm_numbers):
            allocations.append(Allocation(
                bm_number=bm,
                function=slot_function(MEMBER_LABEL, cs.slot_index),
                party=cs.entity.entity_id,
            ))
            allocations.append(Allocation(
                bm_number=bm,
                function=slot_function(SUBSTITUTE_LABEL, cs.slot_index),
                party=cs.entity.entity_id,
            ))
    return allocations
