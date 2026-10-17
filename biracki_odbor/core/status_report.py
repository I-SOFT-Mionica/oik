"""Dated status report — seat-fill completion snapshot for Корекције.

Generates a .docx summarizing how many seats are filled vs. still
empty, overall and per party, for one workflow (стални or проширени).
Not a legal решење — an informational snapshot an operator can print,
archive, or hand to the chairman to show progress at a point in time.

Shares the same "feels like an OIK document" visual baseline as
phase3_docx.py / accountability_log.py (dated header, OIK identity,
same table style) by reusing their helpers directly, same as
accountability_log.py already does for phase3_docx.py's.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core.accountability_log import _emit_table, _setup_page
from biracki_odbor.core.models import Person
from biracki_odbor.core.phase3_docx import BODY_PT, TITLE_PT, _add_mixed_para, _add_para
from biracki_odbor.core.workflow import WorkflowSpec


def generate_status_report(
    persons: list[Person],
    oik: OikConstants,
    election: ElectionConfig,
    out_path: Path | str,
    *,
    spec: WorkflowSpec | None = None,
    generated_at: datetime | None = None,
) -> Path:
    """Write a dated status-report .docx for one workflow: overall
    totals (total/filled/empty/polling stations) + a per-party
    filled-vs-allocated breakdown table — the same numbers
    gui.tabs.corrections._SummaryPanel shows on screen, as a
    print/archive-ready document."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now()
    workflow_label = spec.name_sr if spec is not None else "Стални састав"

    doc = Document()
    _setup_page(doc)

    _add_para(
        doc, oik.municipality.full_committee_name or "ОИК",
        size_pt=BODY_PT, align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=2,
    )
    _add_para(
        doc, f"Статус попуњености — {workflow_label}",
        size_pt=TITLE_PT, bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=10,
    )
    _add_mixed_para(doc, [
        ("Избори: ", True),
        (election.election.dates.date_full or "(непознато)", False),
    ], align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=2)
    _add_mixed_para(doc, [
        ("Документ генерисан: ", True),
        (generated_at.astimezone().strftime("%Y-%m-%d %H:%M"), False),
    ], align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=16)

    total = len(persons)
    filled = sum(1 for p in persons if p.is_filled)
    n_bm = len({p.bm_number for p in persons})
    _add_mixed_para(doc, [
        ("Укупно места: ", True), (str(total), False),
        ("   ·   Попуњено: ", True), (str(filled), False),
        ("   ·   Празно: ", True), (str(total - filled), False),
        ("   ·   Бирачких места: ", True), (str(n_bm), False),
    ], align=WD_ALIGN_PARAGRAPH.CENTER, space_after_pt=16)

    stats: dict[str, tuple[int, int]] = {}
    for p in persons:
        tot, fil = stats.get(p.party, (0, 0))
        tot += 1
        if p.is_filled:
            fil += 1
        stats[p.party] = (tot, fil)
    # Same sort as _SummaryPanel: allocated count DESC, then party name ASC.
    rows = [
        [party, str(tot), str(fil)]
        for party, (tot, fil) in sorted(stats.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]
    party_col = "Листа" if spec is not None else "Странка"
    _emit_table(doc, [party_col, "Укупно", "Попуњено"], rows, col_widths_cm=[8, 4, 4])

    doc.save(out_path)
    return out_path
