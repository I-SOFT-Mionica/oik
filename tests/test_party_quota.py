"""Tests for PartyQuota and its persistence through ElectionConfig."""

from __future__ import annotations

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.core.models import PartyQuota


def test_party_quota_defaults() -> None:
    q = PartyQuota()
    assert (q.predsednik, q.zamenik, q.clan_i_zamenik) == (0, 0, 0)


def test_party_quota_to_dict_from_dict_round_trip() -> None:
    q = PartyQuota(predsednik=23, zamenik=5, clan_i_zamenik=93)
    restored = PartyQuota.from_dict(q.to_dict())
    assert restored == q


def test_party_quota_from_dict_missing_keys_defaults_to_zero() -> None:
    restored = PartyQuota.from_dict({})
    assert restored == PartyQuota()


def test_election_config_party_quotas_round_trip() -> None:
    ec = ElectionConfig(party_quotas={
        "СНС": PartyQuota(predsednik=23, zamenik=5, clan_i_zamenik=93),
        "СПС": PartyQuota(predsednik=5, zamenik=3, clan_i_zamenik=20),
    })
    restored = ElectionConfig.from_dict(ec.to_dict())
    assert restored.party_quotas == ec.party_quotas


def test_election_config_party_quotas_absent_defaults_to_empty() -> None:
    restored = ElectionConfig.from_dict({})
    assert restored.party_quotas == {}
