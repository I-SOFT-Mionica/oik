"""OIK constants — rarely-changing settings owned by the electoral commission.

Lives in `oik_constants.json` in the install directory. Edited via the
Поставке tab. Contains: municipality (in three case forms), the list of
polling stations, the chairman, and the file-lock password used when
generating party workbooks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from biracki_odbor.core.models import PollingStation
from biracki_odbor.config.schema import coerce_float, coerce_int, coerce_str, require_keys


DEFAULT_LOCK_PASSWORD = "bo2026"  # legacy default for backward compatibility

# Standard legal title of the municipal chief's office (Закон о локалној
# самоуправи) — this is the SAME title in every municipality in Serbia,
# not something that varies per-OIK. Filling out the office's function
# isn't optional local configuration, it's a fixed legal fact — so this
# is a real default the field falls back to whenever it's blank, not
# just a placeholder hint the operator has to notice and copy in.
# Only the municipality name (already known via Municipality.name)
# actually varies; see OikConstants.nacelnik_proposal_name.
DEFAULT_NACELNIK_ROLE = "начелника Општинске управе"


def default_station_full_name(name: str, address: str) -> str:
    """Starting value for a polling station's editable full name.

    Address, not municipality: every station belongs to the same
    municipality, so "<school> — <municipality>" (field reports from
    Мионица and Уб) gave every BM the same suffix, while several stations
    sharing one building still need the address to tell them apart.
    Comma-joined like core.phase3_docx's name+address lines; no trailing
    comma when the address is blank.
    """
    name = name.strip()
    address = address.strip()
    return f"{name}, {address}" if (name and address) else name


@dataclass
class Municipality:
    name: str = ""
    name_genitive: str = ""
    name_locative: str = ""
    full_committee_name: str = ""
    is_vojvodina: bool = False
    # Official municipality website, e.g. "ub.rs". Available to document
    # generation as the {municipality_website} template variable (see
    # config/obrazlozenje.py's render()).
    website: str = ""
    # "Шифра општине" — RIK's own municipality code (config/opstine.py's
    # bundled registry). A plain identifier, never used arithmetically,
    # so it's a string even though the source data is numeric-looking.
    # Set by the Опште tab's municipality picker; used to locate the
    # right block in an imported RIK RASPODELA workbook
    # (core/rik_raspodela_import.py).
    sifra_opstine: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Municipality":
        return cls(
            name=coerce_str(d.get("name")),
            name_genitive=coerce_str(d.get("name_genitive")),
            name_locative=coerce_str(d.get("name_locative")),
            full_committee_name=coerce_str(d.get("full_committee_name")),
            is_vojvodina=bool(d.get("is_vojvodina", False)),
            website=coerce_str(d.get("website")),
            sifra_opstine=coerce_str(d.get("sifra_opstine")),
        )


@dataclass
class Chairman:
    title: str = "ПРЕДСЕДНИК"
    name: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chairman":
        return cls(
            title=coerce_str(d.get("title"), "ПРЕДСЕДНИК"),
            name=coerce_str(d.get("name")),
        )


# Vocabulary matches Word's own "Поставити подразумеване вредности" dialog
# (what an operator sees if they ever open a generated .docx and check) —
# "multiple_1_15" is the one python-docx's blank-document template used by
# default before this was ever set explicitly.
LINE_SPACING_CHOICES = ("single", "one_point_five", "double", "multiple_1_15")


@dataclass
class DocumentFormat:
    """Formatting defaults applied to every generated .docx (Phase 3,
    Престанак, Измене) — line spacing and header/footer distance from
    the page edge. Lives here, not ElectionConfig, since it doesn't
    change between election cycles. See core.phase3_docx.
    apply_document_format(), the single place all three generators read
    this from, so they can't drift apart from each other."""

    line_spacing: str = "single"
    header_distance_cm: float = 1.0
    footer_distance_cm: float = 1.0
    # Two independently-configurable groups, surfaced on the generation
    # screens themselves (Phase 3 / Измене) rather than buried in
    # settings -- the actual field complaint was 2-3 rows of overflow
    # pushing a решење onto an unwanted 4th page, and the operator wants
    # to shrink spacing right where they're about to generate and can
    # see the page count, not hunt through Поставке ОИК.
    #
    # "RIK format" (the default) restores roughly the ORIGINAL look —
    # before this was configurable, title-block paragraphs mixed 0/3/6/12pt
    # and ordinary body paragraphs (тачка 1/2/3, РИК provision,
    # образложење, legal remedy) mostly used 6pt after (some 3pt), all
    # hardcoded per-call-site with no visible pattern to which got which.
    # NOT covered by either group — these are fixed layout matched against
    # the official reference forms, never collapsed into a single number:
    # the main "РЕШЕЊЕ"/title heading's own larger break, the
    # "Образложење" section heading, and the signature/broj block.
    title_before_pt: float = 0.0
    title_after_pt: float = 6.0
    body_before_pt: float = 0.0
    body_after_pt: float = 6.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentFormat":
        spacing = coerce_str(d.get("line_spacing"), "single") or "single"
        if spacing not in LINE_SPACING_CHOICES:
            spacing = "single"
        return cls(
            line_spacing=spacing,
            header_distance_cm=coerce_float(d.get("header_distance_cm"), 1.0),
            footer_distance_cm=coerce_float(d.get("footer_distance_cm"), 1.0),
            title_before_pt=coerce_float(d.get("title_before_pt"), 0.0),
            title_after_pt=coerce_float(d.get("title_after_pt"), 6.0),
            body_before_pt=coerce_float(d.get("body_before_pt"), 0.0),
            body_after_pt=coerce_float(d.get("body_after_pt"), 6.0),
        )


