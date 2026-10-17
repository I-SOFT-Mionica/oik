"""Phase 3: generate one Word решење per polling station.

Direct port of legacy generate_docs.js using python-docx. The on-paper
layout matches the legacy output: Times New Roman 11pt body / 16pt title,
A4 with ~2cm margins, two tables (BM-name table with borders, members
table without), page numbers in header on pages 2+ only.

Inputs:
  - persons: list of Person from Phase 2 / Phase 2.5 corrections
  - oik: OikConstants for municipality + chairman
  - election: ElectionConfig for dates, types, party_full_names
  - output_dir: where to write the .docx files

Returns a Phase3Result with file paths and ValidationReport (warnings
for parties without full-name entries, empty polling stations, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path
from typing import Callable

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from biracki_odbor.config.commission import commission_terms
from biracki_odbor.config import obrazlozenje as obrazlozenje_mod
from biracki_odbor.config.declension import (
    parse_serbian_date, place_preposition, place_to_genitive,
)
from biracki_odbor.config.election import ElectionConfig, rik_provision_articles
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core.models import (
    FUNCTIONS,
    Issue,
    Person,
    ValidationReport,
)
from biracki_odbor.core.workflow import STALNI_SPEC, WorkflowSpec
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation.reports import Codes, message


FONT = "Times New Roman"
BODY_PT = 11
TITLE_PT = 16
SMALL_PT = 8
TABLE_PT = 11
PROPOSAL_PT = 9


def _twips(n: int) -> Emu:
    """Convert OOXML twips (1/20 pt) to EMU for python-docx widths."""
    return Emu(n * 635)


# 567 twips == 1cm (567 ≈ 1440 twips/inch ÷ 2.54 cm/inch).
_TWIPS_PER_CM = 567.0

_LINE_SPACING_RULES: dict[str, tuple] = {
    "single": (WD_LINE_SPACING.SINGLE, None),
    "one_point_five": (WD_LINE_SPACING.ONE_POINT_FIVE, None),
    "double": (WD_LINE_SPACING.DOUBLE, None),
    "multiple_1_15": (WD_LINE_SPACING.MULTIPLE, 1.15),
}


def apply_document_format(doc: Document, oik: OikConstants) -> None:
    """Apply the operator-configured line spacing, paragraph spacing, and
    header/footer distance (Поставке ОИК → 3. Систем → Формат докумената)
    to `doc`'s Normal style and first section.

    Shared by every resenje generator (this module, izmene_docx,
    prestanak_docx) so the three can't drift apart — before this existed
    each one separately (and, for a while, silently never) set these;
    python-docx's blank-document template defaults to 1.15 line spacing,
    0pt/10pt paragraph spacing, and ~1.27cm header/footer distance, none
    of which matched the single-spaced, 1cm, 0pt-gap layout these решења
    are meant to use.

    The Normal style's own space_before/space_after here is a DEFAULT —
    `_add_para`/`_add_mixed_para` callers that pass an explicit
    space_before_pt/space_after_pt still override it per-paragraph (title
    blocks, headings, and the signature/broj block all do, deliberately —
    those are fixed layout matched against the official reference forms,
    not a "style" choice this setting is meant to touch).
    """
    fmt = oik.document_format
    rule, multiplier = _LINE_SPACING_RULES.get(
        fmt.line_spacing, _LINE_SPACING_RULES["single"],
    )
    style = doc.styles["Normal"]
    # Order matters: python-docx's `line_spacing` setter clears the
    # `<w:spacing>` element (rule included) when given None, so setting
    # it unconditionally AFTER line_spacing_rule silently wiped the rule
    # right back out for every non-MULTIPLE choice.
    if multiplier is not None:
        style.paragraph_format.line_spacing = multiplier
    style.paragraph_format.line_spacing_rule = rule
    style.paragraph_format.space_before = Pt(fmt.body_before_pt)
    style.paragraph_format.space_after = Pt(fmt.body_after_pt)
    section = doc.sections[0]
    section.header_distance = _twips(round(fmt.header_distance_cm * _TWIPS_PER_CM))
    section.footer_distance = _twips(round(fmt.footer_distance_cm * _TWIPS_PER_CM))


def _set_run_font(run, size_pt: int = BODY_PT, bold: bool = False) -> None:
    run.font.name = FONT
    run.font.size = Pt(size_pt)
    run.bold = bold
    # Set East-Asian / complex script font names so Word renders Cyrillic
    # consistently even when its default Asian-text font differs.
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn(attr), FONT)


def _add_run_lines(paragraph, text: str, *, size_pt: int = BODY_PT, bold: bool = False):
    """Add `text` to `paragraph`, converting embedded newlines into real
    Word line breaks instead of a single run.

    Election-list full names sometimes carry intentional multi-line
    formatting (RIK's own official layout for long coalition names,
    e.g. "СРБИЈА ПРОТИВ НАСИЉА - ... (СТРАНКА ..., НАРОДНИ\\nПОКРЕТ ...")
    — those newlines are deliberate, not incidental whitespace. A raw
    LF character inside a single docx run's text is not a Word line
    break; Word silently collapses/ignores it on render, so the
    original formatting would vanish without this. `run.add_break()`
    (default LINE break) is the correct equivalent.
    """
    run = None
    for i, line in enumerate(text.split("\n")):
        if run is not None:
            run.add_break()
        run = paragraph.add_run(line)
        _set_run_font(run, size_pt=size_pt, bold=bold)
    return run


def _add_para(
    doc_or_cell,
    text: str = "",
    *,
    bold: bool = False,
    size_pt: int = BODY_PT,
    align=None,
    space_before_pt: float | None = None,
    space_after_pt: float | None = None,
):
    p = doc_or_cell.add_paragraph()
    if align is not None:
        p.alignment = align
    if space_before_pt is not None:
        p.paragraph_format.space_before = Pt(space_before_pt)
    if space_after_pt is not None:
        p.paragraph_format.space_after = Pt(space_after_pt)
    _add_run_lines(p, text, size_pt=size_pt, bold=bold)
    return p


def _add_mixed_para(
    doc_or_cell,
    segments: list[tuple[str, bool]],
    *,
    size_pt: int = BODY_PT,
    align=None,
    space_before_pt: float | None = None,
    space_after_pt: float | None = None,
):
    p = doc_or_cell.add_paragraph()
    if align is not None:
        p.alignment = align
    if space_before_pt is not None:
        p.paragraph_format.space_before = Pt(space_before_pt)
    if space_after_pt is not None:
        p.paragraph_format.space_after = Pt(space_after_pt)
    for text, bold in segments:
        _add_run_lines(p, text, size_pt=size_pt, bold=bold)
    return p


def _add_page_number_field(paragraph) -> None:
    """Insert a { PAGE } field run into a paragraph (used in header)."""
    run = paragraph.add_run()
    _set_run_font(run, size_pt=BODY_PT)
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r = run._r
    r.append(fld_begin)
    r.append(instr)
    r.append(fld_end)


def _set_cell_borders(cell, *, top: bool, bottom: bool, left: bool, right: bool) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = tc_pr.find(qn("w:tcBorders"))
    if tc_borders is None:
        tc_borders = OxmlElement("w:tcBorders")
        tc_pr.append(tc_borders)
    for side, present in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        el = tc_borders.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            tc_borders.append(el)
        if present:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")  # 4 = 0.5pt
            el.set(qn("w:color"), "000000")
        else:
            el.set(qn("w:val"), "nil")


def _set_cell_margins(cell, *, top: int = 30, bottom: int = 30, left: int = 40, right: int = 40) -> None:
    """Cell margins in twips."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        el = tc_mar.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            tc_mar.append(el)
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class Phase3Result:
    files_written: list[Path]
    report: ValidationReport


