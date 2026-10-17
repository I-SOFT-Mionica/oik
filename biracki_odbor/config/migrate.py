"""Migration: legacy single election_config.json → split oik + election files.

On first run we look for a single legacy file that contains both
municipality+chairman (now OIK-level) and election+document+parties.
If found, we split it and write the two new files. Idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

from biracki_odbor.config import election as election_mod
from biracki_odbor.config import oik as oik_mod


def split_legacy(
    legacy_path: Path | str,
    out_oik: Path | str,
    out_election: Path | str,
) -> tuple[oik_mod.OikConstants, election_mod.ElectionConfig]:
    """Read a legacy single config and write the two new files.

    Returns the parsed objects so callers can present them in the UI.
    The legacy file is NOT deleted — caller decides.
    """
    legacy = Path(legacy_path)
    with legacy.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # OIK side
    oik = oik_mod.OikConstants.from_dict({
        "municipality": data.get("municipality", {}),
        "chairman": data.get("chairman", {}),
        # legacy never had polling_stations or lock_password in this file
        "polling_stations": [],
        "lock_password": oik_mod.DEFAULT_LOCK_PASSWORD,
    })

    # Election side
    election = election_mod.ElectionConfig.from_dict({
        "election": data.get("election", {}),
        "document": data.get("document", {}),
        "party_full_names": data.get("party_full_names", {}),
        # party_contacts is post-§3 — legacy configs don't have it;
        # an empty dict is the right default (operator can fill it
        # via the Election Settings parties table when they need it).
        "party_contacts": data.get("party_contacts", {}),
    })

    oik_mod.save(oik, out_oik)
    election_mod.save(election, out_election)
    return oik, election
