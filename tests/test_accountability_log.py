"""Tests for the accountability log generator.

The director's request was two-part: timestamped multi-submission
storage (covered by test_phase2 + test_popunjeni_io) and the audit
document. These tests pin the audit document's shape:

- Combined output is always produced.
- One per-party output per party that has either a submission or a
  manual edit.
- Submissions appear with their received_time, file name, source,
  and operator.
- Manual edits from corrections.log appear with before/after.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from docx import Document

from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
)
from biracki_odbor.config.oik import Chairman, Municipality, OikConstants
from biracki_odbor.core.accountability_log import generate_accountability_log
from biracki_odbor.core.models import Person, PollingStation
from biracki_odbor.core import popunjeni_cache as cache_mod


def _docx_text(path: Path) -> str:
    """Flatten every paragraph + table cell to a single string for
    `'foo' in text` assertions. python-docx doesn't have a built-in
    'read all text'; this is the minimal equivalent."""
    doc = Document(path)
    parts: list[str] = []
    for para in doc.paragraphs:
        parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def _make_election(uuid: str = "audit-test-uuid") -> ElectionConfig:
    return ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="X",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "A", "СПС": "B"},
        election_uuid=uuid,
    )


def _make_oik() -> OikConstants:
    return OikConstants(
        municipality=Municipality(
            name="Уб", name_genitive="Уба", name_locative="Убу",
            full_committee_name="ОПШТИНСКА ИЗБОРНА КОМИСИЈА ОПШТИНЕ УБ",
        ),
        chairman=Chairman(title="ПРЕДСЕДНИК", name="Никола Јовановић"),
        polling_stations=[
            PollingStation(bm_number=1, name="БМ 1", address="A", full_name="БМ 1"),
        ],
        lock_password="x",
    )


def _seed_cache(tmp_path: Path) -> cache_mod.CacheData:
    """Build a CacheData with two parties — СНС having two
    submissions (one Outlook, one manual file-picker) and СПС having
    one. Audit doc should show three submission rows total, with the
    latest per party marked as used.
    """
    sns_v1 = tmp_path / "popunjeni" / "СНС__2026-05-01T10-00-00Z.xlsx"
    sns_v2 = tmp_path / "popunjeni" / "СНС__2026-05-15T11-30-00Z.xlsx"
    sps = tmp_path / "popunjeni" / "СПС__2026-05-10T09-00-00Z.xlsx"
    # Files need to exist for the cache_mod hit() check, but the audit
    # doc generator never reads them — it only reads the metadata.
    for f in (sns_v1, sns_v2, sps):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"PK\x03\x04")
    cache = cache_mod.CacheData(election_uuid="audit-test-uuid")
    cache.entries[str(sns_v1)] = cache_mod.CacheEntry(
        mtime_ns=0, size=4,
        received_time_iso="2026-05-01T10:00:00+00:00",
        import_source="file_picker", party="СНС", imported_by="operater",
    )
    cache.entries[str(sns_v2)] = cache_mod.CacheEntry(
        mtime_ns=0, size=4,
        received_time_iso="2026-05-15T11:30:00+00:00",
        import_source="outlook", party="СНС", imported_by="operater",
    )
    cache.entries[str(sps)] = cache_mod.CacheEntry(
        mtime_ns=0, size=4,
        received_time_iso="2026-05-10T09:00:00+00:00",
        import_source="outlook", party="СПС", imported_by="operater",
    )
    return cache


def _seed_corrections_log(path: Path) -> None:
    """Two events: one resolve_conflict (cleared a slot), one
    edit_member (corrected a phone)."""
    events = [
        {
            "timestamp": "2026-05-20T14:00:00+00:00",
            "operator": "operater",
            "event_type": "resolve_conflict",
            "conflict_id": "abc123",
            "slot_bm": 1,
            "slot_function": "Председник",
            "before": {
                "bm_number": 1, "function": "Председник", "party": "СПС",
                "first_name": "Петар", "last_name": "Петровић",
                "jmbg": "0101990774804", "mesto": "", "adresa": "",
                "telefon": "", "email": "",
            },
            "after": {
                "bm_number": 1, "function": "Председник", "party": "СПС",
                "first_name": "", "last_name": "",
                "jmbg": "", "mesto": "", "adresa": "",
                "telefon": "", "email": "",
            },
            "note": "Чисти се у корист странке 'СНС'.",
        },
        {
            "timestamp": "2026-05-21T09:15:00+00:00",
            "operator": "operater",
            "event_type": "edit_member",
            "slot_bm": 1, "slot_function": "Председник",
            "before": {
                "bm_number": 1, "function": "Председник", "party": "СНС",
                "first_name": "Душко", "last_name": "Душковић",
                "jmbg": "1212807150058", "mesto": "Уб", "adresa": "",
                "telefon": "0641111111", "email": "",
            },
            "after": {
                "bm_number": 1, "function": "Председник", "party": "СНС",
                "first_name": "Душко", "last_name": "Душковић",
                "jmbg": "1212807150058", "mesto": "Уб", "adresa": "",
                "telefon": "0642222222", "email": "",
            },
            "note": "Исправка телефона",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def test_generates_combined_and_per_party_docs(tmp_path: Path) -> None:
    """Two parties with submissions → combined doc + one per party. The
    per-party doc filename includes the party's safe-filename form."""
    cache = _seed_cache(tmp_path)
    log_path = tmp_path / "corrections.log"
    _seed_corrections_log(log_path)
    out = tmp_path / "audit"

    result = generate_accountability_log(
        persons=[],
        oik=_make_oik(),
        election=_make_election(),
        output_dir=out,
        cache_data=cache,
        corrections_log_path=log_path,
        operator="operater",
    )

    assert result.combined_path is not None
    assert result.combined_path.exists()
    assert result.combined_path.name == "Аудит траг.docx"
    assert "СНС" in result.per_party_paths
    assert "СПС" in result.per_party_paths
    for p in result.per_party_paths.values():
        assert p.exists()
        assert "Аудит траг" in p.name


