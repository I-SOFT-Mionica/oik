"""Workflow specification — bench mark for the prošireni-sastav generalization.

Two committee workflows live in this codebase:

  * **Стални састав** (stalni) — the existing, mature workflow. Fixed
    list of 6 roles per BM, party-curated list as the entity source,
    every slot must be filled (načelnik backfill if not), one
    candidacy decision per cycle.
  * **Проширени састав** (prosireni) — the upcoming workflow. 2
    roles per BM × entity, RIK/PIK/OIK candidacy registry as the
    entity source, empty slots are legitimate (parties can choose not
    to participate at a given BM), entities ranked by
    (highest-linked-level priority, submission order at that level).

Most of the per-phase logic is **identical** between the two; the
differences are concentrated here in `WorkflowSpec`. Phase functions
(generate / aggregate / generate_documents) will take a `spec`
parameter in Phase D and read the workflow-specific bits from it,
leaving the stalni default registered so existing callers and 466
existing tests stay untouched until then.

This module is A4-skeleton-only:
  * dataclasses defined,
  * two specs registered (STALNI_SPEC, PROSIRENI_SPEC),
  * `spec_by_slug` lookup helper.

No phase function consumes the spec yet — that's Phase D.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Role schema ───────────────────────────────────────────────────


@dataclass(frozen=True)
class RoleDef:
    """One role slot inside a BM × entity grouping.

    `key` is the stable internal identifier (used in dicts, audit log
    events, .docx template substitutions). `label_sr` is what the
    operator sees in tables / dialogs. `is_substitute` marks "Заменик"
    pairings so UI code can render them indented or in a paired group.
    """

    key: str
    label_sr: str
    is_substitute: bool


# Stalni's 6-role schema — matches `core.models.FUNCTIONS` exactly.
# Kept in this file (instead of imported) so the spec module stays
# importable without pulling in `core.models` at workflow-spec import
# time; phase functions that already read `FUNCTIONS` keep doing so.
_STALNI_ROLES: tuple[RoleDef, ...] = (
    RoleDef("predsednik",            "Председник",          False),
    RoleDef("zamenik_predsednika",   "Заменик председника", True),
    RoleDef("clan_1",                "Члан 1",              False),
    RoleDef("zamenik_clana_1",       "Заменик члана 1",     True),
    RoleDef("clan_2",                "Члан 2",              False),
    RoleDef("zamenik_clana_2",       "Заменик члана 2",     True),
)

# Prosireni's 2-role schema — each canonical entity contributes one
# Member + one Substitute per BM where it submits a candidacy.
_PROSIRENI_ROLES: tuple[RoleDef, ...] = (
    RoleDef("clan",          "Члан",          False),
    RoleDef("zamenik_clana", "Заменик члана", True),
)


# ── Path namespace ────────────────────────────────────────────────


@dataclass(frozen=True)
class PathSpec:
    """Subdirectory + filename pieces under `BIRACKI_ODBOR_HOME` per workflow.

    These are bare path segments — `app_paths` will combine them with
    `home()` in Phase D. Kept as strings (not Path objects) because
    they're configuration, not pre-resolved filesystem locations.
    """

    stranke_subdir: str         # "stranka_fajlovi" / "stranka_fajlovi_prosireni"
    popunjeni_subdir: str       # "popunjeni" / "popunjeni_prosireni"
    popunjeni_odbijeno_subdir: str  # "popunjeni_odbijeno" / "popunjeni_odbijeno_prosireni"
    master_subdir: str          # "master" / "master_prosireni"
    master_filename: str        # "zbirana_tabela.xlsx" / "zbirana_tabela_prosireni.xlsx"
    resenja_subdir: str         # "resenja" / "resenja_prosireni"
    audit_subdir: str           # "audit" / "audit_prosireni"


_STALNI_PATHS = PathSpec(
    stranke_subdir="stranka_fajlovi",
    popunjeni_subdir="popunjeni",
    popunjeni_odbijeno_subdir="popunjeni_odbijeno",
    master_subdir="master",
    master_filename="zbirana_tabela.xlsx",
    resenja_subdir="resenja",
    audit_subdir="audit",
)


_PROSIRENI_PATHS = PathSpec(
    stranke_subdir="stranka_fajlovi_prosireni",
    popunjeni_subdir="popunjeni_prosireni",
    popunjeni_odbijeno_subdir="popunjeni_odbijeno_prosireni",
    master_subdir="master_prosireni",
    master_filename="zbirana_tabela_prosireni.xlsx",
    resenja_subdir="resenja_prosireni",
    audit_subdir="audit_prosireni",
)


# ── WorkflowSpec ──────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkflowSpec:
    """The complete per-workflow configuration.

    Fields fall into four groups:

      Identity:
        `slug` — internal identifier ("stalni" / "prosireni").
        `name_sr` — operator-facing Cyrillic name.

      Shape:
        `roles` — RoleDef list driving Phase 1 file shape + master
          schema + Phase 3 enumeration.
        `paths` — where this workflow's files live under HOME.
        `entity_source` — "party_full_names" reads from the curated
          parties table (stalni); "candidacies" reads from the new
          A3-introduced registry (prosireni).
        `entity_slot_ordering` — "by_party_abbrev" uses the party's
          string key directly (stalni); "by_highest_level_priority"
          runs the B3 canonical-entity ranking algorithm (prosireni).
        `canonical_name_strategy` — "abbrev_only" uses
          `party_full_names[abbrev]` for «Предложио» (stalni);
          "highest_level_wins" runs the B3 cross-level name
          resolution (prosireni).

      Domain rules:
        `require_all_slots_filled` — Phase 3 blocks generation if any
          slot is empty (stalni). False for prosireni (empty slots OK).
        `enforce_one_team_per_bm` — At aggregate time, drop duplicate
          entities-on-multiple-levels for the same BM, keeping only
          the highest-level entry (prosireni). False for stalni.

      Resenja text:
        `resenja_title_subtitle` — line under «Р Е Ш Е Њ Е».
        `resenja_composition_mark` — "- У СТАЛНОМ САСТАВУ -"
          / "- У ПРОШИРЕНОМ САСТАВУ -".
        `resenja_item_i_intro` — locative-case composition phrase
          ("сталном саставу" / "проширеном саставу") substituted into
          Item I's "У бирачки одбор у {...} за координирано
          спровођење ..." sentence in phase3_docx._build_document().
        `resenja_legal_basis_key` — `DocumentInfo` attribute holding
          the workflow's legal-basis text (so stalni and prosireni
          can carry independent boilerplate that the operator can
          edit on Phase 3).
        `obrazlozenje_filename` — bare filename under HOME;
          `obrazlozenje.json` for stalni, `obrazlozenje_prosireni.json`
          for prosireni.

      Numbering / mail:
        `subbroj_field` — `ElectionDates` attribute holding the
          starting sub-broj for this workflow.
        `subject_token_kind` — "stalni" produces `[ОИК-YYYYMMDD]`,
          "prosireni" produces `[ОИК-PROSIRENI-YYYYMMDD]` so Phase 2
          inbox filter doesn't mix returns from the two workflows.
    """

    # Identity.
    slug: str
    name_sr: str

    # Shape.
    roles: tuple[RoleDef, ...]
    paths: PathSpec
    entity_source: str
    entity_slot_ordering: str
    canonical_name_strategy: str

    # Domain rules.
    require_all_slots_filled: bool
    enforce_one_team_per_bm: bool

    # Resenja text.
    resenja_title_subtitle: str
    resenja_composition_mark: str
    resenja_item_i_intro: str
    resenja_legal_basis_key: str
    obrazlozenje_filename: str

    # Numbering / mail.
    subbroj_field: str
    number_prefix_field: str   # DocumentInfo attribute for this workflow's prefix
    session_date_field: str    # ElectionDates attribute for this workflow's session date
    session_number_field: str  # ElectionDates attribute for this workflow's session number
    subject_token_kind: str


# ── Registered specs ──────────────────────────────────────────────


STALNI_SPEC = WorkflowSpec(
    slug="stalni",
    name_sr="Стални састав",
    roles=_STALNI_ROLES,
    paths=_STALNI_PATHS,
    entity_source="party_full_names",
    entity_slot_ordering="by_party_abbrev",
    canonical_name_strategy="abbrev_only",
    require_all_slots_filled=True,
    enforce_one_team_per_bm=False,
    resenja_title_subtitle=(
        "О ИМЕНОВАЊУ ПРЕДСЕДНИКА И ЧЛАНОВА БИРАЧКОГ ОДБОРА"
        " И ЊИХОВИХ ЗАМЕНИКА"
    ),
    resenja_composition_mark="- У СТАЛНОМ САСТАВУ -",
    resenja_item_i_intro="сталном саставу",
    resenja_legal_basis_key="legal_basis",
    obrazlozenje_filename="obrazlozenje.json",
    subbroj_field="subbroj_start",
    number_prefix_field="number_prefix",
    session_date_field="session_date",
    session_number_field="session_number",
    subject_token_kind="stalni",
)


PROSIRENI_SPEC = WorkflowSpec(
    slug="prosireni",
    name_sr="Проширени састав",
    roles=_PROSIRENI_ROLES,
    paths=_PROSIRENI_PATHS,
    entity_source="candidacies",
    entity_slot_ordering="by_highest_level_priority",
    canonical_name_strategy="highest_level_wins",
    require_all_slots_filled=False,
    enforce_one_team_per_bm=True,
    resenja_title_subtitle="О ИМЕНОВАЊУ ЧЛАНОВА И ЊИХОВИХ ЗАМЕНИКА",
    resenja_composition_mark="- У ПРОШИРЕНОМ САСТАВУ -",
    resenja_item_i_intro="проширеном саставу",
    resenja_legal_basis_key="legal_basis_prosireni",
    obrazlozenje_filename="obrazlozenje_prosireni.json",
    subbroj_field="subbroj_start_prosireni",
    number_prefix_field="number_prefix_prosireni",
    session_date_field="session_date_prosireni",
    session_number_field="session_number_prosireni",
    subject_token_kind="prosireni",
)


# ── Registry / lookup ────────────────────────────────────────────


_REGISTRY: dict[str, WorkflowSpec] = {
    s.slug: s for s in (STALNI_SPEC, PROSIRENI_SPEC)
}


def all_specs() -> tuple[WorkflowSpec, ...]:
    """Every registered spec in stable order (stalni first)."""
    return tuple(_REGISTRY.values())


def spec_by_slug(slug: str) -> WorkflowSpec:
    """Look up the workflow spec by its `slug` ("stalni" / "prosireni").

    Raises `KeyError` with a helpful message on miss — callers
    routing on a user-controlled string should validate first; this
    helper is for code paths where the slug is internal.
    """
    try:
        return _REGISTRY[slug]
    except KeyError:
        raise KeyError(
            f"Unknown workflow slug {slug!r}; expected one of "
            f"{sorted(_REGISTRY.keys())}"
        ) from None


def bm_offset(oik, bm_number: int) -> int:
    """A BM's index in the OIK's sorted station list — what `format_broj`
    needs to reconstruct the sub-broj it was originally given, since
    Phase 3 assigns them in this same sorted order. Shared so any screen
    that needs to re-derive (not store) an already-issued decision's own
    broj uses the identical rule Phase 3 used to assign it."""
    sorted_bms = sorted(s.bm_number for s in oik.polling_stations)
    try:
        return sorted_bms.index(bm_number)
    except ValueError:
        return 0
