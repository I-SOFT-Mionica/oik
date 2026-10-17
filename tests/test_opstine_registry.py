"""Tests for config.opstine — the bundled municipality registry.

The registry is whatever was extracted from the RIK export it was built
from; these tests check internal consistency (loader/lookup behavior),
never an expected total count.
"""

from __future__ import annotations

from biracki_odbor.config import opstine


def test_load_registry_nonempty_and_cached() -> None:
    reg1 = opstine.load_registry()
    reg2 = opstine.load_registry()
    assert len(reg1) > 0
    assert reg1 is reg2  # lru_cache — same tuple instance, not a fixed count check


def test_find_by_sifra_known_entry() -> None:
    entry = opstine.find_by_sifra("71218")
    assert entry is not None
    assert entry.name == "Уб"
    assert entry.okrug == "КОЛУБАРСКИ"


def test_find_by_sifra_unknown_returns_none() -> None:
    assert opstine.find_by_sifra("00000") is None


def test_find_by_sifra_strips_whitespace() -> None:
    assert opstine.find_by_sifra(" 71218 ") is not None


def test_find_by_name_exact_match_only() -> None:
    entry = opstine.find_by_name("Уб")
    assert entry is not None
    assert entry.sifra == "71218"
    # Substring/partial text must NOT match — that's the exact failure
    # mode this registry exists to eliminate (a bare "б" search would
    # otherwise false-positive-match "Уб" and many other names).
    assert opstine.find_by_name("б") is None
    assert opstine.find_by_name("Уб-нешто") is None
    # Whitespace tolerance is a UX nicety, not a substring match.
    assert opstine.find_by_name(" Уб ") is not None


def test_every_entry_has_sifra_and_name() -> None:
    for entry in opstine.load_registry():
        assert entry.sifra.strip()
        assert entry.name.strip()
        assert entry.okrug.strip()


def test_no_duplicate_sifra() -> None:
    codes = [e.sifra for e in opstine.load_registry()]
    assert len(codes) == len(set(codes))