def _proposal_text(
    party: str, election: ElectionConfig, nacelnik_full_name: str,
    *, appointed_by_nacelnik: bool = False,
) -> tuple[str, str]:
    """Return (label_line, party_name_line) for the proposal cell.

    For "Посланичке групе X" / "Посланичка група X" entries, label is
    normalized to the genitive "на предлог Посланичке групе" regardless of
    which form the user stored, and the second line is just "X". For
    non-standard fallbacks (e.g. "_default" mapping "начелника Општинске
    управе…"), label is just "на предлог" and the whole text goes on the
    second line. Empty party returns ('', '').

    `party` on a Person always reflects the RIK-allocated party even after
    a načelnik appointment (needed elsewhere for quota stats) — so a
    nacelnik-filled slot would otherwise resolve back to the ORIGINAL
    party's name here. When `appointed_by_nacelnik` is set, `party` is
    ignored so the lookup key never matches a real party, triggering
    the nacelnik fallback in `ElectionConfig.party_full_name` instead.
    """
    full, _matched = election.party_full_name(
        "" if appointed_by_nacelnik else party, nacelnik_full_name,
    )
    if not full:
        return "", ""
    for prefix in ("Посланичке групе ", "Посланичка група "):
        if full.startswith(prefix):
            return "на предлог Посланичке групе", full[len(prefix):].strip()
    return "на предлог", full


