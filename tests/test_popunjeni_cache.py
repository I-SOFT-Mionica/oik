"""Tests for biracki_odbor.core.popunjeni_cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from biracki_odbor.core import popunjeni_cache
from biracki_odbor.core.models import Issue, Person


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    """Sandbox BIRACKI_ODBOR_HOME so we never touch the maintainer's machine."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))


def _make_entry(path: Path, *, mtime_ns: int = 0, size: int = 0) -> popunjeni_cache.CacheEntry:
    """Build a CacheEntry from a real file, with optional override of fingerprint."""
    if path.exists():
        st = path.stat()
        mtime_ns = mtime_ns or st.st_mtime_ns
        size = size or st.st_size
    return popunjeni_cache.CacheEntry(
        mtime_ns=mtime_ns, size=size,
        records=[{
            "bm": 1, "function": "Председник",
            "person": Person(
                bm_number=1, function="Председник", party="СНС",
                first_name="Петар", last_name="Петровић",
            ).to_dict(),
        }],
        issues=[],
    )


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    """No cache file → empty CacheData; never raises."""
    data = popunjeni_cache.load(election_uuid="abc")
    assert data.entries == {}
    assert data.election_uuid == "abc"


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"PK\x03\x04dummy")
    data = popunjeni_cache.CacheData(
        election_uuid="uuid123",
        entries={str(file): _make_entry(file)},
    )
    popunjeni_cache.save(data)
    loaded = popunjeni_cache.load(election_uuid="uuid123")
    assert str(file) in loaded.entries
    assert loaded.entries[str(file)].size == file.stat().st_size


def test_load_with_wrong_election_uuid_wipes(tmp_path: Path) -> None:
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"PK\x03\x04dummy")
    popunjeni_cache.save(popunjeni_cache.CacheData(
        election_uuid="old-cycle",
        entries={str(file): _make_entry(file)},
    ))
    # New cycle UUID → cache treated as foreign.
    fresh = popunjeni_cache.load(election_uuid="new-cycle")
    assert fresh.entries == {}


def test_load_with_corrupt_json_returns_empty() -> None:
    popunjeni_cache.cache_path().parent.mkdir(parents=True, exist_ok=True)
    popunjeni_cache.cache_path().write_text("{not valid json", encoding="utf-8")
    data = popunjeni_cache.load(election_uuid="x")
    assert data.entries == {}


def test_load_with_wrong_version_returns_empty() -> None:
    popunjeni_cache.cache_path().parent.mkdir(parents=True, exist_ok=True)
    popunjeni_cache.cache_path().write_text(
        json.dumps({"version": 999, "election_uuid": "x", "entries": {}}),
        encoding="utf-8",
    )
    data = popunjeni_cache.load(election_uuid="x")
    assert data.entries == {}


def test_hit_on_unchanged_file(tmp_path: Path) -> None:
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"PK\x03\x04dummy")
    entry = _make_entry(file)
    assert popunjeni_cache.hit(file, entry) is True


def test_hit_false_on_mtime_change(tmp_path: Path) -> None:
    import os
    import time
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"PK\x03\x04dummy")
    entry = _make_entry(file)
    # Bump mtime to make it look modified.
    os.utime(file, (time.time() + 5, time.time() + 5))
    assert popunjeni_cache.hit(file, entry) is False


def test_hit_false_on_size_change(tmp_path: Path) -> None:
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"PK\x03\x04dummy")
    entry = _make_entry(file)
    # Same mtime_ns + bigger size → still cache miss.
    file.write_bytes(b"PK\x03\x04dummylonger")
    import os
    os.utime(file, (file.stat().st_atime, entry.mtime_ns / 1e9))
    # `hit` reads current stat; size mismatches so we expect False.
    assert popunjeni_cache.hit(file, entry) is False


def test_hit_false_when_file_missing(tmp_path: Path) -> None:
    file = tmp_path / "ghost.xlsx"
    entry = popunjeni_cache.CacheEntry(mtime_ns=1, size=1, records=[], issues=[])
    assert popunjeni_cache.hit(file, entry) is False


def test_hit_false_when_entry_none(tmp_path: Path) -> None:
    file = tmp_path / "x.xlsx"
    file.write_bytes(b"x")
    assert popunjeni_cache.hit(file, None) is False


