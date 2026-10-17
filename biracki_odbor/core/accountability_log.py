"""Accountability log — per-party and combined audit document.

Generates two flavors of .docx output for the OIK's records:

1. **Combined** (`Аудит траг.docx`) — every party, every submission +
   every manual correction in one document. The reference copy that
   stays with the OIK after the election.

2. **Per-party** (`Аудит траг — <party>.docx`) — one document per
   party that submitted at least one file. Scoped to that party's
   data so it can be handed back to them as proof of which submission
   we used and what we changed.

Both flavors share the same section structure:
  - Header: election + OIK + generation timestamp + operator.
  - Source files: for each party (or just the one), the timestamped
    list of submissions with received_time + import_source + the
    operator who imported each version, and which one Phase 2 picked.
  - Manual edits: every `corrections.log` event affecting this party
    — slot (БМ + функција), event type, who, when, before → after
    diff, note.
  - Footer: signature line for the OIK chairman.

Visual style reuses [phase3_docx.py](phase3_docx.py)'s typographic
helpers so the audit doc matches решења (Times New Roman, same body
size, same heading scale). Different file naming + structure, same
"feels like an OIK document" baseline.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core import corrections as corrections_mod
from biracki_odbor.core import popunjeni_cache as cache_mod
from biracki_odbor.core.models import Person
from biracki_odbor.core.phase1_generate import _safe_filename
from biracki_odbor.core.phase3_docx import (
    BODY_PT,
    SMALL_PT,
    TITLE_PT,
    _add_para,
    _add_mixed_para,
    _set_cell_borders,
    _set_cell_margins,
    _set_run_font,
)


log = logging.getLogger(__name__)


@dataclass
class AccountabilityResult:
    files_written: list[Path] = field(default_factory=list)
    combined_path: Path | None = None
    per_party_paths: dict[str, Path] = field(default_factory=dict)


# ── Public entry point ───────────────────────────────────────────────


def generate_accountability_log(
    persons: list[Person],
    oik: OikConstants,
    election: ElectionConfig,
    output_dir: Path | str,
    *,
    cache_data: cache_mod.CacheData | None = None,
    corrections_log_path: Path | str | None = None,
    operator: str | None = None,
    spec: object = None,
) -> AccountabilityResult:
    """Write the combined audit document + one per party with submissions.

    Args:
      persons: the aggregated master list (used to derive the set of
        parties to scope per-party docs against).
      cache_data: optional pre-loaded popunjeni cache. When None, we
        load it scoped to `election.election_uuid`.
      corrections_log_path: override for the audit log path. When None,
        uses `app_paths.corrections_log_path()`.
      operator: name printed in the document header. When None, reads
        from the current Windows username (same source the audit log
        events use).

    Returns paths to every file written.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if cache_data is None:
        cache_data = cache_mod.load(election_uuid=election.election_uuid)

    if corrections_log_path is None:
        # Local import — same lazy pattern popunjeni_cache uses so this
        # module is testable without a fully-initialized app_paths.
        from biracki_odbor import app_paths
        if spec is not None:
            corrections_log_path = app_paths.corrections_log_path_for(spec)
        else:
            corrections_log_path = app_paths.corrections_log_path()

    if operator is None:
        operator = (
            os.environ.get("USERNAME") or os.environ.get("USER") or "(непознат)"
        )

    audit_events = corrections_mod.read_log(corrections_log_path)

    submissions_by_party = _group_submissions_by_party(cache_data)
    parties_with_data = sorted(set(submissions_by_party.keys()) | _parties_with_edits(audit_events))

    generated_at = datetime.now(timezone.utc)

    result = AccountabilityResult()

    workflow_label = getattr(spec, "name_sr", None)
    combined_title = (
        f"Аудит траг — {workflow_label} — комплетан"
        if workflow_label else "Аудит траг — комплетан"
    )

    # 1) Combined document
    combined_path = output_dir / "Аудит траг.docx"
    _build_document(
        combined_path,
        title=combined_title,
        scope_party=None,
        submissions_by_party=submissions_by_party,
        audit_events=audit_events,
        oik=oik, election=election,
        operator=operator,
        generated_at=generated_at,
    )
    result.combined_path = combined_path
    result.files_written.append(combined_path)

    # 2) Per-party documents (one per party with at least one
    #    submission OR at least one manual edit affecting them).
    for party in parties_with_data:
        safe = _safe_filename(party)
        path = output_dir / f"Аудит траг — {safe}.docx"
        _build_document(
            path,
            title=f"Аудит траг — {party}",
            scope_party=party,
            submissions_by_party=submissions_by_party,
            audit_events=audit_events,
            oik=oik, election=election,
            operator=operator,
            generated_at=generated_at,
        )
        result.per_party_paths[party] = path
        result.files_written.append(path)

    log.info(
        "accountability_log: wrote %d documents to %s",
        len(result.files_written), output_dir,
    )
    return result


