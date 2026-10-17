"""Candidacy registry — entities + candidates for the prošireni-sastav workflow.

Data model:

  * `Entity` — one record per (legal-entity × election-level). The same
    legal entity that runs on multiple levels (e.g. SNS on presidential
    + parliamentary + local) appears once per level. The operator
    manually links them across levels via `linked_to_entity_id` —
    automatic detection isn't possible (50%-shared-members threshold is
    out of OIK's knowledge scope per the design discussion).
  * `Candidate` — one record per person standing for office. Their JMBG
    is the cross-check key: a candidate cannot also serve on the
    бирачки одбор (enforced at master-import time in Phase B1).
  * `CandidaciesRegistry` — container; lives on `ElectionConfig`.

Level vocabulary follows `declension.TYPE_KEYS`:
  presidential / parliamentary / provincial / local.

Slot ordering precedence (highest wins for canonical-name + sort):
  presidential (1) > parliamentary (2) > provincial (3) > local (4).
The slot index that lands in the resenja docs is the entity's
1-based position in the canonical-entities list sorted by
(highest_linked_level_priority, submission_order_at_that_level). The
algorithm itself lives in B3; this module just stores the inputs.

This module is pure data — no I/O, no GUI, no openpyxl. Excel I/O
lives in `core/template.py` next to the existing parties helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Vocabulary ────────────────────────────────────────────────────


# Mirrors `declension.TYPE_KEYS` so callers stay consistent across
# config files. Kept duplicated here (not imported) to avoid a
# top-level dependency on declension from the data model.
LEVEL_KEYS: tuple[str, ...] = (
    "presidential", "parliamentary", "provincial", "local",
)

# Lower numbers = higher precedence. Used by B3 canonical-entity
# resolution: when the same legal entity is on multiple levels, the
# canonical name comes from the level with the smallest priority.
LEVEL_PRIORITY: dict[str, int] = {
    "presidential":  1,
    "parliamentary": 2,
    "provincial":    3,
    "local":         4,
}

# The three entity-type values the operator can pick from. "Party" =
# registered political party; "coalition" = legally distinct coalition
# entity formed for this cycle; "group_of_citizens" = група грађана
# endorsing an independent candidacy.
# NOTE: "movement" (Политички покрет) was removed — it is not a
# legally recognised submitter form under current Serbian election law.
ENTITY_TYPES: tuple[str, ...] = (
    "party", "coalition", "group_of_citizens",
)


def _coerce_str(v: object) -> str:
    """Identical helper to `election.coerce_str` but kept local so this
    module doesn't depend on `election`. Returns "" for None / non-str."""
    return v.strip() if isinstance(v, str) else ""


def _coerce_int(v: object, default: int = 0) -> int:
    """Coerce numeric strings or ints; everything else → `default`."""
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            try:
                return int(s)
            except ValueError:
                return default
    return default


# ── Entity ────────────────────────────────────────────────────────


@dataclass
class Entity:
    """One legal entity at one election level.

    `entity_id` is an operator-assigned slug, unique within the cycle.
    Convention: `<short-name>-<level>` (e.g. `sns-presidential`,
    `sns-parliamentary`); the slug itself doesn't carry meaning, it's
    just the FK target for candidates + cross-level links.

    `linked_to_entity_id` points to the canonical entity when the same
    legal entity runs on multiple levels. Per the plan, the
    canonical entity is the one with the highest level — operators
    choose one as the "leader" and link lower-level records to it.
    Empty string = this is a standalone entity (no link).

    `slot_index` — the entity's permanent prosireni slot number (1-based),
    once assigned. 0 = not yet assigned. Assigned once by
    `prosireni_allocation.canonical_slots()` on first read and never
    reassigned afterward, even as later-registering entities would
    otherwise change the sort order — see that function's docstring
    for why this must be stable rather than recomputed from a sort key
    every time.

    `email`/`phone` — this list's own contact info, used by Phase 1's
    "Send" flow to draft it the completed-list request. Deliberately a
    separate address book from `ElectionConfig.party_contacts` (the
    стални RIK-party contacts) rather than sharing it: a прошиени
    entity_id (e.g. "moja-lista-local") and a RIK party abbreviation
    (e.g. "СНС") are different identity systems that can coincidentally
    collide, and a стални party's saved email must never be reused to
    contact a прошиени list, or vice versa, by accident.
    """

    entity_id: str
    name: str
    entity_type: str  # one of ENTITY_TYPES
    level: str        # one of LEVEL_KEYS
    submission_order: int  # 1-based ballot position at this level
    linked_to_entity_id: str = ""
    slot_index: int = 0
    email: str = ""
    phone: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "level": self.level,
            "submission_order": self.submission_order,
            "linked_to_entity_id": self.linked_to_entity_id,
            "slot_index": self.slot_index,
            "email": self.email,
            "phone": self.phone,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entity":
        return cls(
            entity_id=_coerce_str(d.get("entity_id")),
            name=_coerce_str(d.get("name")),
            entity_type=_coerce_str(d.get("entity_type")),
            level=_coerce_str(d.get("level")),
            submission_order=_coerce_int(d.get("submission_order")),
            linked_to_entity_id=_coerce_str(d.get("linked_to_entity_id")),
            slot_index=_coerce_int(d.get("slot_index")),
            email=_coerce_str(d.get("email")),
            phone=_coerce_str(d.get("phone")),
        )


# ── Candidate ─────────────────────────────────────────────────────


