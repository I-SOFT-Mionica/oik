"""Per-election configuration.

Lives in `election_config.json` in the install directory. Contains the
election dates and types, document numbering, legal basis paragraph,
and the map of party abbreviation → full Cyrillic name used in решења.
Changes every election cycle.

Some fields that used to be typed explicitly are now derived by the program
(see `biracki_odbor.config.declension`):
  - date_genitive is computed from date_full (month name declension)
  - year is parsed out of date_full
  - types_upper is uppercase of the expanded type strings
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from biracki_odbor.config import candidacies as candidacies_mod, declension
from biracki_odbor.config.schema import coerce_str
from biracki_odbor.core.models import PartyQuota


@dataclass
class ElectionDates:
    date_full: str = ""        # "17. децембар 2023. године"
    session_date: str = ""     # "6. децембра 2023. године" — set in Phase 3 (стални)
    session_number: str = ""   # "5" — OIK session number; set in Phase 3 (стални)
    # Проширені решења are adopted at a separate OIK session — independent
    # date and ordinal number. Empty = use стални values as a convenience
    # default until the operator fills them in Phase 3 (проширені tab).
    session_date_prosireni: str = ""
    session_number_prosireni: str = ""
    # Phase 3 broj-resenja building blocks. Each BM's resenja Број is
    # constructed as `{prefix}{separator}{start + bm_offset}/{year}`:
    #   - `prefix` from DocumentInfo.number_prefix (e.g. "013-5-30")
    #   - `separator` ("-" or "/" — operator picks; OIK convention
    #     varies by municipality)
    #   - `start` is the operator-entered starting sub-broj. The
    #     municipal archive issues a single base number per election
    #     cycle and every document OIK writes claims one sub-broj
    #     sequentially; by the time the stalni-sastav resenja get
    #     produced the start is usually a few hundred in. Stored as
    #     a string so leading-zero formats (rare but legal) survive.
    #   - `bm_offset` is the index of the BM in the OIK's order
    #     (first BM → 0, second → 1, …) — Phase 3 computes it from
    #     the polling-stations list.
    # Empty strings keep the legacy `{prefix}-{bm}/{year}` rendering.
    subbroj_start: str = ""
    subbroj_separator: str = "-"
    # Parallel starting sub-broj for the prošireni-sastav workflow.
    # Municipal archive issues sub-broj sequentially across ALL OIK
    # documents — so the prosireni resenja typically continue from
    # wherever the stalni resenja left off (e.g. stalni used 200..249,
    # prosireni starts at 250). Independent field because the two
    # workflows generate separately and at different times within the
    # cycle. Empty string ⇒ falls back to legacy `{prefix}-{bm}/{year}`
    # format same way `subbroj_start` does for stalni. The separator is
    # SHARED between workflows since municipal-archive convention is
    # uniform within an OIK.
    subbroj_start_prosireni: str = ""
    # Nomination / registration cutoff dates (ISO, "YYYY-MM-DD"). Empty = not
    # yet set — UI auto-calculates from election date on first load.
    # Party submission deadlines — operator-editable; auto-calculated from
    # election_date as a starting point on first load. The law changes between
    # cycles, and стані / проширені have independent legislative calendars.
    cutoff_stalni: str = ""      # party submission deadline (стані), approx. election_date − 15 days
    cutoff_prosireni: str = ""   # party submission deadline (проширені), own calendar
    cutoff_posmatraci: str = ""  # observer accreditation deadline, approx. election_date − 2 days
    # OIK publication deadlines — when the final commission composition must be
    # published. Informational only; shown as a reminder in Phase 3, never a gate.
    cutoff_resenja_stalni: str = ""    # approx. election_date − 10 days
    cutoff_resenja_prosireni: str = "" # проширені has its own publication deadline

    @property
    def date_genitive(self) -> str:
        return declension.to_genitive(self.date_full)

    @property
    def year(self) -> str:
        return declension.year_from(self.date_full)

    @property
    def subject_token(self) -> str:
        """Subject-line identifier embedded in Phase 1 outgoing mail.

        Format: `[ОИК-YYYYMMDD]` based on the election date. Same
        token for every party in a given election, so Phase 2's
        Outlook fetch can filter the inbox with one `ci_phrasematch`
        clause instead of walking every .xlsx attachment in the
        last 14 days.

        Returns an empty string when the election date is empty or
        unparseable — callers MUST handle that as "no rider, fall
        back to date-only filter" rather than crashing or building
        a token that matches nothing. This is also what makes the
        helper safe to call unconditionally from the send dialog
        (worst case: no token, same behavior as before this feature).
        """
        parsed = declension.parse_serbian_date(self.date_full)
        if parsed is None:
            return ""
        y, m, d = parsed
        return f"[ОИК-{y:04d}{m:02d}{d:02d}]"

    def subject_token_for(self, kind: str) -> str:
        """Workflow-aware subject token.

        kind="stalni"    → ``[ОИК-YYYYMMDD]``
        kind="prosireni" → ``[ОИК-PROSIRENI-YYYYMMDD]``

        Returns "" when the election date is empty/unparseable — same
        contract as `subject_token`.
        """
        parsed = declension.parse_serbian_date(self.date_full)
        if parsed is None:
            return ""
        y, m, d = parsed
        if kind == "prosireni":
            return f"[ОИК-PROSIRENI-{y:04d}{m:02d}{d:02d}]"
        return f"[ОИК-{y:04d}{m:02d}{d:02d}]"

    def to_dict(self) -> dict[str, str]:
        return {
            "date_full": self.date_full,
            "session_date": self.session_date,
            "session_number": self.session_number,
            "session_date_prosireni": self.session_date_prosireni,
            "session_number_prosireni": self.session_number_prosireni,
            "subbroj_start": self.subbroj_start,
            "subbroj_separator": self.subbroj_separator,
            "subbroj_start_prosireni": self.subbroj_start_prosireni,
            "cutoff_stalni": self.cutoff_stalni,
            "cutoff_prosireni": self.cutoff_prosireni,
            "cutoff_posmatraci": self.cutoff_posmatraci,
            "cutoff_resenja_stalni": self.cutoff_resenja_stalni,
            "cutoff_resenja_prosireni": self.cutoff_resenja_prosireni,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ElectionDates":
        return cls(
            date_full=coerce_str(d.get("date_full")),
            session_date=coerce_str(d.get("session_date")),
            session_number=coerce_str(d.get("session_number")),
            session_date_prosireni=coerce_str(d.get("session_date_prosireni")),
            session_number_prosireni=coerce_str(d.get("session_number_prosireni")),
            subbroj_start=coerce_str(d.get("subbroj_start")),
            # Default "-" if older configs lack the field; matches
            # the most common municipal-archive convention.
            subbroj_separator=coerce_str(d.get("subbroj_separator")) or "-",
            subbroj_start_prosireni=coerce_str(
                d.get("subbroj_start_prosireni")
            ),
            cutoff_stalni=coerce_str(d.get("cutoff_stalni")),
            cutoff_prosireni=coerce_str(d.get("cutoff_prosireni")),
            cutoff_posmatraci=coerce_str(d.get("cutoff_posmatraci")),
            cutoff_resenja_stalni=coerce_str(d.get("cutoff_resenja_stalni")),
            cutoff_resenja_prosireni=coerce_str(d.get("cutoff_resenja_prosireni")),
        )


@dataclass
class ElectionInfo:
    dates: ElectionDates = field(default_factory=ElectionDates)
    # Canonical type keys: 'presidential' / 'parliamentary' / 'provincial' / 'local'.
    # Legacy full-text entries are accepted on load and migrated when possible;
    # unknown strings are kept as-is so user-customised configs survive.
    types: list[str] = field(default_factory=list)
    rik_decision: str = ""  # full composed text — used by Phase 3 / obrazlozenje
    rik_broj: str = ""      # decision reference, e.g. "02 број 013-376/23"
    rik_date: str = ""      # decision date ISO "YYYY-MM-DD"

    def expanded_types(
        self, municipality_name: str, local_assembly: str = "",
    ) -> list[tuple[str, str]]:
        """(lowercase, UPPERCASE) tuples for use in решења headers/body."""
        return declension.expand_types(self.types, municipality_name, local_assembly)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.dates.to_dict(),
            "types": list(self.types),
            "rik_decision": self.rik_decision,
            "rik_broj": self.rik_broj,
            "rik_date": self.rik_date,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ElectionInfo":
        raw_types = [coerce_str(x) for x in (d.get("types") or [])]
        normalised: list[str] = []
        for t in raw_types:
            if t in declension.TYPE_KEYS:
                normalised.append(t)
                continue
            key = declension.detect_key(t)
            normalised.append(key if key is not None else t)
        return cls(
            dates=ElectionDates.from_dict(d),
            types=normalised,
            rik_decision=coerce_str(d.get("rik_decision")),
            rik_broj=coerce_str(d.get("rik_broj")),
            rik_date=coerce_str(d.get("rik_date")),
        )


@dataclass
class DocumentInfo:
    number_prefix: str = ""
    # Separate document number prefix for the проширени workflow.
    # The municipal archive assigns document numbers sequentially within one
    # OIK category; стані and проширені decisions often fall under different
    # archive categories, so they carry different prefixes.
    number_prefix_prosireni: str = ""
    legal_basis: str = ""
    # Separate legal-basis text for the prošireni-sastav workflow.
    # Стални and проширени cite different statutory articles and are
    # generated at different times, so each workflow keeps its own text.
    legal_basis_prosireni: str = ""
    # Delegated-signer authorization — ONE shared setting used by every
    # resenje type (Phase 3 original appointment, Престанак, Измене), not
    # per-document-type: legally, a chairman delegates signing authority
    # for a period, and everything issued in that period is signed by the
    # delegate, not just amendments. Originally izmena-only (field names
    # below carried that prefix) — from_dict() falls back to the old
    # izmena_*-prefixed keys so an already-saved election.json with real
    # delegation data doesn't silently reset to blank.
    use_authorization: bool = True
    authorization_number: str = ""   # e.g. "013-5-32/2023-01"
    authorization_date: str = ""     # e.g. "6. децембра 2023. године"
    authorized_name: str = ""        # e.g. "Ивана Тешић"
    authorized_role: str = ""        # e.g. "заменик председника"
    izmena_legal_basis_stalni: str = ""
    izmena_legal_basis_prosireni: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentInfo":
        return cls(
            number_prefix=coerce_str(d.get("number_prefix")),
            number_prefix_prosireni=coerce_str(d.get("number_prefix_prosireni")),
            legal_basis=coerce_str(d.get("legal_basis")),
            legal_basis_prosireni=coerce_str(d.get("legal_basis_prosireni")),
            use_authorization=bool(
                d.get("use_authorization", d.get("izmena_use_authorization", True))
            ),
            authorization_number=coerce_str(
                d.get("authorization_number") or d.get("izmena_authorization_number")
            ),
            authorization_date=coerce_str(
                d.get("authorization_date") or d.get("izmena_authorization_date")
            ),
            authorized_name=coerce_str(
                d.get("authorized_name") or d.get("izmena_authorized_name")
            ),
            authorized_role=coerce_str(
                d.get("authorized_role") or d.get("izmena_authorized_role")
            ),
            izmena_legal_basis_stalni=coerce_str(d.get("izmena_legal_basis_stalni")),
            izmena_legal_basis_prosireni=coerce_str(d.get("izmena_legal_basis_prosireni")),
        )


@dataclass
class PartyContact:
    """Email + phone for one party.

    Stored parallel to `party_full_names` (which stays a plain
    `dict[str, str]` so the existing decision points in phase3_docx
    and elsewhere don't need to change). The new info is consumed by
    the upcoming Outlook auto-send feature — Phase 1 generates files
    per party, then sends one draft per party to the email here with
    the matching .xlsx attached.
    """

    email: str = ""
    phone: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"email": self.email, "phone": self.phone}

    @classmethod
    def from_dict(cls, d: Any) -> "PartyContact":
        if not isinstance(d, dict):
            return cls()
        return cls(
            email=coerce_str(d.get("email")),
            phone=coerce_str(d.get("phone")),
        )

    @property
    def is_empty(self) -> bool:
        return not (self.email.strip() or self.phone.strip())


@dataclass
class RikPerson:
    name: str = ""
    jmbg: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> "RikPerson":
        if not isinstance(d, dict):
            return cls()
        return cls(
            name=coerce_str(d.get("name")),
            jmbg=coerce_str(d.get("jmbg")),
            address=coerce_str(d.get("address")),
            phone=coerce_str(d.get("phone")),
            email=coerce_str(d.get("email")),
        )

    @property
    def is_empty(self) -> bool:
        return not self.name.strip()


@dataclass
class RikBmEntry:
    member: RikPerson = field(default_factory=RikPerson)
    deputy: RikPerson = field(default_factory=RikPerson)

    def to_dict(self) -> dict[str, Any]:
        return {"member": self.member.to_dict(), "deputy": self.deputy.to_dict()}

    @classmethod
    def from_dict(cls, d: Any) -> "RikBmEntry":
        if not isinstance(d, dict):
            return cls()
        return cls(
            member=RikPerson.from_dict(d.get("member") or {}),
            deputy=RikPerson.from_dict(d.get("deputy") or {}),
        )


@dataclass
class RikProvision:
    active: bool = False
    members: dict[int, RikBmEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "members": {str(k): v.to_dict() for k, v in self.members.items()},
        }

    @classmethod
    def from_dict(cls, d: Any) -> "RikProvision":
        if not isinstance(d, dict):
            return cls()
        raw = d.get("members") or {}
        members: dict[int, RikBmEntry] = {}
        for k, v in raw.items():
            try:
                members[int(k)] = RikBmEntry.from_dict(v)
            except (ValueError, TypeError):
                pass
        return cls(active=bool(d.get("active", False)), members=members)


_TRANSITIONAL_ARTICLES: dict[str, str] = {
    "presidential": "члану 35. Закона о избору председника Републике",
    "parliamentary": "члану 179. Закона о избору народних посланика",
    "local": "члану 98. Закона о локалним изборима",
}


def rik_provision_articles(types: list[str]) -> str:
    """Return 'По члану X и члану Y' citation string for the given election types."""
    refs = [_TRANSITIONAL_ARTICLES[t] for t in types if t in _TRANSITIONAL_ARTICLES]
    if not refs:
        return ""
    return "По " + " и ".join(refs)


@dataclass
class ElectionConfig:
    election: ElectionInfo = field(default_factory=ElectionInfo)
    document: DocumentInfo = field(default_factory=DocumentInfo)
    # Real parliamentary groups only — never contains "_default". The
    # nacelnik (municipal chief) isn't a parliamentary group; its display
    # name lives in `OikConstants.nacelnik_full_name` — the chief doesn't
    # change between election cycles, so it's OIK identity data, not
    # election-cycle data (moved out of here so "New election cycle"
    # doesn't wipe it — see settings_election.py's _on_new_cycle).
    party_full_names: dict[str, str] = field(default_factory=dict)
    # Email + phone per party, keyed by the same abbreviation as
    # `party_full_names`. Optional — when empty, the Outlook
    # send-to-parties flow shows an inline editable email field so the
    # operator can still drive the send without permanently storing
    # the address. See [TODO.md §3, §4](TODO.md).
    party_contacts: dict[str, PartyContact] = field(default_factory=dict)
    # RIK-declared seat quota per party (Председник/Заменик/Чл.+Зам.чл.
    # counts), keyed by the same abbreviation as `party_full_names`
    # (never includes "_default" — nacelnik isn't a parliamentary group,
    # doesn't get a quota). Operator-entered from the RIK decision
    # document; used by the matrix builder grid to hard-block assigning
    # a party past its declared quota for a role. Empty by default —
    # absent quota entries simply aren't checked.
    party_quotas: dict[str, PartyQuota] = field(default_factory=dict)
    # Stable identifier for this election cycle. Stamped into every Phase 1
    # party file and used by Phase 2 import to refuse files from a different
    # cycle (e.g. leftover .xlsx from last year's vote). Lazily generated
    # on first save when absent.
    election_uuid: str = ""
    # Candidacy registry — entities (party / coalition /
    # group_of_citizens) per election level and the candidates each
    # endorses. Feeds the prošireni-sastav workflow (slot ordering,
    # canonical names) AND the cross-check that blocks committee
    # members who are also running for office. Empty by default; the
    # field is silently absent in pre-A3 election_config.json files
    # (from_dict treats missing as an empty registry).
    candidacies: "candidacies_mod.CandidaciesRegistry" = field(
        default_factory=lambda: candidacies_mod.CandidaciesRegistry()
    )
    rik_provision: RikProvision = field(default_factory=RikProvision)
    # Cosmetic only — Phase 1's "Име"/"Презиме" party-facing columns stay
    # two real columns (first_name/last_name are relied on separately
    # downstream: gender inference reads first_name specifically, decision
    # salutations need given-name-first order, decision documents source
    # from Person.first_name/last_name directly). This only groups the two
    # header cells under a shared "Име и презиме" label, requested by
    # parties who found two same-looking adjacent columns confusing to
    # fill in — no splitting/parsing logic anywhere else changes.
    combined_name_header: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "election": self.election.to_dict(),
            "document": self.document.to_dict(),
            "party_full_names": dict(self.party_full_names),
            "party_contacts": {
                k: c.to_dict() for k, c in self.party_contacts.items()
                if not c.is_empty
            },
            "party_quotas": {
                k: q.to_dict() for k, q in self.party_quotas.items()
            },
            "election_uuid": self.election_uuid,
            "candidacies": self.candidacies.to_dict(),
            "rik_provision": self.rik_provision.to_dict(),
            "combined_name_header": self.combined_name_header,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ElectionConfig":
        # One-time migration: "_default" used to live inside
        # party_full_names as an ordinary entry (and later, a plain
        # nacelnik_full_name field on this class). Pop it out so old
        # election_config.json files upgrade in place; the actual value
        # is pulled forward into OikConstants.nacelnik_full_name by
        # AppState's cross-file migration (see app_state.py), not here —
        # this class has no access to oik_constants.json's path.
        raw_parties = dict(d.get("party_full_names") or {})
        raw_parties.pop("_default", None)
        return cls(
            election=ElectionInfo.from_dict(d.get("election", {}) or {}),
            document=DocumentInfo.from_dict(d.get("document", {}) or {}),
            party_full_names={
                str(k): coerce_str(v) for k, v in raw_parties.items()
            },
            # Legacy configs (pre-§3) don't carry party_contacts; the
            # default empty dict is fine — Outlook send just shows the
            # email column blank for those parties so the operator can
            # fill it inline.
            party_contacts={
                str(k): PartyContact.from_dict(v)
                for k, v in (d.get("party_contacts") or {}).items()
            },
            # Absent in configs saved before this field existed — empty
            # dict means no quota is checked for any party.
            party_quotas={
                str(k): PartyQuota.from_dict(v)
                for k, v in (d.get("party_quotas") or {}).items()
            },
            election_uuid=coerce_str(d.get("election_uuid")),
            # Pre-A3 configs don't carry "candidacies"; the default
            # empty registry is fine — operator builds it via the
            # upcoming Кандидати UI when prošireni-sastav matters.
            candidacies=candidacies_mod.CandidaciesRegistry.from_dict(
                d.get("candidacies") or {}
            ),
            rik_provision=RikProvision.from_dict(d.get("rik_provision") or {}),
            # Absent in configs saved before this toggle existed —
            # default False keeps existing party files' layout unchanged.
            combined_name_header=bool(d.get("combined_name_header", False)),
        )

    def validate(self) -> list[str]:
        """Completeness check for the Election Settings tab's own Save button.

        Deliberately does NOT check `session_date`, `number_prefix`, or
        `legal_basis` — all three are only entered later, in Phase 3,
        once decisions are actually being drafted (the Election
        Settings tab doesn't even show fields for the latter two —
        see settings_election.py's _load_from_state comment). Requiring
        them here made it impossible to ever save a brand-new election
        cycle. Phase 3's own preflight (`preflight_phase3`) checks all
        three separately, since THOSE gates are meaningful.
        """
        errs: list[str] = []
        if not self.election.dates.date_full.strip():
            errs.append("Избори: датум избора није унет")
        if not self.election.types:
            errs.append("Избори: листа врста избора је празна")
        if not self.election.rik_decision.strip():
            # Names the two fields the operator actually has to fill and
            # where they live. The old wording quoted the internal field
            # name — "'rik_decision' (одлука РИК-а) је празно" — which
            # says nothing about what to do, and this check blocks the
            # whole tab: an operator who had just typed an electoral
            # list could not save it either, and had no way to tell from
            # the message that the two were connected.
            errs.append(
                "Изборни циклус: унесите број и датум одлуке РИК-а којом је"
                " покренут изборни циклус (корак 1 „Изборни циклус”, поље"
                " „Одлука РИК-а” — Број одлуке и Датум одлуке). Док оба нису"
                " попуњена, поставке се не могу сачувати."
            )
        return errs

    def party_full_name(self, abbrev: str, nacelnik_full_name: str = "") -> tuple[str, bool]:
        """Returns (full_name, matched_explicitly). False means nacelnik fallback.

        `nacelnik_full_name` comes from OikConstants (see its docstring
        for why it lives there, not on this class) — callers pass
        `oik.nacelnik_full_name` explicitly since ElectionConfig has no
        access to OIK data itself.

        `abbrev` is stalni's party abbreviation (looked up in
        `party_full_names`, populated from the Странке tab) OR prosireni's
        entity_id (`Person.party` holds the short id there too — see
        `build_prosireni_allocation`'s docstring) — resolved via the
        candidacies registry instead, since prosireni has no Странке-style
        abbreviation table of its own.
        """
        key = abbrev.strip()
        if key in self.party_full_names:
            return self.party_full_names[key], True
        entity = self.candidacies.entity_by_id(key)
        if entity is not None:
            from biracki_odbor.config.candidacies import canonical_entity_name
            return canonical_entity_name(entity, self.candidacies.entities), True
        return nacelnik_full_name, False

    def party_contact(self, abbrev: str) -> PartyContact:
        """Returns the email+phone for a party, or an empty PartyContact.

        Never raises — callers (the Outlook send dialog) treat an
        empty email as "operator will fill it inline" rather than as
        a validation error.
        """
        return self.party_contacts.get(abbrev.strip(), PartyContact())


def load(path: Path | str) -> ElectionConfig:
    p = Path(path)
    if not p.exists():
        return ElectionConfig()
    with p.open("r", encoding="utf-8") as f:
        return ElectionConfig.from_dict(json.load(f))


def save(config: ElectionConfig, path: Path | str) -> None:
    # Lazy-generate the election UID on first save. Stable for the rest of
    # the cycle; party file markers and the popunjeni cache key off it.
    if not config.election_uuid.strip():
        config.election_uuid = uuid.uuid4().hex
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(p)