def test_combined_doc_lists_every_submission(tmp_path: Path) -> None:
    """Combined doc shows ALL submissions (every version per party),
    with the latest per party marked as used."""
    cache = _seed_cache(tmp_path)
    log_path = tmp_path / "corrections.log"
    _seed_corrections_log(log_path)
    out = tmp_path / "audit"

    result = generate_accountability_log(
        persons=[], oik=_make_oik(), election=_make_election(),
        output_dir=out, cache_data=cache,
        corrections_log_path=log_path, operator="operater",
    )
    text = _docx_text(result.combined_path)
    # All three submissions appear, identified by their filenames.
    assert "СНС__2026-05-01T10-00-00Z.xlsx" in text
    assert "СНС__2026-05-15T11-30-00Z.xlsx" in text
    assert "СПС__2026-05-10T09-00-00Z.xlsx" in text
    # Both parties named.
    assert "СНС" in text
    assert "СПС" in text
    # Sources labeled in Cyrillic ("Outlook" / "Ручни увоз").
    assert "Outlook" in text
    assert "Ручни увоз" in text


def test_per_party_doc_is_scoped(tmp_path: Path) -> None:
    """The per-party СНС doc shows only СНС's submissions and edits;
    СПС shouldn't appear in it.

    This is the doc handed back to the party as proof of what we
    received from them and what we changed.
    """
    cache = _seed_cache(tmp_path)
    log_path = tmp_path / "corrections.log"
    _seed_corrections_log(log_path)
    out = tmp_path / "audit"

    result = generate_accountability_log(
        persons=[], oik=_make_oik(), election=_make_election(),
        output_dir=out, cache_data=cache,
        corrections_log_path=log_path, operator="operater",
    )

    sns_text = _docx_text(result.per_party_paths["СНС"])
    assert "СНС" in sns_text
    assert "СНС__2026-05-01T10-00-00Z.xlsx" in sns_text
    assert "СНС__2026-05-15T11-30-00Z.xlsx" in sns_text
    # СПС's submission must not appear in СНС's doc.
    assert "СПС__2026-05-10T09-00-00Z.xlsx" not in sns_text


def test_audit_doc_includes_corrections_log_events(tmp_path: Path) -> None:
    """The corrections.log events surface in the combined doc with
    operator + before/after + note rendered."""
    cache = _seed_cache(tmp_path)
    log_path = tmp_path / "corrections.log"
    _seed_corrections_log(log_path)
    out = tmp_path / "audit"

    result = generate_accountability_log(
        persons=[], oik=_make_oik(), election=_make_election(),
        output_dir=out, cache_data=cache,
        corrections_log_path=log_path, operator="operater",
    )
    text = _docx_text(result.combined_path)
    # Section heading + at least one event type label.
    # Renumbered in A5 — №2 is now načelnik appointments; manual edits
    # moved to №3.
    assert "3. Ручне измене" in text
    assert "Конфликт" in text or "Измена" in text
    # Operator name surfaces (corrections.log captures Windows username).
    assert "operater" in text
    # The phone-edit before/after telefon both appear so the diff is visible.
    assert "0641111111" in text
    assert "0642222222" in text
    # Notes from the log appear.
    assert "Исправка телефона" in text


def test_no_data_still_produces_combined_doc(tmp_path: Path) -> None:
    """Empty cache + empty log: combined doc is still written (with
    "(нема ...)" placeholders) so the OIK has a record that nothing
    was submitted/changed. No per-party docs in this case."""
    empty_cache = cache_mod.CacheData(election_uuid="audit-test-uuid")
    log_path = tmp_path / "corrections.log"
    # Don't create the log file at all — the read_log helper handles missing.
    out = tmp_path / "audit"

    result = generate_accountability_log(
        persons=[], oik=_make_oik(), election=_make_election(),
        output_dir=out, cache_data=empty_cache,
        corrections_log_path=log_path, operator="operater",
    )
    assert result.combined_path is not None
    assert result.combined_path.exists()
    assert result.per_party_paths == {}
    text = _docx_text(result.combined_path)
    assert "нема увежених пријава" in text
    assert "нема ручних измена" in text
