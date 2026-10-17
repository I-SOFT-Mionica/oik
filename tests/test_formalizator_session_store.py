"""Tests for formalizator.core.session_store."""

from __future__ import annotations

from pathlib import Path

from formalizator.core import session_store
from formalizator.core.models import SessionInfo, VoterEntry


def _info(**overrides) -> SessionInfo:
    base = dict(template_name="НПРС-3 2026")
    base.update(overrides)
    return SessionInfo(**base)


def test_open_session_returns_id(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    assert sid > 0


def test_add_and_list_entries_preserves_order(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())

    session_store.add_entry(db, sid, VoterEntry(given_name="Марко", surname="Марковић", jmbg="1" * 13), "t1")
    session_store.add_entry(db, sid, VoterEntry(given_name="Ана", surname="Анић", jmbg="2" * 13), "t2")

    entries = session_store.list_entries(db, sid)
    assert [e.given_name for e in entries] == ["Марко", "Ана"]


def test_entries_scoped_to_their_own_session(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid1 = session_store.open_session(db, _info())
    sid2 = session_store.open_session(db, _info(template_name="Друга сесија"))

    session_store.add_entry(db, sid1, VoterEntry(given_name="A"), "t1")
    session_store.add_entry(db, sid2, VoterEntry(given_name="B"), "t2")

    assert [e.given_name for e in session_store.list_entries(db, sid1)] == ["A"]
    assert [e.given_name for e in session_store.list_entries(db, sid2)] == ["B"]


def test_get_open_session_returns_most_recent_unclosed(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid1 = session_store.open_session(db, _info())
    session_store.close_session(db, sid1, "2026-01-01T00:00:00")
    sid2 = session_store.open_session(db, _info(template_name="Друга сесија"))

    result = session_store.get_open_session(db)
    assert result is not None
    found_id, info = result
    assert found_id == sid2
    assert info.template_name == "Друга сесија"


def test_get_open_session_none_when_all_closed(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    session_store.close_session(db, sid, "2026-01-01T00:00:00")
    assert session_store.get_open_session(db) is None


def test_clear_session_removes_entries_and_session(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    session_store.add_entry(db, sid, VoterEntry(given_name="A"), "t1")

    session_store.clear_session(db, sid)

    assert session_store.list_entries(db, sid) == []
    assert session_store.get_open_session(db) is None


def test_portrait_jpeg_round_trips_as_blob(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    raw = b"\xff\xd8\xff\x00fake-jpeg-bytes"
    session_store.add_entry(db, sid, VoterEntry(given_name="A", portrait_jpeg=raw, source="card"), "t1")

    entries = session_store.list_entries(db, sid)
    assert entries[0].portrait_jpeg == raw
    assert entries[0].source == "card"


def test_template_name_and_copies_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info(template_name="НПРС-3 2026", copies=3))

    result = session_store.get_open_session(db)
    assert result is not None
    found_id, info = result
    assert found_id == sid
    assert info.template_name == "НПРС-3 2026"
    assert info.copies == 3


def test_document_type_round_trips(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    session_store.add_entry(db, sid, VoterEntry(given_name="A", document_type="Пасош"), "t1")

    entries = session_store.list_entries(db, sid)
    assert entries[0].document_type == "Пасош"


def test_session_custom_values_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(
        db, _info(custom_values={"overitelj_ime": "Петар Петровић"}),
    )

    result = session_store.get_open_session(db)
    assert result is not None
    _, info = result
    assert info.custom_values == {"overitelj_ime": "Петар Петровић"}


def test_entry_custom_values_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "celik.db"
    sid = session_store.open_session(db, _info())
    session_store.add_entry(
        db, sid, VoterEntry(given_name="A", custom_values={"napomena": "нешто"}), "t1",
    )

    entries = session_store.list_entries(db, sid)
    assert entries[0].custom_values == {"napomena": "нешто"}


# ── printer_name, added after the first release ──────────────────────


def test_printer_name_round_trips_through_a_session(tmp_path: Path) -> None:
    from formalizator.core import session_store
    from formalizator.core.models import SessionInfo

    db = tmp_path / "formalizator.db"
    session_store.open_session(db, SessionInfo(template_name="t", printer_name="HP LaserJet 1020"))

    resumed = session_store.get_open_session(db)

    assert resumed is not None
    assert resumed[1].printer_name == "HP LaserJet 1020"


def test_a_database_from_an_older_build_gains_the_column(tmp_path: Path) -> None:
    """Field laptops already hold databases written before printer_name
    existed, and `CREATE TABLE IF NOT EXISTS` does nothing to a table
    that is already there. Without the migration, opening one of those
    raises on every session."""
    import sqlite3

    from formalizator.core import session_store
    from formalizator.core.models import SessionInfo

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            template_name TEXT NOT NULL DEFAULT '',
            copies INTEGER NOT NULL DEFAULT 1,
            custom_values_json TEXT NOT NULL DEFAULT '{}',
            export_template_name TEXT NOT NULL DEFAULT '',
            closed_at TEXT
        );
    """)
    conn.execute(
        "INSERT INTO sessions (started_at, template_name, copies) VALUES (?, ?, ?)",
        ("2026-09-01T10:00:00", "Стари образац", 2),
    )
    conn.commit()
    conn.close()

    resumed = session_store.get_open_session(db)

    assert resumed is not None
    assert resumed[1].template_name == "Стари образац"
    assert resumed[1].copies == 2
    assert resumed[1].printer_name == ""  # absent in the old row, not a crash

    # ...and the migrated database still accepts new sessions.
    session_store.open_session(db, SessionInfo(template_name="t", printer_name="Canon MF3010"))
    assert session_store.get_open_session(db)[1].printer_name == "Canon MF3010"
