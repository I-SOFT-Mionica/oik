"""Generate observer accreditation documents.

Three outputs per election cycle:
  1. master_posmatraci.xlsx  — all observers by BM then by org (openpyxl)
  2. posmatraci/liste/       — one DOCX per BM, grouped by org inside
  3. posmatraci/legitimacije/legitimacije.docx — ID cards per layout

All functions are pure (no AppState dependency) — they take plain data
objects so they're easy to unit-test and to call from a worker thread.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Side, Border
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Emu

from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core.observers import (
    BLOCK_DIVIDER, BLOCK_FIELD_BM, BLOCK_FIELD_ELECTION, BLOCK_FIELD_ID,
    BLOCK_FIELD_MUNICIPALITY, BLOCK_FIELD_NAME,
    BLOCK_FIELD_ORG, BLOCK_FIELD_SERIAL, BLOCK_SIGNATURE_LINE,
    BLOCK_SPACER, BLOCK_STAMP_BOX, BLOCK_STATIC_TEXT,
    LegitimacijaBlock, Observer, ObserverRegistry,)

_WD_ALIGN = {
    "left":   WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right":  WD_ALIGN_PARAGRAPH.RIGHT,
}
from biracki_odbor.config.settings import PosmatraciSettings


def _twips(n: int) -> Emu:
    return Emu(n * 914)


# ── Helpers ───────────────────────────────────────────────────────────

_MAX_FILENAME_STEM = 80  # keeps the full path well under Windows' 260-char MAX_PATH


def _safe_filename(text: str) -> str:
    """Sanitise a string for use as part of a filename.

    Length-capped: an operator/org-entered name can run long enough on
    its own to exceed Windows' MAX_PATH once combined with a real
    output directory (see core/phase1_generate.py's _safe_filename,
    which had this exact gap confirmed by direct reproduction).
    """
    cleaned = "".join(c if c.isalnum() or c in " _-" else "_" for c in text).strip()
    return cleaned[:_MAX_FILENAME_STEM]


def _resolve_token(value: str, municipality: str, election_name: str) -> str:
    return (
        value
        .replace("[municipality]", municipality)
        .replace("[election]", election_name)
    )


def _grouped_by_bm(
    observers: list[Observer],
) -> dict[str, list[Observer]]:
    """Map bm_assignment text → list of observers.

    Observers with 'Сва БМ' (case-insensitive) are duplicated into
    every group so they appear on every per-BM list.
    """
    groups: dict[str, list[Observer]] = defaultdict(list)
    mobile: list[Observer] = []
    for ob in observers:
        bm = ob.bm_assignment.strip()
        if bm.lower().startswith("сва"):
            mobile.append(ob)
        else:
            groups[bm].append(ob)
    # Inject mobile observers into every BM group.
    for bm_key in list(groups):
        groups[bm_key].extend(mobile)
    # If there are ONLY mobile observers and no BM-specific ones, put
    # them under "Сва БМ" so at least one document is produced.
    if mobile and not groups:
        groups["Сва БМ"].extend(mobile)
    return dict(groups)


# ── 1. Master list (Excel) ────────────────────────────────────────────

def generate_master_list(
    observers: list[Observer],
    out_path: Path,
) -> None:
    """Write master_posmatraci.xlsx sorted by (bm_assignment, org, last_name)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Посматрачи"

    headers = [
        "Р.бр.", "Расп. БМ", "Организација", "Презиме", "Ime",
        "ЈМБГ", "Број легитимације",
    ]
    header_fill = PatternFill("solid", fgColor="2C3E50")
    header_font = Font(bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:G1"

    sorted_obs = sorted(observers, key=lambda o: (
        o.bm_assignment.lower(), o.organization.lower(), o.last_name.lower(),
    ))

    for i, ob in enumerate(sorted_obs, 1):
        ws.append([
            i,
            ob.bm_assignment,
            ob.organization,
            ob.last_name,
            ob.first_name,
            ob.display_id,
            ob.serial_number,
        ])

    col_widths = [6, 20, 30, 20, 16, 20, 16]
    for col, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w

    wb.save(out_path)


# ── 2. Per-BM lists (DOCX) ────────────────────────────────────────────

def _set_narrow_margins(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = _twips(11906)
    section.page_height = _twips(16838)
    margin = _twips(1134)
    section.top_margin = margin
    section.right_margin = margin
    section.bottom_margin = margin
    section.left_margin = margin


def _add_bm_list_heading(doc: Document, bm_name: str, election_name: str) -> None:
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(election_name.upper())
    run.bold = True
    run.font.size = Pt(12)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = sub.add_run(f"ПОСМАТРАЧИ — {bm_name.upper()}")
    run2.bold = True
    run2.font.size = Pt(11)


def _add_org_table(
    doc: Document,
    org_name: str,
    observers: list[Observer],
    start_serial: int,
) -> None:
    org_heading = doc.add_paragraph()
    run = org_heading.add_run(org_name)
    run.bold = True
    run.font.size = Pt(10)

    headers = ["Р.бр.", "Презиме и Ime", "ЈМБГ", "Бр.лег."]
    col_widths_cm = [1.2, 6.5, 5.0, 2.5]

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    hdr_row = table.rows[0]
    for i, (h, w) in enumerate(zip(headers, col_widths_cm)):
        cell = hdr_row.cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "D0D3D4")
        shd.set(qn("w:val"), "clear")
        tcPr.append(shd)
        cell.width = Cm(w)

    for idx, ob in enumerate(observers, 1):
        row = table.add_row()
        row.cells[0].text = str(idx)
        row.cells[1].text = f"{ob.last_name} {ob.first_name}"
        row.cells[2].text = ob.display_id
        row.cells[3].text = ob.serial_number
        for cell in row.cells:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()  # spacing after table


def generate_bm_lists(
    observers: list[Observer],
    out_dir: Path,
    election_name: str = "",
) -> list[Path]:
    """Generate one DOCX per BM, grouped by org inside each doc."""
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = _grouped_by_bm(observers)
    produced: list[Path] = []

    for bm_name, bm_observers in sorted(groups.items()):
        doc = Document()
        _set_narrow_margins(doc)

        style = doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(11)

        _add_bm_list_heading(doc, bm_name, election_name)

        # Group by org within this BM
        by_org: dict[str, list[Observer]] = defaultdict(list)
        for ob in bm_observers:
            by_org[ob.organization].append(ob)

        serial = 1
        for org_name in sorted(by_org):
            _add_org_table(doc, org_name, by_org[org_name], serial)
            serial += len(by_org[org_name])

        safe_bm = _safe_filename(bm_name)[:40] or "bm"
        out_path = out_dir / f"posmatraci_{safe_bm}.docx"
        doc.save(out_path)
        produced.append(out_path)

    return produced


# ── 3. Legitimacije (DOCX) ────────────────────────────────────────────

def _render_block(
    doc: Document,
    block: LegitimacijaBlock,
    observer: Observer,
    municipality: str,
    election_name: str,
    oik: "OikConstants | None" = None,
) -> None:
    """Append one block's content to the document for a given observer."""
    align = _WD_ALIGN.get(block.alignment, WD_ALIGN_PARAGRAPH.CENTER)

    if block.block_type == BLOCK_STATIC_TEXT:
        text = _resolve_token(block.value, municipality, election_name)
        p = doc.add_paragraph(text)
        p.alignment = align
        if text.isupper() or text.upper() in ("ПОСМАТРАЧ", "POSMATRAČ"):
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(12)

    elif block.block_type == BLOCK_FIELD_NAME:
        p = doc.add_paragraph(observer.name.upper())
        p.alignment = align
        for run in p.runs:
            run.bold = True

    elif block.block_type == BLOCK_FIELD_ORG:
        p = doc.add_paragraph(observer.organization)
        p.alignment = align

    elif block.block_type == BLOCK_FIELD_ID:
        p = doc.add_paragraph(observer.display_id)
        p.alignment = align

    elif block.block_type == BLOCK_FIELD_BM:
        if observer.bm_assignment:
            p = doc.add_paragraph(observer.bm_assignment)
            p.alignment = align

    elif block.block_type == BLOCK_FIELD_SERIAL:
        if observer.serial_number:
            p = doc.add_paragraph(f"Бр. {observer.serial_number}")
            p.alignment = align

    elif block.block_type == BLOCK_FIELD_MUNICIPALITY:
        if municipality:
            p = doc.add_paragraph(municipality)
            p.alignment = align

    elif block.block_type == BLOCK_FIELD_ELECTION:
        if election_name:
            p = doc.add_paragraph(election_name)
            p.alignment = align

    elif block.block_type == BLOCK_DIVIDER:
        p = doc.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "auto")
        pBdr.append(bottom)
        pPr.append(pBdr)

    elif block.block_type == BLOCK_SPACER:
        doc.add_paragraph()

    elif block.block_type == BLOCK_STAMP_BOX:
        p = doc.add_paragraph("(М.П.)")
        p.alignment = align

    elif block.block_type == BLOCK_SIGNATURE_LINE:
        chairman = oik.chairman if oik else None
        raw_title = chairman.title if chairman else "ПРЕДСЕДНИК"
        title = raw_title + " ОИК"
        name = chairman.name if chairman else ""
        underline = "_" * max(int(len(name) * 2.5), 25)
        p1 = doc.add_paragraph(title)
        p1.alignment = align
        p2 = doc.add_paragraph(underline)
        p2.alignment = align
        if name:
            p3 = doc.add_paragraph(name)
            p3.alignment = align


