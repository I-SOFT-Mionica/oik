"""Bundled municipality registry — (шифра општине, назив, округ) triples.

Extracted once from a real RIK RASPODELA export (see
`core/rik_raspodela_import.py`'s docstring) and shipped as a static
resource (`resources/opstine.json`). Municipality codes are a stable
national numbering scheme, not reassigned per election cycle, so this
registry isn't expected to go stale between cycles — it exists so the
Опште tab's municipality picker (`gui/tabs/settings_oik.py`) works
immediately on a fresh install, before any cycle-specific RIK file has
been imported.

This is a fixed count of whatever was in the export it was built from —
never treated as an invariant to validate against elsewhere. Matching a
freshly-imported RASPODELA file happens purely by code
(`core.rik_raspodela_import.find_municipality_block`), independent of
this list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


# The 7 управни окрузи of AP Vojvodina, spelled as in opstine.json --
# together they cover exactly the province's 45 local self-government units.
VOJVODINA_OKRUZI = frozenset({
    "СЕВЕРНО-БАЧКИ", "СРЕДЊЕ-БАНАТСКИ", "СЕВЕРНО-БАНАТСКИ", "ЈУЖНО-БАНАТСКИ",
    "ЗАПАДНО-БАЧКИ", "ЈУЖНО-БАЧКИ", "СРЕМСКИ",
})


VRSTA_OPSTINA = "opstina"
VRSTA_GRAD = "grad"
VRSTA_GRADSKA_OPSTINA = "gradska_opstina"


@dataclass(frozen=True)
class OpstinaEntry:
    sifra: str
    name: str
    okrug: str
    # Local self-government type per the Law on Territorial Organization
    # (27 cities + Belgrade's 17 city municipalities in RIK's data, the
    # rest municipalities) -- drives the commission's legal name in every
    # document (config/commission.py).
    vrsta: str = VRSTA_OPSTINA
    # Name as written in decisions. RIK's list marks some cities in the
    # name itself ("Нови Сад - град", "Град Ниш", "Београд-Лазаревац").
    doc_name: str = ""
    # Only where the rule-based declension gets it wrong ("Чачку", "Шапцу").
    doc_locative: str = ""

    @property
    def is_vojvodina(self) -> bool:
        return self.okrug in VOJVODINA_OKRUZI

    @property
    def document_name(self) -> str:
        return self.doc_name or self.name


@lru_cache(maxsize=1)
def load_registry() -> tuple[OpstinaEntry, ...]:
    """All bundled municipality entries, in the source file's order
    (grouped by округ — a reasonable browsing order for a picker)."""
    raw = resources.files("biracki_odbor.resources").joinpath("opstine.json").read_text(
        encoding="utf-8",
    )
    data = json.loads(raw)
    return tuple(
        OpstinaEntry(
            sifra=str(d["sifra"]), name=d["name"], okrug=d["okrug"],
            vrsta=d.get("vrsta", VRSTA_OPSTINA), doc_name=d.get("doc_name", ""),
            doc_locative=d.get("doc_locative", ""),
        )
        for d in data
    )


def find_by_sifra(sifra: str) -> OpstinaEntry | None:
    sifra = str(sifra).strip()
    for entry in load_registry():
        if entry.sifra == sifra:
            return entry
    return None


def find_by_name(name: str) -> OpstinaEntry | None:
    """Exact-match lookup, used to validate/resolve the strict picker's
    typed text back to a registry entry. Not a fuzzy/substring search —
    that's exactly the failure mode this registry exists to avoid."""
    name = name.strip()
    for entry in load_registry():
        if entry.name == name:
            return entry
    return None
