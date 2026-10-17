"""Shared dataclasses used across phases and the GUI.

These types are deliberately plain — no behavior beyond `to_dict` /
`from_dict` helpers — so they can be serialized to JSON for the
audit log and read back without surprises.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# Fixed roster of 6 polling-board roles per BM (Cyrillic, must match template).
FUNCTIONS: tuple[str, ...] = (
    "Председник",
    "Заменик председника",
    "Члан 1",
    "Заменик члана 1",
    "Члан 2",
    "Заменик члана 2",
)


def slot_rbr(bm_number: int, function: str) -> int:
    """Canonical sequence number for a (BM, function) slot.

    r.br = (bm_number - 1) * len(FUNCTIONS) + function_index + 1

    Same slot → same number in every file that contains it. President of
    BM 2 is r.br 7 in master AND in every party's per-party workbook,
    making cross-referencing between master and per-party files trivial.
    Unknown function values get placed past the regular range so they
    don't collide with valid slots.
    """
    try:
        func_idx = FUNCTIONS.index(function)
    except ValueError:
        func_idx = len(FUNCTIONS)
    return (bm_number - 1) * len(FUNCTIONS) + func_idx + 1


def split_combined_name(full_name: str) -> tuple[str, str]:
    """Split one "Име [Презиме...]" field into (first_name, last_name).

    First token is the given name; every remaining token (rejoined with
    single spaces) is the surname. Used wherever a form's
    combined_name_header merges Име/Презиме into one input box —
    popunjeni_io.parse_party_file and nacelnik_xlsx.read_nacelnik_xlsx.

    Confirmed field decision: a multi-word surname (or a name that's
    just ambiguous past two words) must still produce a non-blank
    surname rather than leaving the whole string in first_name and
    flagging it unresolved — the two-word case ("Петар Петровић") was
    already unambiguous and unaffected by this; this only changes what
    happens at three or more words. The assumption can still be wrong
    for a compound GIVEN name ("Ана Марија Петровић" splits to "Ана" /
    "Марија Петровић", not "Ана Марија" / "Петровић") — callers that
    already flag this case for operator review (NAME_AMBIGUOUS_SPLIT)
    keep doing so; this function only changes what gets filled in
    while that happens, never leaving a seat's surname blank."""
    tokens = full_name.split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], " ".join(tokens[1:])


@dataclass
class PollingStation:
    """One bm row (polling station)."""

    bm_number: int
    name: str = ""        # short name, e.g. "ОШ Душан Даниловић"
    address: str = ""
    full_name: str = ""   # used in решења, may equal name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PollingStation":
        return cls(
            bm_number=int(d["bm_number"]),
            name=str(d.get("name", "")),
            address=str(d.get("address", "")),
            full_name=str(d.get("full_name", d.get("name", ""))),
        )


@dataclass
class Allocation:
    """Which party fills which (bm, function) slot — from `Raspodela` sheet."""

    bm_number: int
    function: str  # must be a value from FUNCTIONS
    party: str


@dataclass
class PartyQuota:
    """RIK-declared seat quota for one parliamentary group.

    Mirrors RIK's own decision-document table (party × role-count) —
    one combined bucket for the 4 "member" roles (Члан 1/Заменик члана 1/
    Члан 2/Заменик члана 2) because RIK's table doesn't split those
    further, only Председник and Заменик председника get their own
    column. Used to cross-check the matrix builder grid against the
    legally declared allocation, not just a free-form headcount.
    """

    predsednik: int = 0
    zamenik: int = 0
    clan_i_zamenik: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PartyQuota":
        return cls(
            predsednik=int(d.get("predsednik", 0)),
            zamenik=int(d.get("zamenik", 0)),
            clan_i_zamenik=int(d.get("clan_i_zamenik", 0)),
        )