@dataclass
class Candidate:
    """One person standing for office.

    JMBG is the cross-check key: phase B1 rejects any committee-member
    JMBG that matches one of these. Stored as a 13-digit string so the
    leading-zero "Yu-format" representation survives round-trips
    (numeric storage would strip it).

    `endorsed_by_entity_id` is the FK to `Entity.entity_id` — and via
    the entity's level + cross-link the operator can answer "which
    candidacies must we cross-check across the four levels?".
    """

    name: str
    jmbg: str
    endorsed_by_entity_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "jmbg": self.jmbg,
            "endorsed_by_entity_id": self.endorsed_by_entity_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candidate":
        return cls(
            name=_coerce_str(d.get("name")),
            jmbg=_coerce_str(d.get("jmbg")),
            endorsed_by_entity_id=_coerce_str(d.get("endorsed_by_entity_id")),
        )


# ── Registry ──────────────────────────────────────────────────────


@dataclass
class CandidaciesRegistry:
    """Holds every entity + candidate for the current election cycle.

    Wholly empty by default — fresh installs and elections where the
    operator hasn't started building the registry yet should serialize
    to `{"entities": [], "candidates": []}` without surprising existing
    election_config.json files that predate this field.

    Membership lookup helpers live here so callers don't reinvent them:
      `entity_by_id`, `candidates_for_entity`, `jmbg_index` (a set of
      every candidate JMBG, used by Phase B1's cross-check).
    """

    entities: list[Entity] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "candidates": [c.to_dict() for c in self.candidates],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CandidaciesRegistry":
        if not isinstance(d, dict):
            return cls()
        raw_entities = d.get("entities") or []
        raw_candidates = d.get("candidates") or []
        return cls(
            entities=[
                Entity.from_dict(x) for x in raw_entities
                if isinstance(x, dict)
            ],
            candidates=[
                Candidate.from_dict(x) for x in raw_candidates
                if isinstance(x, dict)
            ],
        )

    # ── Lookups ──────────────────────────────────────────────

    def entity_by_id(self, entity_id: str) -> Entity | None:
        """Return the entity with the given id, or None."""
        for e in self.entities:
            if e.entity_id == entity_id:
                return e
        return None

    def candidates_for_entity(self, entity_id: str) -> list[Candidate]:
        """Every candidate endorsed by `entity_id`. Order preserved."""
        return [c for c in self.candidates if c.endorsed_by_entity_id == entity_id]

    def jmbg_index(self) -> set[str]:
        """Set of every candidate's JMBG. Used by Phase B1 to reject
        committee members who are also running for office."""
        return {c.jmbg.strip() for c in self.candidates if c.jmbg.strip()}


# ── B3 — canonical-name resolution ────────────────────────────────


def _link_group(entity: Entity, all_entities: list[Entity]) -> list[Entity]:
    """Return all entities in `entity`'s link group, sorted highest-level first.

    A link group is the connected component containing `entity` when
    `linked_to_entity_id` edges are treated as undirected (both directions
    are followed). This is cycle-safe — a cycle that spans two entities
    yields a group containing both, and the entity at the highest election
    level sorts first.

    Dangling links (target missing): the walk stops at the missing edge;
    only reachable entities are included.
    """
    by_id = {e.entity_id: e for e in all_entities}

    # Forward pass: follow linked_to_entity_id from entity outwards.
    reachable: set[str] = set()
    stack: list[Entity] = [entity]
    while stack:
        cur = stack.pop()
        if cur.entity_id in reachable:
            continue
        reachable.add(cur.entity_id)
        if cur.linked_to_entity_id:
            nxt = by_id.get(cur.linked_to_entity_id)
            if nxt:
                stack.append(nxt)

    # Backward pass: entities that link INTO any already-reachable entity.
    changed = True
    while changed:
        changed = False
        for e in all_entities:
            if e.entity_id not in reachable and e.linked_to_entity_id in reachable:
                reachable.add(e.entity_id)
                changed = True

    group = [e for e in all_entities if e.entity_id in reachable]
    group.sort(key=lambda e: (
        LEVEL_PRIORITY.get(e.level, 99),
        e.submission_order,
        e.entity_id,
    ))
    return group


def canonical_entity_name(
    entity: Entity, all_entities: list[Entity],
) -> str:
    """Resolve an entity's canonical name via the "highest-level wins" rule.

    Collects the full link group (connected component) containing `entity`,
    then returns the name of the entity with the smallest LEVEL_PRIORITY
    value (i.e. the highest election level: Presidential > Parliamentary >
    Provincial > Local). Ties broken by submission_order then entity_id.

    Behavior with no link:
      Returns `entity.name` unchanged — standalone entities are their own
      canonical.

    Behavior with a circular link (operator misconfiguration):
      Both directions are followed; the cycle is collected safely and the
      highest-level entity in the cycle wins.

    Behavior with a dangling `linked_to_entity_id` (target missing):
      Returns `entity.name` — defensive against half-edited registries.

    Phase E uses this when filling the «Предложио:» column in the
    prošireni-sastav решења; Phase 1 + Phase 2 also call it when
    enforcing the one-team-per-BM dedup at aggregate time.
    """
    group = _link_group(entity, all_entities)
    return group[0].name if group else entity.name


def canonical_entity(
    entity: Entity, all_entities: list[Entity],
) -> Entity:
    """Same resolution as `canonical_entity_name` but returns the Entity object.

    Used by prosireni_allocation to determine the canonical entity for
    slot ordering — the name alone is insufficient because we also need
    the level and submission_order for the sort key.
    """
    group = _link_group(entity, all_entities)
    return group[0] if group else entity
