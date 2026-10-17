"""Observer accreditation data model.

Observers are submitted by NGOs, civic organisations, and foreign observer
missions — NOT by the political parties in the election config. OIK is
only responsible for observer accreditation when local elections are part
of the current election cycle.

Storage: {HOME}/posmatraci.json
  {"orgs": [...], "observers": [...]}

Validation rules:
  - Domestic observers and foreigners with a Serbian temp-JMBG use the
    `jmbg` field; MOD 11 (soft) + age ≥ 18 (hard) checks apply.
  - Foreign observers without a Serbian JMBG use `foreign_doc_type` +
    `foreign_doc_number`; no JMBG checks run for these.
  - Cross-workflow hard block: a JMBG that appears in the стални or
    проширени master cannot be accredited as an observer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from biracki_odbor.core import jmbg as jmbg_mod


# ── Block types for legitimacija layout ──────────────────────────────

BLOCK_STATIC_TEXT = "STATIC_TEXT"
BLOCK_FIELD_NAME = "FIELD_NAME"
BLOCK_FIELD_ORG = "FIELD_ORG"
BLOCK_FIELD_ID = "FIELD_ID"
BLOCK_FIELD_BM = "FIELD_BM"
BLOCK_FIELD_SERIAL = "FIELD_SERIAL"
BLOCK_FIELD_MUNICIPALITY = "FIELD_MUNICIPALITY"
BLOCK_FIELD_ELECTION = "FIELD_ELECTION"
BLOCK_DIVIDER = "DIVIDER"
BLOCK_SPACER = "SPACER"
BLOCK_STAMP_BOX = "STAMP_BOX"
BLOCK_SIGNATURE_LINE = "SIGNATURE_LINE"

ALL_BLOCK_TYPES: list[str] = [
    BLOCK_STATIC_TEXT,
    BLOCK_FIELD_NAME,
    BLOCK_FIELD_ORG,
    BLOCK_FIELD_ID,
    BLOCK_FIELD_BM,
    BLOCK_FIELD_SERIAL,
    BLOCK_FIELD_MUNICIPALITY,
    BLOCK_FIELD_ELECTION,
    BLOCK_DIVIDER,
    BLOCK_SPACER,
    BLOCK_STAMP_BOX,
    BLOCK_SIGNATURE_LINE,
]

BLOCK_LABELS: dict[str, str] = {
    BLOCK_STATIC_TEXT: "Слободан текст",
    BLOCK_FIELD_NAME: "Поље: Име и Презиме",
    BLOCK_FIELD_ORG: "Поље: Назив организације",
    BLOCK_FIELD_ID: "Поље: Број документа",
    BLOCK_FIELD_BM: "Поље: Расподела БМ",
    BLOCK_FIELD_SERIAL: "Поље: Број легитимације",
    BLOCK_FIELD_MUNICIPALITY: "Поље: Општина",
    BLOCK_FIELD_ELECTION: "Поље: Назив избора",
    BLOCK_DIVIDER: "Хоризонтална линија",
    BLOCK_SPACER: "Празан ред",
    BLOCK_STAMP_BOX: "Место за печат (М.П.)",
    BLOCK_SIGNATURE_LINE: "Потпис председника ОИК",
}


@dataclass
class LegitimacijaBlock:
    """One content block in the operator-designed legitimacija layout."""

    block_type: str
    value: str = ""        # only used by STATIC_TEXT
    col_span: int = 12     # 1–12 in a 12-column grid (12 = full width)
    row_height: int = 1    # relative height units (1 = single line)
    alignment: str = "center"  # "left" | "center" | "right"

    def to_dict(self) -> dict:
        return {
            "block_type": self.block_type,
            "value": self.value,
            "col_span": self.col_span,
            "row_height": self.row_height,
            "alignment": self.alignment,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LegitimacijaBlock":
        return cls(
            block_type=str(d.get("block_type", BLOCK_STATIC_TEXT)),
            value=str(d.get("value", "")),
            col_span=int(d.get("col_span", 12)),
            row_height=int(d.get("row_height", 1)),
            alignment=str(d.get("alignment", "center")),
        )


# ── Card setup ────────────────────────────────────────────────────────

PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
}


@dataclass
class CardSetup:
    """Physical dimensions of a legitimacija card and the sheet it prints on."""

    card_width_mm: float = 90.0
    card_height_mm: float = 60.0
    gutter_mm: float = 5.0
    paper_size: str = "A4"
    margin_mm: float = 10.0  # page margin on each side

    def cards_per_sheet(self) -> int:
        pw, ph = PAPER_SIZES.get(self.paper_size, PAPER_SIZES["A4"])
        usable_w = pw - 2 * self.margin_mm
        usable_h = ph - 2 * self.margin_mm
        cols = max(1, int(
            (usable_w + self.gutter_mm) / (self.card_width_mm + self.gutter_mm)
        ))
        rows = max(1, int(
            (usable_h + self.gutter_mm) / (self.card_height_mm + self.gutter_mm)
        ))
        return cols * rows

    def to_dict(self) -> dict:
        return {
            "card_width_mm": self.card_width_mm,
            "card_height_mm": self.card_height_mm,
            "gutter_mm": self.gutter_mm,
            "paper_size": self.paper_size,
            "margin_mm": self.margin_mm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CardSetup":
        return cls(
            card_width_mm=float(d.get("card_width_mm", 90.0)),
            card_height_mm=float(d.get("card_height_mm", 60.0)),
            gutter_mm=float(d.get("gutter_mm", 5.0)),
            paper_size=str(d.get("paper_size", "A4")),
            margin_mm=float(d.get("margin_mm", 10.0)),
        )


def default_legitimacija_layout() -> list[LegitimacijaBlock]:
    """Pre-seeded legitimacija layout."""
    return [
        LegitimacijaBlock(BLOCK_STATIC_TEXT, "РЕПУБЛИКА СРБИЈА", col_span=6, alignment="left"),
        LegitimacijaBlock(BLOCK_SPACER, col_span=2),
        LegitimacijaBlock(BLOCK_FIELD_ELECTION, col_span=4, alignment="right"),
        LegitimacijaBlock(BLOCK_FIELD_MUNICIPALITY, col_span=5, alignment="left"),
        LegitimacijaBlock(BLOCK_STATIC_TEXT, "ПОСМАТРАЧ", col_span=12, row_height=2, alignment="center"),
        LegitimacijaBlock(BLOCK_DIVIDER, col_span=12, alignment="left"),
        LegitimacijaBlock(BLOCK_FIELD_NAME, col_span=6, alignment="left"),
        LegitimacijaBlock(BLOCK_SPACER, col_span=6),
        LegitimacijaBlock(BLOCK_FIELD_ORG, col_span=6, alignment="left"),
        LegitimacijaBlock(BLOCK_SPACER, col_span=6),
        LegitimacijaBlock(BLOCK_FIELD_SERIAL, col_span=6, alignment="right"),
        LegitimacijaBlock(BLOCK_STAMP_BOX, col_span=2),
        LegitimacijaBlock(BLOCK_SIGNATURE_LINE, col_span=4, row_height=2, alignment="center"),
    ]


# ── Domain dataclasses ────────────────────────────────────────────────

@dataclass
class AccreditingOrg:
    """A domestic organisation authorised to submit observer proposals.

    Not a political party — NGOs, civic orgs, etc.
    Foreign observers are handled at the republic level and are not
    registered through OIK.
    """

    name: str
    contact: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AccreditingOrg":
        return cls(
            name=str(d.get("name", "")),
            contact=str(d.get("contact", "")),
        )


@dataclass
class Observer:
    """A single accredited observer."""

    first_name: str
    last_name: str
    organization: str  # AccreditingOrg.name
    bm_assignment: str  # free text, e.g. "Сва БМ" or "БМ 01, БМ 03"

    jmbg: str = ""
    serial_number: str = ""
    notes: str = ""

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_id(self) -> str:
        return self.jmbg

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Observer":
        return cls(
            first_name=str(d.get("first_name", "")),
            last_name=str(d.get("last_name", "")),
            organization=str(d.get("organization", "")),
            bm_assignment=str(d.get("bm_assignment", "")),
            jmbg=str(d.get("jmbg", "")),
            serial_number=str(d.get("serial_number", "")),
            notes=str(d.get("notes", "")),
        )


# ── Registry ──────────────────────────────────────────────────────────

@dataclass
class ObserverRegistry:
    """In-memory store of orgs + observers for one election cycle."""

    orgs: list[AccreditingOrg] = field(default_factory=list)
    observers: list[Observer] = field(default_factory=list)

    # ── Persistence ─────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "ObserverRegistry":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            orgs = [AccreditingOrg.from_dict(o) for o in data.get("orgs", [])]
            observers = [Observer.from_dict(o) for o in data.get("observers", [])]
            return cls(orgs=orgs, observers=observers)
        except Exception:  # noqa: BLE001
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "orgs": [o.to_dict() for o in self.orgs],
            "observers": [o.to_dict() for o in self.observers],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Validation helpers ────────────────────────────────────────────

    def jmbg_duplicates(self) -> list[str]:
        """JMBGs that appear more than once in the observer list."""
        seen: dict[str, int] = {}
        for ob in self.observers:
            if ob.jmbg:
                seen[ob.jmbg] = seen.get(ob.jmbg, 0) + 1
        return [j for j, count in seen.items() if count > 1]

    def org_names(self) -> list[str]:
        return [o.name for o in self.orgs]


# ── Per-observer validation ───────────────────────────────────────────

@dataclass
class ObserverValidation:
    """Result of validating a single observer before saving."""

    jmbg_invalid: bool = False        # MOD 11 failed (soft)
    underage: bool = False            # age < 18 on election date (hard)
    jmbg_duplicate: bool = False      # same JMBG already in registry (soft)
    member_conflict: bool = False     # JMBG found in стални/проширени master (hard)

    @property
    def is_hard_blocked(self) -> bool:
        return self.underage or self.member_conflict

    @property
    def has_warnings(self) -> bool:
        return self.jmbg_invalid or self.jmbg_duplicate


def validate_observer(
    observer: Observer,
    registry: ObserverRegistry,
    election_date_iso: str = "",
    master_jmbgs: set[str] | None = None,
    existing_index: int | None = None,
) -> ObserverValidation:
    """Validate a single observer, returning all applicable issues.

    `existing_index`: when editing, the index of the observer being replaced
    (excluded from duplicate detection).
    `master_jmbgs`: set of JMBGs from the стални + проширени master sheets.
    `election_date_iso`: "YYYY-MM-DD" string; used for age check.
    """
    from datetime import date as _date

    v = ObserverValidation()

    if not observer.jmbg:
        return v  # no JMBG to check

    # MOD 11 (soft)
    if not jmbg_mod.is_valid(observer.jmbg):
        v.jmbg_invalid = True

    # Age ≥ 18 (hard)
    if election_date_iso:
        try:
            y, m, d = (int(x) for x in election_date_iso.split("-"))
            on_date = _date(y, m, d)
        except (ValueError, AttributeError):
            on_date = _date.today()
    else:
        on_date = _date.today()

    if not jmbg_mod.is_at_least_18_on(observer.jmbg, on_date):
        v.underage = True

    # JMBG duplicate within registry (soft)
    for i, ob in enumerate(registry.observers):
        if i == existing_index:
            continue
        if ob.jmbg and ob.jmbg == observer.jmbg:
            v.jmbg_duplicate = True
            break

    # Cross-workflow conflict (hard)
    if master_jmbgs and observer.jmbg in master_jmbgs:
        v.member_conflict = True

    return v