@dataclass
class OikConstants:
    municipality: Municipality = field(default_factory=Municipality)
    polling_stations: list[PollingStation] = field(default_factory=list)
    chairman: Chairman = field(default_factory=Chairman)
    lock_password: str = DEFAULT_LOCK_PASSWORD
    # Path to the Stalni_sastav.xlsx template; empty → auto-find in sablon/.
    template_path: str = ""
    # Role/title of the municipal chief (начелник) WITHOUT the
    # municipality name — e.g. "начелника Општинске управе", not
    # "начелника Општинске управе општине Уб". `nacelnik_proposal_name`
    # below appends "општине {municipality.name}" automatically, so the
    # full text always reflects the current municipality even if it's
    # ever renamed/corrected — see ElectionConfig.party_full_name() for
    # where this feeds into решења/измене proposal text. Lives here (not
    # ElectionConfig) because the chief doesn't change between election
    # cycles — "New election cycle" must NOT reset this.
    #
    # Defaults to DEFAULT_NACELNIK_ROLE, same as Chairman.title defaults
    # to "ПРЕДСЕДНИК" — this is fixed by law, not a blank the operator
    # is expected to notice and fill in themselves. Only override it if
    # a specific municipality genuinely uses different wording.
    nacelnik_full_name: str = DEFAULT_NACELNIK_ROLE
    document_format: DocumentFormat = field(default_factory=DocumentFormat)

    @property
    def nacelnik_proposal_name(self) -> str:
        """Full 'начелника Општинске управе општине X' proposal-text
        phrase. Uses the municipality's nominative name, matching the
        "општине {mun.name}" convention already used elsewhere in
        generated decisions (e.g. "Општинска изборна комисија општине
        Уб") — not the genitive form.

        Falls back to DEFAULT_NACELNIK_ROLE even if the stored field is
        blank (e.g. an old config saved before this default existed, or
        the operator cleared it by mistake) — the office's function is
        a legal fact, not configuration that should ever silently
        produce a blank decision line just because a field was empty.
        """
        from biracki_odbor.config.commission import NACELNIK_ROLES, commission_terms
        terms = commission_terms(self.municipality)
        role = self.nacelnik_full_name.strip()
        if not role or role in NACELNIK_ROLES.values():
            # A standard title isn't a customization -- follow the unit type
            # ("…Градске управе града Ваљева", "…Управе градске општине Лазаревац").
            role = NACELNIK_ROLES[terms.vrsta]
        muni = self.municipality.name.strip()
        return f"{role} {terms.unit_gen}" if muni else role

    def to_dict(self) -> dict[str, Any]:
        return {
            "municipality": self.municipality.to_dict(),
            "polling_stations": [ps.to_dict() for ps in self.polling_stations],
            "chairman": self.chairman.to_dict(),
            "lock_password": self.lock_password,
            "template_path": self.template_path,
            "nacelnik_full_name": self.nacelnik_full_name,
            "document_format": self.document_format.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OikConstants":
        stations_raw = d.get("polling_stations", []) or []
        return cls(
            municipality=Municipality.from_dict(d.get("municipality", {}) or {}),
            polling_stations=[
                PollingStation.from_dict(s) for s in stations_raw if isinstance(s, dict)
            ],
            chairman=Chairman.from_dict(d.get("chairman", {}) or {}),
            lock_password=coerce_str(d.get("lock_password"), DEFAULT_LOCK_PASSWORD),
            template_path=coerce_str(d.get("template_path")),
            nacelnik_full_name=coerce_str(d.get("nacelnik_full_name"), DEFAULT_NACELNIK_ROLE),
            document_format=DocumentFormat.from_dict(d.get("document_format", {}) or {}),
        )

    def validate(self) -> list[str]:
        """Return Cyrillic error strings (empty list = OK)."""
        errs: list[str] = []
        errs += require_keys(
            self.municipality.to_dict(),
            ["name", "name_genitive", "name_locative", "full_committee_name"],
            "Општина",
        )
        if len(self.polling_stations) == 0:
            errs.append("Бирачка места: мора постојати најмање једно бирачко место")
        seen_bms: set[int] = set()
        for i, ps in enumerate(self.polling_stations, start=1):
            if ps.bm_number <= 0:
                errs.append(f"Бирачко место {i}: број мора бити позитиван")
            if ps.bm_number in seen_bms:
                errs.append(f"Бирачко место {ps.bm_number}: дупликат броја")
            seen_bms.add(ps.bm_number)
            if not ps.name.strip():
                errs.append(f"Бирачко место {ps.bm_number}: назив је празан")
        if len(self.lock_password) < 4:
            errs.append("Лозинка за закључавање мора имати најмање 4 карактера")
        return errs

    def station_by_bm(self, bm_number: int) -> PollingStation | None:
        for ps in self.polling_stations:
            if ps.bm_number == bm_number:
                return ps
        return None


def load(path: Path | str) -> OikConstants:
    """Load from disk; return defaults if file missing."""
    p = Path(path)
    if not p.exists():
        return OikConstants()
    with p.open("r", encoding="utf-8") as f:
        return OikConstants.from_dict(json.load(f))


def save(constants: OikConstants, path: Path | str) -> None:
    """Atomic save: write to .tmp then replace."""
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(constants.to_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(p)