# ── Section assembly ────────────────────────────────────────────────


def _build_document(
    out_path: Path,
    *,
    title: str,
    scope_party: str | None,
    submissions_by_party: dict[str, list[_Submission]],
    audit_events: list[dict],
    oik: OikConstants,
    election: ElectionConfig,
    operator: str,
    generated_at: datetime,
) -> None:
    """Write one accountability document.

    When `scope_party` is None, includes every party with data.
    Otherwise, scoped to that one party's submissions + the audit
    events that touched a slot whose `party` was that party.
    """
    doc = Document()
    _setup_page(doc)

    # Header — short identification block, election + OIK + when this
    # doc was generated.
    _add_para(doc, oik.municipality.full_committee_name or "ОИК",
              size_pt=BODY_PT, align=WD_ALIGN_PARAGRAPH.CENTER,
              space_after_pt=2)
    _add_para(doc, title, size_pt=TITLE_PT, bold=True,
              align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10)
    _add_mixed_para(doc, [
        ("Избори: ", True),
        (election.election.dates.date_full or "(непознато)", False),
    ], align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=2)
    _add_mixed_para(doc, [
        ("Документ генерисан: ", True),
        (generated_at.astimezone().strftime("%Y-%m-%d %H:%M"), False),
        ("  ·  оператор: ", True),
        (operator, False),
    ], align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=16)

    # Section 1 — Source files
    _add_para(doc, "1. Изворни фајлови", size_pt=BODY_PT + 2, bold=True,
              space_after_pt=6)

    parties_to_show: list[str]
    if scope_party is not None:
        parties_to_show = [scope_party] if scope_party in submissions_by_party else []
    else:
        parties_to_show = sorted(submissions_by_party.keys())

    if not parties_to_show:
        _add_para(doc, "(нема увежених пријава)", size_pt=BODY_PT,
                  space_after_pt=12)
    else:
        _write_submissions_table(doc, parties_to_show, submissions_by_party)

    # Section 2 — Načelnik appointments. Split from regular manual
    # edits per the A5 audit-trail design: the operator (and any
    # later reader) needs to know at a glance which slots were filled
    # by načelnik vs which were edited per party-side feedback.
    all_party_events = _filter_events_by_party(
        audit_events, scope_party,
        submissions_by_party=submissions_by_party,
    )
    nacelnik_events = [
        ev for ev in all_party_events
        if str(ev.get("event_type", "")) == "nacelnik_appointment"
    ]
    other_edits = [
        ev for ev in all_party_events
        if str(ev.get("event_type", "")) != "nacelnik_appointment"
    ]

    _add_para(doc, "2. Именовања од стране начелника",
              size_pt=BODY_PT + 2, bold=True, space_before_pt=10,
              space_after_pt=6)
    if not nacelnik_events:
        _add_para(doc, "(нема именовања од стране начелника)",
                  size_pt=BODY_PT, space_after_pt=10)
    else:
        _write_edits_table(doc, nacelnik_events)

    # Section 3 — Other manual edits (the rest of corrections.log).
    _add_para(doc, "3. Ручне измене (Фаза 2.5)",
              size_pt=BODY_PT + 2, bold=True, space_before_pt=10,
              space_after_pt=6)
    if not other_edits:
        _add_para(doc, "(нема ручних измена)", size_pt=BODY_PT,
                  space_after_pt=10)
    else:
        _write_edits_table(doc, other_edits)

    # Footer — signature line for the OIK chairman.
    _add_para(doc, "", size_pt=BODY_PT, space_before_pt=24)
    _add_mixed_para(doc, [
        ("Председник ОИК: ", True),
        (
            f"{oik.chairman.title or 'ПРЕДСЕДНИК'} "
            f"{oik.chairman.name or '__________________________'}",
            False,
        ),
    ], align=WD_ALIGN_PARAGRAPH.RIGHT)
    _add_para(doc, "____________________________", size_pt=BODY_PT,
              align=WD_ALIGN_PARAGRAPH.RIGHT)

    doc.save(out_path)