def test_prune_missing_drops_orphaned_entries(tmp_path: Path) -> None:
    file_alive = tmp_path / "alive.xlsx"
    file_alive.write_bytes(b"PK\x03\x04")
    file_dead = tmp_path / "dead.xlsx"
    file_dead.write_bytes(b"PK\x03\x04")
    data = popunjeni_cache.CacheData(
        election_uuid="x",
        entries={
            str(file_alive): _make_entry(file_alive),
            str(file_dead): _make_entry(file_dead),
        },
    )
    file_dead.unlink()
    removed = popunjeni_cache.prune_missing(data)
    assert removed == [str(file_dead)]
    assert str(file_alive) in data.entries
    assert str(file_dead) not in data.entries


def test_entry_records_roundtrip_to_person(tmp_path: Path) -> None:
    file = tmp_path / "x.xlsx"
    file.write_bytes(b"PK\x03\x04")
    person = Person(
        bm_number=2, function="Заменик председника", party="СПС",
        first_name="Марко", last_name="Марковић",
        jmbg="0101990710001", mesto="Уб",
    )
    entry = popunjeni_cache.CacheEntry.from_parsed(
        file,
        [((2, "Заменик председника"), person)],
        [Issue(code="X", message_sr="msg", severity="warning", file="x.xlsx")],
    )
    # Round-trip through save+load.
    popunjeni_cache.save(popunjeni_cache.CacheData(
        election_uuid="u", entries={str(file): entry},
    ))
    loaded = popunjeni_cache.load(election_uuid="u")
    loaded_entry = loaded.entries[str(file)]
    records = loaded_entry.to_records_tuples()
    issues = loaded_entry.to_issues_list()
    assert len(records) == 1
    (bm, func), p = records[0]
    assert bm == 2
    assert func == "Заменик председника"
    assert p.first_name == "Марко"
    assert p.last_name == "Марковић"
    assert p.party == "СПС"
    assert len(issues) == 1
    assert issues[0].code == "X"


def test_load_uses_caller_uuid_when_no_stored_uuid_and_caller_empty() -> None:
    """Edge case: load with empty uuid + empty stored returns an empty cache
    (no scope check possible)."""
    data = popunjeni_cache.load(election_uuid="")
    assert data.entries == {}
    assert data.election_uuid == ""


# ── latest_submission_path_for_party — §22 reply-email attachment ─────


def test_latest_submission_path_for_party_picks_newest_by_received_time(tmp_path: Path) -> None:
    old_file = tmp_path / "СНС_v1.xlsx"
    old_file.write_bytes(b"old")
    new_file = tmp_path / "СНС_v2.xlsx"
    new_file.write_bytes(b"new")

    old_entry = _make_entry(old_file)
    old_entry.party = "СНС"
    old_entry.received_time_iso = "2026-07-01T10:00:00Z"
    new_entry = _make_entry(new_file)
    new_entry.party = "СНС"
    new_entry.received_time_iso = "2026-07-02T10:00:00Z"

    data = popunjeni_cache.CacheData(
        election_uuid="uuid1",
        entries={str(old_file): old_entry, str(new_file): new_entry},
    )
    popunjeni_cache.save(data)

    result = popunjeni_cache.latest_submission_path_for_party("uuid1", "СНС")
    assert result == new_file


def test_latest_submission_path_for_party_none_when_no_submission() -> None:
    result = popunjeni_cache.latest_submission_path_for_party("uuid1", "СНС")
    assert result is None


def test_latest_submission_path_for_party_none_when_file_deleted(tmp_path: Path) -> None:
    """The cache entry can outlive the actual file (e.g. moved/deleted
    outside the app) — must not return a dangling path."""
    file = tmp_path / "СНС.xlsx"
    file.write_bytes(b"data")
    entry = _make_entry(file)
    entry.party = "СНС"
    data = popunjeni_cache.CacheData(election_uuid="uuid1", entries={str(file): entry})
    popunjeni_cache.save(data)
    file.unlink()

    result = popunjeni_cache.latest_submission_path_for_party("uuid1", "СНС")
    assert result is None