def _add_page_break_between_cards(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def generate_legitimacije(
    observers: list[Observer],
    settings: PosmatraciSettings,
    municipality: str = "",
    election_name: str = "",
    out_path: Path | None = None,
    oik: "OikConstants | None" = None,
) -> Path:
    """Generate legitimacije.docx with all observer ID cards.

    Layout: settings.card_setup.cards_per_sheet() cards per sheet.
    Each card renders the operator-defined block list from
    settings.legitimacija_layout.
    """
    if out_path is None:
        raise ValueError("out_path is required")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    _set_narrow_margins(doc)

    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    cards_per_page = max(1, settings.card_setup.cards_per_sheet())
    layout = settings.legitimacija_layout

    for card_idx, observer in enumerate(observers):
        # Render all blocks for this observer
        for block in layout:
            _render_block(doc, block, observer, municipality, election_name, oik)

        # Page break logic: break after every N cards (except last card)
        is_last = card_idx == len(observers) - 1
        if not is_last:
            cards_on_page = (card_idx + 1) % cards_per_page
            if cards_on_page == 0:
                _add_page_break_between_cards(doc)
            else:
                # Separator between cards on the same page
                p = doc.add_paragraph()
                pPr = p._p.get_or_add_pPr()
                pBdr = OxmlElement("w:pBdr")
                bottom = OxmlElement("w:bottom")
                bottom.set(qn("w:val"), "single")
                bottom.set(qn("w:sz"), "12")
                bottom.set(qn("w:space"), "1")
                bottom.set(qn("w:color"), "auto")
                pBdr.append(bottom)
                pPr.append(pBdr)

    doc.save(out_path)
    return out_path


# ── Output paths helper ───────────────────────────────────────────────

def posmatraci_paths(home: Path) -> dict[str, Path]:
    """Return canonical output paths for the observer workflow."""
    base = home / "posmatraci"
    return {
        "base": base,
        "master": base / "master_posmatraci.xlsx",
        "liste_dir": base / "liste",
        "legitimacije": base / "legitimacije" / "legitimacije.docx",
    }
