"""Tests for §3 — party contact info in ElectionConfig.

Schema decision: `party_full_names: dict[str, str]` stays unchanged
(7+ test fixtures + phase3_docx depend on it as a string dict).
Email + phone live in a parallel `party_contacts: dict[str, PartyContact]`
field. Pre-§3 configs deserialize cleanly: missing party_contacts →
empty dict, no breakage.
"""

from __future__ import annotations

import json
from pathlib import Path

from biracki_odbor.config import election as election_mod
from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo, PartyContact,
)


def _make_election(**kwargs) -> ElectionConfig:
    defaults = dict(
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"], rik_decision="X",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "Посланичка група"},
        election_uuid="party-contact-test",
    )
    defaults.update(kwargs)
    return ElectionConfig(**defaults)


def test_default_party_contacts_is_empty() -> None:
    """Configs that don't set party_contacts work as before — the
    party_contact() lookup just returns an empty PartyContact."""
    ec = _make_election()
    assert ec.party_contacts == {}
    c = ec.party_contact("СНС")
    assert isinstance(c, PartyContact)
    assert c.is_empty


def test_party_contact_lookup_returns_stored() -> None:
    ec = _make_election(party_contacts={
        "СНС": PartyContact(email="kontakt@sns.rs", phone="+381 11 1111"),
    })
    c = ec.party_contact("СНС")
    assert c.email == "kontakt@sns.rs"
    assert c.phone == "+381 11 1111"
    # Unknown party → empty default (no KeyError).
    assert ec.party_contact("ДС").is_empty


def test_round_trip_via_save_load(tmp_path: Path) -> None:
    """Serialize + deserialize preserves party_contacts. Empty
    contacts are dropped from the JSON so the file isn't noisy."""
    ec = _make_election(party_contacts={
        "СНС": PartyContact(email="kontakt@sns.rs", phone="+381 11 1111"),
        "СПС": PartyContact(email="", phone=""),  # all-empty, should be dropped
    })
    p = tmp_path / "ec.json"
    election_mod.save(ec, p)

    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "party_contacts" in raw
    assert "СНС" in raw["party_contacts"]
    assert "СПС" not in raw["party_contacts"], (
        "All-empty contacts must be omitted from the JSON dump — keeps"
        " election_config.json tidy and makes loading legacy v0 files"
        " visually indistinguishable from a freshly-cleared config."
    )

    loaded = election_mod.load(p)
    assert loaded.party_contact("СНС").email == "kontakt@sns.rs"
    assert loaded.party_contact("СПС").is_empty


def test_legacy_config_without_party_contacts(tmp_path: Path) -> None:
    """Pre-§3 election_config.json files don't carry party_contacts;
    must load as if it were an empty dict — no crash, no data loss for
    the rest of the file."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({
        "election": {"date_full": "17. децембар 2023. године",
                     "types": ["parliamentary"], "rik_decision": "X"},
        "document": {"number_prefix": "013-5-30", "legal_basis": "L"},
        "party_full_names": {"СНС": "A", "_default": "."},
        "election_uuid": "legacy-uuid",
    }, ensure_ascii=False), encoding="utf-8")
    loaded = election_mod.load(p)
    # §21 migration: "_default" is stripped out of party_full_names on
    # load — it was never a real parliamentary group. Its value now
    # migrates cross-file into OikConstants.nacelnik_full_name (see
    # app_state.py's _read_legacy_nacelnik_name), not onto ElectionConfig
    # at all, so there's nothing further to assert on `loaded` here.
    assert loaded.party_full_names == {"СНС": "A"}
    assert loaded.party_contacts == {}
    # Lookup contract holds: returns an empty PartyContact, no KeyError.
    assert loaded.party_contact("СНС").is_empty