def format_broj(
    election: ElectionConfig,
    bm_number: int,
    bm_offset: int,
    spec: WorkflowSpec | None = None,
) -> str:
    """Construct the «Број» line for one resenja.

    Format: `{prefix}{separator}{start + offset}/{year}`. When the
    operator hasn't set the workflow's subbroj field, the legacy format
    `{prefix}-{bm_number}/{year}` is preserved so existing configs
    keep producing the same broj they always did.

    `bm_offset` is the BM's index in the OIK's ordered station list
    (0 for the first BM, 1 for the second, …). The municipal archive
    issues one base number per cycle and every OIK document claims a
    sub-broj sequentially, so giving each BM the next integer in
    order matches the bookkeeping convention.

    Extracted as a pure function so it can be unit-tested + reused by
    Phase 3's preview panel without spinning up python-docx.

    `spec` selects which ElectionDates field to read for the starting
    sub-broj (STALNI_SPEC → `subbroj_start`; PROSIRENI_SPEC →
    `subbroj_start_prosireni`). Defaults to STALNI_SPEC so all
    pre-Phase-D callers continue to work unchanged.
    """
    if spec is None:
        spec = STALNI_SPEC
    prefix = getattr(election.document, spec.number_prefix_field, "") or election.document.number_prefix
    year = election.election.dates.year
    # Read the workflow's own subbroj field via getattr so we don't need
    # to enumerate PROSIRENI_SPEC specifically.
    start_raw = getattr(election.election.dates, spec.subbroj_field, "").strip()
    sep = election.election.dates.subbroj_separator or "-"
    if not start_raw:
        # Legacy format — preserved exactly so old configs don't change.
        return f"Број: {prefix}-{bm_number}/{year}"
    try:
        start = int(start_raw)
    except ValueError:
        # Operator typed something non-numeric (rare; defensive). Fall
        # back to the legacy format rather than rendering a confusing
        # «013-5-30-abc12/2026».
        return f"Број: {prefix}-{bm_number}/{year}"
    return f"Број: {prefix}{sep}{start + bm_offset}/{year}"


