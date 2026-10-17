"""Local SQLite session store — one sitting of collecting signatures
against one calibrated template.

Resumable on relaunch (crash safety) — `open_session`/`get_open_session`
let the GUI pick back up an in-progress sitting instead of losing
entries if the app closes unexpectedly.

Privacy: this holds real citizens' JMBG and raw ID data. Nothing here
talks to a network; `clear_session` exists specifically so the operator
can wipe a session's entries once its cumulative export has been
submitted.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from formalizator.core.models import SessionInfo, VoterEntry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    template_name TEXT NOT NULL DEFAULT '',
    copies INTEGER NOT NULL DEFAULT 1,
    printer_name TEXT NOT NULL DEFAULT '',
    custom_values_json TEXT NOT NULL DEFAULT '{}',
    export_template_name TEXT NOT NULL DEFAULT '',
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    sequence_no INTEGER NOT NULL,
    given_name TEXT NOT NULL DEFAULT '',
    surname TEXT NOT NULL DEFAULT '',
    jmbg TEXT NOT NULL DEFAULT '',
    date_of_birth TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    full_address TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    document_reg_no TEXT NOT NULL DEFAULT '',
    date_of_issue TEXT NOT NULL DEFAULT '',
    issuing_authority TEXT NOT NULL DEFAULT '',
    portrait_jpeg BLOB,
    source TEXT NOT NULL DEFAULT 'manual',
    custom_values_json TEXT NOT NULL DEFAULT '{}',
    captured_at TEXT NOT NULL
);
"""


# Columns added after the first release. `CREATE TABLE IF NOT EXISTS`
# does nothing to a table that already exists, so a database written by
# an older build needs them added explicitly.
_ADDED_COLUMNS = (
    ("sessions", "printer_name", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any missing columns.

    Deliberately checks before writing: `PRAGMA table_info` is a read,
    so an up-to-date database is untouched by opening it. (Writing on
    every connect once broke file-integrity fingerprinting in the main
    app — same mistake, worth not repeating.)"""
    for table, column, declaration in _ADDED_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            conn.commit()


def _connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def open_session(db_path: Path | str, info: SessionInfo) -> int:
    """Start a new session, returning its id."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO sessions (started_at, template_name, copies, printer_name,"
            " custom_values_json, export_template_name)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (info.started_at, info.template_name, info.copies, info.printer_name,
             json.dumps(info.custom_values, ensure_ascii=False), info.export_template_name),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def close_session(db_path: Path | str, session_id: int, closed_at: str) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE sessions SET closed_at = ? WHERE id = ?", (closed_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_open_session(db_path: Path | str) -> tuple[int, SessionInfo] | None:
    """Most recent session with no closed_at, if any — used to offer
    resuming after a restart."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE closed_at IS NULL"
            " ORDER BY id DESC LIMIT 1",
        ).fetchone()
        if row is None:
            return None
        info = SessionInfo(
            template_name=row["template_name"], copies=row["copies"],
            printer_name=row["printer_name"],
            started_at=row["started_at"],
            custom_values=json.loads(row["custom_values_json"] or "{}"),
            export_template_name=row["export_template_name"],
        )
        return int(row["id"]), info
    finally:
        conn.close()


def add_entry(db_path: Path | str, session_id: int, entry: VoterEntry, captured_at: str) -> int:
    conn = _connect(db_path)
    try:
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM entries WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO entries (session_id, sequence_no, given_name, surname,"
            " jmbg, date_of_birth, city, full_address, document_type,"
            " document_reg_no, date_of_issue, issuing_authority, portrait_jpeg,"
            " source, custom_values_json, captured_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, next_seq, entry.given_name, entry.surname, entry.jmbg,
             entry.date_of_birth, entry.city, entry.full_address, entry.document_type,
             entry.document_reg_no, entry.date_of_issue, entry.issuing_authority,
             entry.portrait_jpeg, entry.source,
             json.dumps(entry.custom_values, ensure_ascii=False), captured_at),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_entries(db_path: Path | str, session_id: int) -> list[VoterEntry]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM entries WHERE session_id = ? ORDER BY sequence_no",
            (session_id,),
        ).fetchall()
        return [
            VoterEntry(
                given_name=r["given_name"], surname=r["surname"], jmbg=r["jmbg"],
                date_of_birth=r["date_of_birth"], city=r["city"],
                full_address=r["full_address"], document_type=r["document_type"],
                document_reg_no=r["document_reg_no"],
                date_of_issue=r["date_of_issue"], issuing_authority=r["issuing_authority"],
                portrait_jpeg=r["portrait_jpeg"], source=r["source"],
                custom_values=json.loads(r["custom_values_json"] or "{}"),
            )
            for r in rows
        ]
    finally:
        conn.close()


def clear_session(db_path: Path | str, session_id: int) -> None:
    """Delete a session's entries (and the session row itself) — an
    explicit operator action, given this is real citizens' JMBG/ID data."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM entries WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()
