"""Legal name forms of the local election commission, by unit type.

Every generated document names the commission and its territory. The
wording differs by the type of local self-government unit (verified
against real decisions: ОИК Мионица, ГИК Ваљево 2026, ИК ГО Лазаревац 2026):

  општина         Општинска изборна комисија општине Мионица ... у општини Мионица
  град            Градска изборна комисија града Ваљева ...     у граду Ваљеву
  градска општина Изборна комисија градске општине Лазаревац ... у градској општини Лазаревац

A municipality keeps its name in the nominative after "општине", while a
city takes the genitive ("града Ваљева"). For a city municipality the
commission has no adjective and "градске општине X" always follows it,
so on its own it is never just "Изборна комисија".

The type comes from the bundled registry by municipality code
(config/opstine.py); no code or an unknown code means општина, which is
how every pre-existing install behaves.
"""

from __future__ import annotations

from dataclasses import dataclass

from biracki_odbor.config import opstine as opstine_mod
from biracki_odbor.config.opstine import VRSTA_GRAD, VRSTA_GRADSKA_OPSTINA, VRSTA_OPSTINA

_HEADS = {
    #                     nominative,                   genitive,                     dative
    VRSTA_OPSTINA:         ("Општинска изборна комисија", "Општинске изборне комисије", "Општинској изборној комисији"),
    VRSTA_GRAD:            ("Градска изборна комисија", "Градске изборне комисије", "Градској изборној комисији"),
    VRSTA_GRADSKA_OPSTINA: ("Изборна комисија", "Изборне комисије", "Изборној комисији"),
}
_UNIT_WORDS = {
    #                     genitive,           locative
    VRSTA_OPSTINA:         ("општине", "општини"),
    VRSTA_GRAD:            ("града", "граду"),
    VRSTA_GRADSKA_OPSTINA: ("градске општине", "градској општини"),
}
NACELNIK_ROLES = {
    VRSTA_OPSTINA:         "начелника Општинске управе",
    VRSTA_GRAD:            "начелника Градске управе",
    VRSTA_GRADSKA_OPSTINA: "начелника Управе",
}


@dataclass(frozen=True)
class CommissionTerms:
    vrsta: str
    head: str
    head_gen: str
    head_dat: str
    unit_word_gen: str
    unit_name_gen: str
    unit_word_loc: str
    unit_name_loc: str
    full_committee_name: str = ""

    @property
    def unit_gen(self) -> str:
        """"општине Мионица" / "града Ваљева" / "градске општине Лазаревац"."""
        return f"{self.unit_word_gen} {self.unit_name_gen}".strip()

    @property
    def in_unit(self) -> str:
        """"у општини Мионица" / "у граду Ваљеву" / "у градској општини Лазаревац"."""
        return f"у {self.unit_word_loc} {self.unit_name_loc}".strip()

    @property
    def _needs_unit(self) -> bool:
        return self.vrsta == VRSTA_GRADSKA_OPSTINA

    @property
    def subject(self) -> str:
        """The commission as a sentence subject on its own."""
        return f"{self.head} {self.unit_gen}" if self._needs_unit else self.head

    @property
    def subject_gen(self) -> str:
        return f"{self.head_gen} {self.unit_gen}" if self._needs_unit else self.head_gen

    @property
    def dative_with_place(self) -> str:
        """For "… су достављени предлози" in the образложење."""
        if self._needs_unit:
            return f"{self.head_dat} {self.unit_gen}"
        return f"{self.head_dat} {self.in_unit}"

    @property
    def preamble_subject(self) -> str:
        """Opening line of a решење. Cities and city municipalities use
        their configured full legal name (e.g. ГИК Ваљево's "…за
        спровођење избора за одборнике Скупштине града Ваљева");
        municipalities keep the long-standing short form."""
        if self.vrsta != VRSTA_OPSTINA and self.full_committee_name.strip():
            return self.full_committee_name.strip()
        return f"{self.head} {self.unit_gen}"

    @property
    def signature_lines(self) -> tuple[str, str]:
        return self.head.upper(), self.unit_gen.upper()

    @property
    def local_assembly(self) -> str:
        """"Скупштине општине Мионица" / "Скупштине града Ваљева" / …"""
        return f"Скупштине {self.unit_gen}"


def vrsta_for(sifra: str) -> str:
    entry = opstine_mod.find_by_sifra(sifra) if sifra else None
    return entry.vrsta if entry is not None else VRSTA_OPSTINA


def terms_for(
    vrsta: str, name: str, name_genitive: str = "", name_locative: str = "",
    full_committee_name: str = "",
) -> CommissionTerms:
    from biracki_odbor.config.declension import place_to_genitive, place_to_locative
    name = name.strip()
    head, head_gen, head_dat = _HEADS[vrsta]
    word_gen, word_loc = _UNIT_WORDS[vrsta]
    if vrsta == VRSTA_GRAD:
        gen = name_genitive.strip() or place_to_genitive(name)
        loc = name_locative.strip() or place_to_locative(name)
    else:
        gen = loc = name
    return CommissionTerms(
        vrsta=vrsta, head=head, head_gen=head_gen, head_dat=head_dat,
        unit_word_gen=word_gen, unit_name_gen=gen,
        unit_word_loc=word_loc, unit_name_loc=loc,
        full_committee_name=full_committee_name,
    )


def commission_terms(municipality) -> CommissionTerms:
    """Terms for a config.oik.Municipality."""
    return terms_for(
        vrsta_for(municipality.sifra_opstine),
        municipality.name,
        municipality.name_genitive,
        municipality.name_locative,
        municipality.full_committee_name,
    )


def default_full_committee_name(vrsta: str, name: str, name_genitive: str = "") -> str:
    """Suggested value for Municipality.full_committee_name (signature
    block). City form follows ГИК Ваљево's own decisions."""
    name = name.strip()
    if not name:
        return ""
    t = terms_for(vrsta, name, name_genitive)
    if vrsta == VRSTA_OPSTINA:
        return f"Општинска изборна комисија у општини {name}"
    if vrsta == VRSTA_GRAD:
        return f"Градска изборна комисија за спровођење избора за одборнике {t.local_assembly}"
    return t.subject