def _setup_page(doc) -> None:
    """A4 portrait, sensible margins matching решења."""
    section = doc.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    # Default body font baseline; per-run overrides via _set_run_font still apply.
    style = doc.styles["Normal"]
    style.font.size = Pt(BODY_PT)


# ── Submissions table ──────────────────────────────────────────────


def _write_submissions_table(
    doc, parties: list[str],
    submissions_by_party: dict[str, list[_Submission]],
) -> None:
    """Render: for each party, every known submission, with the chosen
    one (latest by received_time) marked."""
    headers = ["Странка", "Примљено", "Извор", "Фајл", "Увезао", "Коришћено"]
    rows: list[list[str]] = []
    for party in parties:
        subs = submissions_by_party.get(party, [])
        if not subs:
            rows.append([party, "—", "—", "—", "—", "—"])
            continue
        # Latest first by received_time_iso (lexical sort, same shape
        # phase2_aggregate uses).
        subs_sorted = sorted(subs, key=lambda s: s.received_time_iso or "", reverse=True)
        for idx, sub in enumerate(subs_sorted):
            chosen = "✓" if idx == 0 else "—"
            rows.append([
                party if idx == 0 else "",
                _pretty_iso(sub.received_time_iso),
                _source_label(sub.import_source),
                Path(sub.file_path).name,
                sub.imported_by or "—",
                chosen,
            ])
    _emit_table(doc, headers, rows, col_widths_cm=[3.0, 3.5, 2.2, 5.5, 2.6, 1.8])


# ── Edits table ────────────────────────────────────────────────────


def _write_edits_table(doc, events: list[dict]) -> None:
    headers = ["Време", "Оператор", "Слот", "Радња", "Пре", "После", "Напомена"]
    rows: list[list[str]] = []
    for ev in events:
        slot = ""
        bm = ev.get("slot_bm")
        func = ev.get("slot_function") or ""
        if bm is not None:
            slot = f"БМ {bm}"
            if func:
                slot += f" · {func}"
        rows.append([
            _pretty_iso(ev.get("timestamp", "")),
            str(ev.get("operator", "")),
            slot,
            _event_label(str(ev.get("event_type", ""))),
            _person_one_line(ev.get("before")),
            _person_one_line(ev.get("after")),
            str(ev.get("note", "")),
        ])
    _emit_table(doc, headers, rows,
                col_widths_cm=[2.6, 1.8, 2.6, 2.0, 3.4, 3.4, 2.8])


# ── Helpers ────────────────────────────────────────────────────────


def _emit_table(doc, headers: list[str], rows: list[list[str]],
                col_widths_cm: list[float] | None = None) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.autofit = False
    if col_widths_cm:
        for i, w in enumerate(col_widths_cm):
            for cell in table.columns[i].cells:
                cell.width = Cm(w)
    # Header
    for col, label in enumerate(headers):
        cell = table.rows[0].cells[col]
        _fill_cell(cell, label, bold=True, size_pt=SMALL_PT + 1)
        _set_cell_borders(cell, top=True, bottom=True, left=True, right=True)
        _set_cell_margins(cell, top=40, bottom=40, left=60, right=60)
    # Data rows
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            cell = table.rows[r].cells[c]
            _fill_cell(cell, val, bold=False, size_pt=SMALL_PT + 1)
            _set_cell_borders(cell, top=False, bottom=True, left=True, right=True)
            _set_cell_margins(cell, top=40, bottom=40, left=60, right=60)