def _build_document(
    bm_number: int,
    bm_offset: int,
    bm_name: str,
    members: list[Person],
    oik: OikConstants,
    election: ElectionConfig,
    spec: WorkflowSpec | None = None,
) -> Document:
    if spec is None:
        spec = STALNI_SPEC
    mun = oik.municipality
    chairman = oik.chairman
    terms = commission_terms(mun)
    expanded = election.election.expanded_types(mun.name, terms.local_assembly)
    types_joined = " и ".join(t_lower for t_lower, _ in expanded)

    doc = Document()

    # A4 page; ~2cm side/top margins, ~3cm bottom for stamp/signature room.
    section = doc.sections[0]
    section.page_width = _twips(11906)
    section.page_height = _twips(16838)
    section.top_margin = _twips(1134)
    section.right_margin = _twips(1134)
    section.bottom_margin = _twips(1701)
    section.left_margin = _twips(1134)
    section.different_first_page_header_footer = True

    # Header on pages 2+: centered page number; first-page header stays empty.
    header_para = section.header.paragraphs[0]
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number_field(header_para)
    # Ensure a first-page header element exists (empty)
    _ = section.first_page_header.paragraphs[0]

    # Default style font (also sets table/empty paragraph baseline)
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(BODY_PT)
    apply_document_format(doc, oik)
    fmt = oik.document_format
    style_rPr = style.element.get_or_add_rPr()
    rFonts = style_rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        style_rPr.append(rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rFonts.set(qn(attr), FONT)

    # ── Legal basis ── read the workflow's own field (stalni →
    # document.legal_basis; prosireni → document.legal_basis_prosireni
    # once Phase E adds that field). Fallback to legal_basis so the
    # prosireni path works even before the separate field exists.
    legal_basis_text = getattr(
        election.document, spec.resenja_legal_basis_key,
        election.document.legal_basis,
    ) or election.document.legal_basis
    _add_para(
        doc, legal_basis_text,
        align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after_pt=10,
    )

    # ── Session line ──
    dates = election.election.dates
    s_date = getattr(dates, spec.session_date_field, "").strip() or dates.session_date
    s_num = (getattr(dates, spec.session_number_field, "").strip() or dates.session_number).strip()
    session_phrase = (
        f"на {s_num}. седници одржаној {s_date}"
        if s_num
        else f"на седници одржаној {s_date}"
    )
    _add_para(
        doc,
        f"{terms.preamble_subject}, "
        f"{session_phrase}, донела је",
        align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after_pt=10,
    )

    # ── РЕШЕЊЕ ── (Title style: 16pt bold + letter-spacing 80 = 4pt apart).
    # Reference encodes the "spaced" look via run-level <w:spacing w:val="80"/>
    # rather than inserting actual spaces. Word renders "РЕШЕЊЕ" with the
    # individual glyphs spread out by 4pt each.
    p_resenje = _add_para(
        doc, "РЕШЕЊЕ",
        bold=True, size_pt=TITLE_PT,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_before_pt=12, space_after_pt=12,
    )
    for run in p_resenje.runs:
        rPr = run._element.get_or_add_rPr()
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), "80")
        rPr.append(spacing)

    _add_para(
        doc,
        spec.resenja_title_subtitle,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_before_pt=fmt.title_before_pt, space_after_pt=fmt.title_after_pt,
    )
    _add_para(
        doc, spec.resenja_composition_mark,
        bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
        space_before_pt=fmt.title_before_pt, space_after_pt=fmt.title_after_pt,
    )

    # Election type line — one paragraph per type, matching the official
    # RIK reference form exactly (confirmed against the reference image:
    # "ЗА СПРОВОЂЕЊЕ ИЗБОРА ЗА НАРОДНЕ ПОСЛАНИКЕ НАРОДНЕ СКУПШТИНЕ" is a
    # single line, not two). Previously split into two separate
    # paragraphs — a smaller non-bold prefix line glued (space_after=0)
    # to a bold type-name line — which was wrong; merged via
    # _add_mixed_para the same way the РАСПИСАНИХ ЗА / ЗА БИРАЧКО МЕСТО
    # lines just below already mix non-bold + bold text in one line.
    multi = len(expanded) > 1
    for i, (_, t_upper) in enumerate(expanded):
        if t_upper.startswith("ИЗБОРА ЗА "):
            suffix = t_upper[len("ИЗБОРА ЗА "):]
            if i == 0:
                # "ЗА ИЗБОРА ЗА" (missing СПРОВОЂЕЊЕ) isn't grammatical
                # Serbian — the official RIK form reads "ЗА СПРОВОЂЕЊЕ
                # ИЗБОРА ЗА …" even for a single election type; the multi
                # branch already had this right ("...КООРДИНИРАНО
                # СПРОВОЂЕЊЕ...").
                prefix_line = (
                    "ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ ИЗБОРА ЗА" if multi
                    else "ЗА СПРОВОЂЕЊЕ ИЗБОРА ЗА"
                )
            else:
                prefix_line = "И ИЗБОРА ЗА"
        else:
            suffix = t_upper
            if i == 0:
                prefix_line = "ЗА КООРДИНИРАНО СПРОВОЂЕЊЕ" if multi else "ЗА"
            else:
                prefix_line = "И"
        _add_mixed_para(
            doc,
            [(f"{prefix_line} ", False), (suffix, True)],
            align=WD_ALIGN_PARAGRAPH.CENTER,
            space_before_pt=fmt.title_before_pt, space_after_pt=fmt.title_after_pt,
        )

    _add_mixed_para(
        doc,
        [
            ("РАСПИСАНИХ ЗА ", False),
            (f"{election.election.dates.date_full.upper()},", True),
        ],
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_before_pt=fmt.title_before_pt, space_after_pt=fmt.title_after_pt,
    )

    _add_mixed_para(
        doc,
        [
            ("ЗА БИРАЧКО МЕСТО ", False),
            (f"БРОЈ {bm_number}.", True),
            (f" {terms.in_unit.upper()}", False),
        ],
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_before_pt=fmt.title_before_pt, space_after_pt=fmt.title_after_pt,
    )

    # ── BM name "signature line" table (14 cm wide, centered). Only the
    # middle horizontal line is visible; BM name sits ON that line, label
    # "(назив и адреса …)" hangs just below.
    BM_TABLE_TWIPS = 7938  # = 14 cm; matches reference's tblW + tblGrid
    bm_table = doc.add_table(rows=2, cols=1)
    bm_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    bm_table.columns[0].width = _twips(BM_TABLE_TWIPS)

    cell_top = bm_table.rows[0].cells[0]
    cell_top.width = _twips(BM_TABLE_TWIPS)
    _set_cell_borders(cell_top, top=False, bottom=True, left=False, right=False)
    _set_cell_margins(cell_top, top=80, bottom=10, left=80, right=80)
    cell_top.vertical_alignment = WD_ALIGN_VERTICAL.BOTTOM
    top_para = cell_top.paragraphs[0]
    top_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    top_para.paragraph_format.space_before = Pt(0)
    top_para.paragraph_format.space_after = Pt(0)
    run = top_para.add_run(bm_name)
    _set_run_font(run, size_pt=BODY_PT, bold=True)

    cell_bot = bm_table.rows[1].cells[0]
    cell_bot.width = _twips(BM_TABLE_TWIPS)
    _set_cell_borders(cell_bot, top=False, bottom=False, left=False, right=False)
    _set_cell_margins(cell_bot, top=10, bottom=20, left=80, right=80)
    cell_bot.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    bot_para = cell_bot.paragraphs[0]
    bot_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    bot_para.paragraph_format.space_before = Pt(0)
    bot_para.paragraph_format.space_after = Pt(0)
    run = bot_para.add_run("(назив и адреса бирачког места)")
    _set_run_font(run, size_pt=SMALL_PT)

    # ── Point 1 — selective bold per reference: only "бирачко место број N."
    # is emphasized; the surrounding narrative is in regular weight.
    _add_mixed_para(
        doc,
        [
            (
                f"1. У бирачки одбор у {spec.resenja_item_i_intro} за координирано спровођење "
                f"{types_joined} расписаних за {election.election.dates.date_full}, за ",
                False,
            ),
            (f"бирачко место број {bm_number}.", True),
            (f" {terms.in_unit}  именују се:", False),
        ],
        align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    )

    # ── Members table (5 cols, no borders) ──
    # Column widths chosen so total equals the page text width (9638 twips =
    # A4 width 11906 − 2×1134 margins). Previously the columns summed to
    # 10207 twips, pushing the right edge past the body-text margin by ~1cm.
    #
    # Stalni's schema is fixed (3 groups of Председник/Члан 1/Члан 2, each
    # with a Заменик row) — known in advance regardless of data. Prosireni
    # has no fixed schema: the number of participating entities (each one
    # a "Члан [N]"/"Заменик члана [N]" pair) varies per election, so the
    # groups are derived from the actual slot indices present in `members`
    # instead of a hardcoded list — using the stalni-only labels here for
    # prosireni previously meant `member_by_func.get(...)` never matched
    # anything and every prosireni решење rendered a blank table.
    if spec.slug == "prosireni":
        from biracki_odbor.core.prosireni_allocation import (
            MEMBER_LABEL, SUBSTITUTE_LABEL, parse_slot_function, slot_function,
        )
        slot_indices: set[int] = set()
        for p in members:
            parsed = parse_slot_function(p.function)
            if parsed is not None:
                slot_indices.add(parsed[0])
        # The printed number IS slot_idx — a list's permanent ballot-order
        # position (see prosireni_allocation.canonical_slots) — never a
        # fresh 1..N recount of however many slots happen to be filled.
        # Field clarification: if list 5 never submits a member, "5.
        # члан" simply doesn't appear in the decision at all; list 6's
        # member stays "6. члан", not renumbered down to "5." to fill
        # the gap. An earlier version used enumerate()'s position here,
        # which silently compacted the numbering whenever any slot in
        # between had no submission — misattributing a later list's seat
        # to an earlier list's ballot number in the actual legal document.
        func_groups = [
            (f"{slot_idx})", [
                (slot_function(MEMBER_LABEL, slot_idx), MEMBER_LABEL),
                (slot_function(SUBSTITUTE_LABEL, slot_idx), SUBSTITUTE_LABEL),
            ])
            for slot_idx in sorted(slot_indices)
        ]
    else:
        func_groups = [
            ("1)", [("Председник", "Председник"), ("Заменик председника", "Заменик председника")]),
            ("2)", [("Члан 1", "Члан 1"), ("Заменик члана 1", "Заменик члана 1")]),
            ("3)", [("Члан 2", "Члан 2"), ("Заменик члана 2", "Заменик члана 2")]),
        ]
    # Col 0 at 324 twips (sum 9638) matches the maintainer's reference
    # .docx exactly for stalni, which only ever has single-digit "1)"/
    # "2)"/"3)" -- kept as-is there. Prosireni's slot number is the
    # list's ballot-order position and routinely reaches two digits; at
    # TABLE_PT the glyphs for e.g. "12)" don't fit in 324 twips of usable
    # width (minus the 80-twip L/R cell margin) and wrap onto two lines.
    # Widened by 226 twips there, taken from col 4 (proposal text, which
    # already wraps onto multiple lines by design) to keep the row sum
    # at 9638.
    if spec.slug == "prosireni":
        col_widths_twips = (550, 1736, 2193, 1417, 3742)  # sum = 9638
    else:
        col_widths_twips = (324, 1736, 2193, 1417, 3968)  # sum = 9638; from reference
    member_table = doc.add_table(rows=max(len(func_groups), 1) * 2, cols=5)
    member_table.autofit = False
    for col_idx, width in enumerate(col_widths_twips):
        member_table.columns[col_idx].width = _twips(width)

    member_by_func = {p.function: p for p in members}
    row_idx = 0
    for group_label, funcs in func_groups:
        for i, (func_name, display_label) in enumerate(funcs):
            row = member_table.rows[row_idx]
            label_text = group_label if i == 0 else ""
            person = member_by_func.get(func_name)
            name = person.name if person else ""
            mesto = person.mesto if person else ""
            party = person.party if person else ""
            mesto_text = (
                f"{place_preposition(mesto)} {place_to_genitive(mesto)}"
                if mesto else ""
            )
            proposal_label, proposal_party = (
                _proposal_text(
                    party, election, oik.nacelnik_proposal_name,
                    appointed_by_nacelnik=person.appointed_by_nacelnik,
                ) if person else ("", "")
            )

            # vAlign policy from reference: label rows (i==0) have all cells
            # vertically centered. Replacement rows (i==1): col 0 stays
            # centered, cols 1-3 default to top, col 4 stays centered.
            label_row = (i == 0)

            simple_cells = [
                (0, label_text, True),   # col 0: always center
                (1, display_label.lower(), label_row),
                (2, name, label_row),
                (3, mesto_text, label_row),
            ]
            for col_idx, text, vcenter in simple_cells:
                cell = row.cells[col_idx]
                cell.width = _twips(col_widths_twips[col_idx])
                _set_cell_margins(cell, top=30, bottom=30, left=40, right=40)
                if vcenter:
                    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                par = cell.paragraphs[0]
                # Reference: every cell paragraph has spacing.after=0; without
                # this our rows inherit Normal's 10pt after-spacing and the
                # table grows visibly taller.
                par.paragraph_format.space_after = Pt(0)
                run = par.add_run(text)
                _set_run_font(run, size_pt=TABLE_PT)

            # Col 5: two-line proposal — label (small) + party name at the
            # same size as the person's name. Skipped (cell stays empty) when
            # there's no party. Always vertically centered.
            cell = row.cells[4]
            cell.width = _twips(col_widths_twips[4])
            _set_cell_margins(cell, top=30, bottom=30, left=40, right=40)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            par = cell.paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            if proposal_label:
                run1 = par.add_run(proposal_label)
                _set_run_font(run1, size_pt=PROPOSAL_PT)
                if proposal_party:
                    run1.add_break()
                    _add_run_lines(par, proposal_party, size_pt=TABLE_PT)
            row_idx += 1

    # ── RIK transitional provision (art. 35/179/98) ──
    rik_prov = election.rik_provision
    if rik_prov.active:
        rik_entry = rik_prov.members.get(bm_number)
        if rik_entry and not rik_entry.member.is_empty:
            articles = rik_provision_articles(election.election.types)
            intro = (
                f"{articles}, Републичка изборна комисија именовала је"
                " у бирачки одбор:"
            )
            _add_para(doc, intro,
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            m = rik_entry.member
            m_line = f"члан: {m.name}" + (f", {m.address}" if m.address else "")
            _add_para(doc, m_line,
                      align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            d = rik_entry.deputy
            if not d.is_empty:
                d_line = f"заменик члана: {d.name}" + (f", {d.address}" if d.address else "")
                _add_para(doc, d_line,
                          align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    # ── Point 2 ──
    _add_mixed_para(
        doc,
        [
            ("2", True),
            (". Ово решење објављује се на веб-презентацији Републичке изборне комисије.", False),
        ],
        align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    )

    # ── Point 3 ──
    _add_mixed_para(
        doc,
        [
            ("3.", True),
            (" Ово решење ступа на снагу даном објављивања.", False),
        ],
        align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    )

    # ── Образложење (forced onto page 2 via page-break-before).
    # Run-level letter-spacing 80 (4pt apart) renders the glyphs visually
    # spaced out, the same mechanism we use for "РЕШЕЊЕ".
    obr_heading = _add_para(
        doc, "Образложење",
        bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after_pt=10,
    )
    obr_heading.paragraph_format.page_break_before = True
    for run in obr_heading.runs:
        rPr = run._element.get_or_add_rPr()
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), "80")
        rPr.append(spacing)

    # Obrazloženje text comes from the user-editable JSON template
    # (`<HOME>/obrazlozenje.json`, seeded on first run). Placeholders
    # including {days_before_proposal} and {days_before_appointment} are
    # computed here from the election cutoff dates set in the form so the
    # rok-za-imenovanje paragraph reflects the OIK's actual configured deadlines.
    _days_proposal = 15    # legal default (Чл. 34 ст. 2)
    _days_appoint = 10     # legal default (Чл. 34 ст. 1)
    _parsed = parse_serbian_date(election.election.dates.date_full)
    if _parsed is not None:
        _edate = _date(*_parsed)
        # -1: election day itself isn't counted as one of the "days
        # before" -- e.g. a cutoff of Oct 9 for an Oct 25 election is
        # "15 dana pre izbora", not 16 (raw calendar-day subtraction).
        if election.election.dates.cutoff_stalni:
            try:
                _days_proposal = (
                    _edate - _date.fromisoformat(election.election.dates.cutoff_stalni)
                ).days - 1
            except ValueError:
                pass
        if election.election.dates.cutoff_prosireni:
            try:
                _days_appoint = (
                    _edate - _date.fromisoformat(election.election.dates.cutoff_prosireni)
                ).days - 1
            except ValueError:
                pass
    from biracki_odbor import app_paths
    obrazlozenje = obrazlozenje_mod.render(
        rik_decision=election.election.rik_decision,
        municipality=mun.name,
        days_before_proposal=_days_proposal,
        days_before_appointment=_days_appoint,
        municipality_website=mun.website,
        local_elections="local" in (election.election.types or []),
        path=app_paths.obrazlozenje_path_for(spec),
        commission=terms,
    )
    # УПУТСТВО О ПРАВНОМ СРЕДСТВУ is the last paragraph in the
    # obrazlozenje.json/obrazlozenje_prosireni.json template (id
    # "uputstvo-pravno-sredstvo") -- it used to be hardcoded here,
    # outside the editable template, with no way to adjust its wording
    # (e.g. for a local election, where the eligible complainants and
    # receiving commission differ) without a code change. See
    # config/obrazlozenje.py's `_ensure_legal_remedy_paragraph()` for
    # the one-time migration that adds it to an existing operator's
    # template who saved their file before this change.
    for segments in obrazlozenje:
        _add_mixed_para(
            doc, segments,
            align=WD_ALIGN_PARAGRAPH.JUSTIFY,
        )

    # Document number / place / date — default alignment per reference
    # (no `<w:jc>` element on either paragraph).
    _add_para(
        doc,
        format_broj(election, bm_number, bm_offset, spec),
        space_after_pt=2,
    )
    _add_para(
        doc,
        f"У {mun.name_locative}, {getattr(election.election.dates, spec.session_date_field, '').strip() or election.election.dates.session_date}",
        space_after_pt=6,
    )

    # Committee signature
    name = mun.full_committee_name.strip()
    lines = [ln.strip() for ln in name.splitlines() if ln.strip()] if "\n" in name else []
    if not lines:
        import re
        m = re.match(r"^(ОПШТИНСКА ИЗБОРНА КОМИСИЈА)\s+(.+)$", name)
        if m:
            lines = [m.group(1), m.group(2)]
        else:
            lines = [name]
    for i, line in enumerate(lines):
        _add_para(
            doc, line, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
            space_after_pt=10 if i == len(lines) - 1 else None,
        )

    # ── Continuous section break with 3 columns for the signature block ──
    # Reference uses this so the ПРЕДСЕДНИК / signature-line / chairman-name
    # group renders in the first of three columns (so the visible block sits
    # in the left third of the page, with whitespace on the right).
    sig_section = doc.add_section(WD_SECTION_START.CONTINUOUS)
    sig_sectPr = sig_section._sectPr
    cols_el = sig_sectPr.find(qn("w:cols"))
    if cols_el is None:
        cols_el = OxmlElement("w:cols")
        sig_sectPr.append(cols_el)
    cols_el.set(qn("w:num"), "3")
    cols_el.set(qn("w:space"), "720")

    # Two column breaks fill columns 1 and 2 with whitespace so the
    # signature block (ПРЕДСЕДНИК + line + chairman name) lands in column 3
    # — the right third of the page, matching the reference layout.
    break_para = doc.add_paragraph()
    br_run = break_para.add_run()
    _set_run_font(br_run, size_pt=BODY_PT)
    for _ in range(2):
        br = OxmlElement("w:br")
        br.set(qn("w:type"), "column")
        br_run._r.append(br)

    # Delegated-signer authorization — ONE shared setting used by every
    # resenje type (see config.election.DocumentInfo), not izmena-only:
    # when the chairman has delegated signing authority for the period,
    # the delegate signs the original appointment decision too, not just
    # amendments. Same selection rule as core.izmene_docx.
    doc_info = election.document
    if doc_info.use_authorization and doc_info.authorized_name:
        signer_name = doc_info.authorized_name
        signer_role = doc_info.authorized_role or "овлашћено лице"
    else:
        signer_name = chairman.name
        signer_role = chairman.title

    if signer_role:
        _add_para(
            doc, signer_role, align=WD_ALIGN_PARAGRAPH.CENTER,
        )

    # Signature line — empty 1×1 table, only a thin bottom border visible,
    # ~4.8 cm wide, centered. This is where the signer physically signs.
    sig_tbl = doc.add_table(rows=1, cols=1)
    sig_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    sig_tbl.columns[0].width = _twips(2722)
    sig_cell = sig_tbl.rows[0].cells[0]
    sig_cell.width = _twips(2722)
    _set_cell_borders(sig_cell, top=False, bottom=True, left=False, right=False)
    sig_para = sig_cell.paragraphs[0]
    sig_para.paragraph_format.space_before = Pt(0)
    sig_para.paragraph_format.space_after = Pt(0)

    if signer_name:
        _add_para(doc, signer_name, align=WD_ALIGN_PARAGRAPH.CENTER)

    return doc


def _build_and_save_one_bm(
    bm_num: int,
    bm_offset: int,
    members: list[Person],
    oik: OikConstants,
    election: ElectionConfig,
    output_dir: Path,
    spec: WorkflowSpec | None = None,
) -> tuple[Path, list[Issue]]:
    """Module-level worker: build + save one BM's решење.

    Returns (written_path, issues). Issues currently only includes EMPTY_BM
    when the slot has no filled members. Must remain picklable — no Qt
    imports, no module-state mutation.
    """
    if spec is None:
        spec = STALNI_SPEC
    issues: list[Issue] = []
    if not members:
        issues.append(Issue(
            code=Codes.EMPTY_BM,
            message_sr=message(Codes.EMPTY_BM, row=bm_num),
            severity="warning", row=bm_num,
        ))

    station = oik.station_by_bm(bm_num)
    bm_name = (
        station.full_name or station.name if station else f"БМ бр. {bm_num}"
    )

    doc = _build_document(bm_num, bm_offset, bm_name, members, oik, election, spec)
    # Filename slug comes from the spec so stalni + prosireni files don't
    # clobber each other in the same output directory.
    slug = spec.slug.upper()
    filename = f"БМ_{bm_num:02d}_{slug}.docx"
    path = output_dir / filename
    doc.save(path)
    return path, issues


@log_timing("generate_documents")
def generate_documents(
    persons: list[Person],
    oik: OikConstants,
    election: ElectionConfig,
    output_dir: Path | str,
    progress: Callable[[int, int, int], None] | None = None,
    max_workers: int | None = None,
    spec: WorkflowSpec | None = None,
) -> Phase3Result:
    """Write one .docx per BM. Returns paths + report (party-name warnings).

    `spec` selects the workflow (STALNI_SPEC or PROSIRENI_SPEC). When None
    defaults to STALNI_SPEC so all pre-Phase-D callers keep working.

    Uses a ProcessPoolExecutor when `max_workers > 1` (default min(4, cpu_count));
    pass `max_workers=1` for an in-process sequential path that avoids
    subprocess overhead — useful in tests and on single-core machines.
    """
    import logging
    import os
    log = logging.getLogger(__name__)
    if spec is None:
        spec = STALNI_SPEC

    report = ValidationReport()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Group filled members by BM.
    by_bm: dict[int, list[Person]] = {}
    for p in persons:
        if p.is_filled:
            by_bm.setdefault(p.bm_number, []).append(p)

    # Party-name warnings (one per unmatched party) — main-thread, deterministic.
    unmatched: set[str] = set()
    for p in persons:
        if p.is_filled and p.party:
            _full, matched = election.party_full_name(p.party, oik.nacelnik_full_name)
            if not matched:
                unmatched.add(p.party)
    for party in sorted(unmatched):
        report.add(Issue(
            code=Codes.PARTY_UNMATCHED,
            message_sr=message(Codes.PARTY_UNMATCHED, detail=party),
            severity="warning", detail=party,
        ))

    bm_numbers = sorted({p.bm_number for p in persons})
    total = len(bm_numbers)
    if max_workers is None:
        max_workers = min(4, os.cpu_count() or 2)
    log.info(
        "generate_documents: %d BMs to produce (max_workers=%d)",
        total, max_workers,
    )

    # `bm_offset` = the BM's index in the sorted bm_numbers list — used
    # by `format_broj` to build `{prefix}{sep}{start + offset}/{year}`
    # when the operator has configured a starting sub-broj.
    tasks = [
        (bm_num, offset, by_bm.get(bm_num, []), oik, election, out, spec)
        for offset, bm_num in enumerate(bm_numbers)
    ]

    files_written: list[Path] = []

    # Threshold: process pool startup on Windows is ~300 ms; each .docx is
    # ~30-100 ms. Below ~8 BMs the pool is a net loss, so we run sequentially.
    if max_workers <= 1 or total < 8:
        # Sequential in-process — used in tests and as a safe fallback.
        for idx, args in enumerate(tasks, start=1):
            bm_num = args[0]
            path, issues = _build_and_save_one_bm(*args)
            files_written.append(path)
            for issue in issues:
                report.add(issue)
            log.debug("BM %d: wrote %s", bm_num, path)
            if progress:
                progress(bm_num, idx, total)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            future_to_bm = {
                pool.submit(_build_and_save_one_bm, *args): args[0]
                for args in tasks
            }
            for idx, fut in enumerate(as_completed(future_to_bm), start=1):
                bm_num = future_to_bm[fut]
                path, issues = fut.result()
                files_written.append(path)
                for issue in issues:
                    report.add(issue)
                log.debug("BM %d: wrote %s", bm_num, path)
                if progress:
                    progress(bm_num, idx, total)

    # Files complete in non-deterministic order under as_completed — sort so
    # callers get a stable list (matches sequential path's order).
    files_written.sort()
    log.info("generate_documents: %d files written", len(files_written))
    return Phase3Result(files_written, report)