@dataclass
class Person:
    """A single committee member as returned by a party.

    Name is stored split (`first_name` + `last_name`) so the party-side
    Excel forms can enforce ordering and Excel's per-column autocomplete
    helps with repetition. The `name` property gives readers the joined
    form so решења rendering doesn't need to change.
    """

    bm_number: int
    function: str
    party: str
    first_name: str = ""
    last_name: str = ""
    jmbg: str = ""
    mesto: str = ""
    adresa: str = ""
    telefon: str = ""
    email: str = ""
    # True when this slot was filled via appoint_by_nacelnik(), rather than
    # by the allocated party submitting someone. `party` stays the RIK
    # allocation (needed for quota stats and party xlsx round-trip) even
    # after a nacelnik appointment — this is the flag decision-text
    # generation (Решења/Измене) checks to say "on the chief's proposal"
    # instead of misattributing the appointment to the allocated party.
    appointed_by_nacelnik: bool = False

    @property
    def name(self) -> str:
        """Joined display form. Empty when both halves are empty."""
        return f"{self.first_name} {self.last_name}".strip()

    @name.setter
    def name(self, value: str) -> None:
        """Split a joined "First Last" string back into the two fields.

        Setting to "" clears both halves; this keeps callers that do
        `p.name = ""` working through the property rather than reaching
        for first_name/last_name explicitly. Multi-token first names
        ("Ана Марија") land in `first_name`; the last whitespace-separated
        token becomes `last_name`.
        """
        text = (value or "").strip()
        if " " in text:
            self.first_name, self.last_name = text.rsplit(" ", 1)
        else:
            self.first_name, self.last_name = text, ""

    @property
    def is_filled(self) -> bool:
        return bool(self.first_name.strip() or self.last_name.strip())

    @property
    def slot_key(self) -> tuple[int, str]:
        return (self.bm_number, self.function)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Person":
        # Accept either explicit first_name/last_name OR a legacy `name`
        # string we split on the last space — keeps old audit logs readable.
        first = d.get("first_name")
        last = d.get("last_name")
        if first is None and last is None:
            legacy = str(d.get("name", "")).strip()
            if " " in legacy:
                first, last = legacy.rsplit(" ", 1)
            else:
                first, last = legacy, ""
        return cls(
            bm_number=int(d["bm_number"]),
            function=str(d["function"]),
            party=str(d.get("party", "")),
            first_name=str(first or ""),
            last_name=str(last or ""),
            jmbg=str(d.get("jmbg", "")),
            mesto=str(d.get("mesto", "")),
            adresa=str(d.get("adresa", "")),
            telefon=str(d.get("telefon", "")),
            email=str(d.get("email", "")),
            appointed_by_nacelnik=bool(d.get("appointed_by_nacelnik", False)),
        )


@dataclass
class Conflict:
    """Same JMBG (or same name+birthdate) submitted by two or more parties.

    The blocker scenario from real-world OIK work: party A and party B
    both nominate the same person, but a person can only fill one slot.
    """

    conflict_id: str        # stable hash, used to reference in corrections.log
    jmbg: str
    name: str               # representative name (from first occurrence)
    submissions: list[Person] = field(default_factory=list)
    # Matching person(s) found in the OTHER workflow's master (стални vs
    # проширени) — read-only here: resolving them means editing the
    # OTHER workflow's own data, which this Corrections tab can't do.
    # Kept separate from `submissions` so every existing same-workflow
    # resolution path (resolve_conflict/remove_one_slot/remove_from_all,
    # ConflictCard's Keep/Remove buttons) stays untouched and unaware
    # this field even exists.
    cross_workflow: list[Person] = field(default_factory=list)
    # id(person) -> that submission's party's latest received_time_iso
    # (popunjeni_cache), for displaying submission order in the GUI.
    # Keyed by identity rather than slot_key/party: cross_workflow
    # entries share the same BM-number space as submissions, and a
    # transient UI lookup has no need to round-trip through to_dict.
    submission_times: dict[int, str] = field(default_factory=dict, repr=False, compare=False)
    # name_sr of this workflow / the other one (WorkflowSpec.name_sr,
    # e.g. "Стални састав"/"Проширени састав") -- lets ConflictCard
    # label cross_workflow entries correctly regardless of which tab
    # (стални's or проширени's) is doing the rendering, without the
    # widget needing to know about WorkflowSpec itself.
    other_workflow_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "jmbg": self.jmbg,
            "name": self.name,
            "submissions": [p.to_dict() for p in self.submissions],
            "cross_workflow": [p.to_dict() for p in self.cross_workflow],
        }


# ── Validation report types ──────────────────────────────────────────────


Severity = str  # "error" | "warning" | "info"


@dataclass
class Issue:
    """One validation problem, surfaced to the GUI."""

    code: str           # stable machine code, e.g. "JMBG_BAD_CHECKSUM"
    message_sr: str     # Cyrillic message for end users
    severity: Severity = "error"
    # Context — at least one should be populated where it makes sense:
    file: str = ""
    sheet: str = ""
    row: int | None = None
    column: int | str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    """Aggregated outcome of a pre-flight or per-row validation pass."""

    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)

    def to_dict(self) -> dict[str, Any]:
        return {"issues": [i.to_dict() for i in self.issues], "ok": self.ok}