def _fill_cell(cell, text: str, *, bold: bool, size_pt: int) -> None:
    # Replace the auto-created empty paragraph so we don't get a blank
    # line above our content.
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    _set_run_font(run, size_pt=size_pt, bold=bold)


# ── Data classes ──────────────────────────────────────────────────


@dataclass
class _Submission:
    party: str
    file_path: str
    received_time_iso: str
    import_source: str
    imported_by: str


def _group_submissions_by_party(
    cache_data: cache_mod.CacheData,
) -> dict[str, list[_Submission]]:
    by_party: dict[str, list[_Submission]] = {}
    for path, entry in cache_data.entries.items():
        party = entry.party or "(непознато)"
        by_party.setdefault(party, []).append(_Submission(
            party=party,
            file_path=path,
            received_time_iso=entry.received_time_iso,
            import_source=entry.import_source,
            imported_by=entry.imported_by,
        ))
    return by_party


def _parties_with_edits(events: list[dict]) -> set[str]:
    """Pull party names out of the resolve_conflict note text and the
    `before`/`after` person dicts. Used to ensure a per-party doc gets
    created for any party that had manual edits even if their
    submission file is gone."""
    parties: set[str] = set()
    for ev in events:
        for key in ("before", "after"):
            person = ev.get(key)
            if isinstance(person, dict):
                p = (person.get("party") or "").strip()
                if p:
                    parties.add(p)
    return parties


def _filter_events_by_party(
    events: list[dict],
    scope_party: str | None,
    *,
    submissions_by_party: dict[str, list[_Submission]],
) -> list[dict]:
    """When scope_party is None, return everything. Otherwise return
    only events whose before-or-after person carries that party."""
    if scope_party is None:
        return events
    out: list[dict] = []
    for ev in events:
        if _event_touches_party(ev, scope_party):
            out.append(ev)
    return out


def _event_touches_party(ev: dict, party: str) -> bool:
    for key in ("before", "after"):
        person = ev.get(key)
        if isinstance(person, dict) and (person.get("party") or "").strip() == party:
            return True
    return False


_EVENT_LABELS = {
    "resolve_conflict": "Конфликт",
    "edit_member": "Измена",
    "replace_member": "Замена",
    "remove_member": "Уклоњен",
    "add_member": "Додат",
    "nacelnik_appointment": "Именовање начелника",
}


def _event_label(event_type: str) -> str:
    return _EVENT_LABELS.get(event_type, event_type or "—")


def _source_label(import_source: str) -> str:
    return {
        "outlook": "Outlook",
        "file_picker": "Ручни увоз",
    }.get(import_source, import_source or "—")


def _pretty_iso(iso: str) -> str:
    """Format an ISO 8601 timestamp for display: '2026-05-30 14:22'.

    Returns the raw value (or "—") if parsing fails — we don't want
    the audit doc to throw on a stray edge-case timestamp.
    """
    if not iso:
        return "—"
    try:
        # Strip TZ offset variants so fromisoformat works pre-3.11.
        cleaned = re.sub(r"Z$", "+00:00", iso)
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso


def _person_one_line(person: Any) -> str:
    """Compact representation of a `Person.to_dict()` blob.

    Includes the fields most likely to change between before/after
    (name, JMBG, phone, place) so the audit doc actually shows what
    the edit changed. Empty fields are dropped. Wholly-empty blobs
    render as "(празно)" so a cleared slot is unambiguous.
    """
    if not isinstance(person, dict):
        return "—"
    first = (person.get("first_name") or "").strip()
    last = (person.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    jmbg = (person.get("jmbg") or "").strip()
    telefon = (person.get("telefon") or "").strip()
    mesto = (person.get("mesto") or "").strip()
    parts = [s for s in (name, jmbg, telefon, mesto) if s]
    return " · ".join(parts) if parts else "(празно)"
