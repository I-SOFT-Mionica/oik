"""Envelopes (Коверте) — one printed envelope per polling station.

Bonus tool under Алати. The operator picks the envelope type and designs
the layout with the same block builder as observer ID cards; the result
is a Word document, one landscape page per BM, sized exactly to the
envelope, content centred vertically. Saved under the app home and copied
to the export folder like every other generated document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from biracki_odbor.core.observers import (
    BLOCK_DIVIDER, BLOCK_SPACER, BLOCK_STATIC_TEXT, LegitimacijaBlock,
)

# ── Envelope types (portrait width × height, mm) ──────────────────────

ENV_C4_POCKET = "C4_POCKET"
ENV_B5_WHITE_SL = "B5_WHITE_SL"
ENV_B6_BB_SL = "B6_BB_SL"

ENVELOPE_TYPES: dict[str, tuple[str, float, float]] = {
    ENV_C4_POCKET: ("Коверта са џепом А4", 229.0, 324.0),
    ENV_B5_WHITE_SL: ("Б5 бела СЛ", 176.0, 250.0),
    ENV_B6_BB_SL: ("Б6-ББ СЛ", 125.0, 176.0),
}

# Base font per envelope; a block's row_height multiplies it.
_BASE_PT: dict[str, float] = {ENV_C4_POCKET: 14.0, ENV_B5_WHITE_SL: 12.0, ENV_B6_BB_SL: 9.0}
_MARGIN_MM = 12.0


def envelope_size_landscape(envelope_type: str) -> tuple[float, float]:
    """(width, height) in mm as printed: long side horizontal."""
    _label, w, h = ENVELOPE_TYPES.get(envelope_type, ENVELOPE_TYPES[ENV_C4_POCKET])
    return max(w, h), min(w, h)


# ── Blocks ────────────────────────────────────────────────────────────

ENV_BM_TITLE = "ENV_BM_TITLE"          # "БИРАЧКО МЕСТО БР. 5"
ENV_BM_NAME = "ENV_BM_NAME"            # full name of the polling station
ENV_BM_ADDRESS = "ENV_BM_ADDRESS"
ENV_COMMISSION = "ENV_COMMISSION"      # "Општинска изборна комисија општине …"
ENV_ELECTION = "ENV_ELECTION"

ENVELOPE_BLOCK_TYPES: list[str] = [
    BLOCK_STATIC_TEXT, ENV_BM_TITLE, ENV_BM_NAME, ENV_BM_ADDRESS,
    ENV_COMMISSION, ENV_ELECTION, BLOCK_DIVIDER, BLOCK_SPACER,
]

ENVELOPE_BLOCK_LABELS: dict[str, str] = {
    BLOCK_STATIC_TEXT: "Слободан текст",
    ENV_BM_TITLE: "Поље: Бирачко место бр.",
    ENV_BM_NAME: "Поље: Назив бирачког места",
    ENV_BM_ADDRESS: "Поље: Адреса бирачког места",
    ENV_COMMISSION: "Поље: Изборна комисија",
    ENV_ELECTION: "Поље: Назив избора",
    BLOCK_DIVIDER: "Хоризонтална линија",
    BLOCK_SPACER: "Празан ред",
}


def default_envelope_layout() -> list[LegitimacijaBlock]:
    return [
        LegitimacijaBlock(BLOCK_STATIC_TEXT, "ИЗБОРНИ МАТЕРИЈАЛ", col_span=12, row_height=2),
        LegitimacijaBlock(BLOCK_SPACER, col_span=12),
        LegitimacijaBlock(ENV_BM_TITLE, col_span=12, row_height=3),
        LegitimacijaBlock(ENV_BM_NAME, col_span=12, row_height=2),
    ]


@dataclass
class EnvelopeSettings:
    envelope_type: str = ENV_C4_POCKET
    layout: list[LegitimacijaBlock] = field(default_factory=default_envelope_layout)

    def to_dict(self) -> dict:
        return {"envelope_type": self.envelope_type, "layout": [b.to_dict() for b in self.layout]}

    @classmethod
    def from_dict(cls, d: dict) -> "EnvelopeSettings":
        env = str(d.get("envelope_type") or ENV_C4_POCKET)
        if env not in ENVELOPE_TYPES:
            env = ENV_C4_POCKET
        raw = d.get("layout")
        layout = ([LegitimacijaBlock.from_dict(b) for b in raw if isinstance(b, dict)]
                  if isinstance(raw, list) and raw else default_envelope_layout())
        return cls(envelope_type=env, layout=layout)


@dataclass(frozen=True)
class EnvelopeContext:
    """Per-print values every envelope shares."""

    municipality: str = ""
    commission: str = ""
    election: str = ""


def block_text(block: LegitimacijaBlock, station, ctx: EnvelopeContext) -> str:
    """What `block` prints on the envelope for `station` (a PollingStation)."""
    bm = getattr(station, "bm_number", "")
    name = (getattr(station, "full_name", "") or getattr(station, "name", "")).strip()
    if block.block_type == BLOCK_STATIC_TEXT:
        return (block.value
                .replace("[bm]", str(bm))
                .replace("[bm_name]", name)
                .replace("[municipality]", ctx.municipality)
                .replace("[election]", ctx.election))
    return {
        ENV_BM_TITLE: f"БИРАЧКО МЕСТО БР. {bm}",
        ENV_BM_NAME: name,
        ENV_BM_ADDRESS: getattr(station, "address", "").strip(),
        ENV_COMMISSION: ctx.commission,
        ENV_ELECTION: ctx.election,
    }.get(block.block_type, "")


def _rows(blocks: list[LegitimacijaBlock]) -> list[list[LegitimacijaBlock]]:
    rows: list[list[LegitimacijaBlock]] = []
    cur: list[LegitimacijaBlock] = []
    used = 0
    for b in blocks:
        span = max(1, min(12, b.col_span))
        if used + span > 12 and cur:
            rows.append(cur)
            cur, used = [], 0
        cur.append(b)
        used += span
    if cur:
        rows.append(cur)
    return rows


_ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
          "right": WD_ALIGN_PARAGRAPH.RIGHT}


def _no_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tbl_pr.append(borders)


def _bottom_rule(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "8"), ("w:space", "1"), ("w:color", "auto")):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    p_pr.append(bdr)


def _render_envelope(doc, blocks, station, ctx, base_pt: float, usable_w_mm: float) -> None:
    for row in _rows(blocks):
        table = doc.add_table(rows=1, cols=len(row))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        _no_borders(table)
        for cell, blk in zip(table.rows[0].cells, row):
            cell.width = Mm(usable_w_mm * max(1, min(12, blk.col_span)) / 12)
            p = cell.paragraphs[0]
            p.alignment = _ALIGN.get(blk.alignment, WD_ALIGN_PARAGRAPH.CENTER)
            p.paragraph_format.space_after = Pt(2)
            if blk.block_type == BLOCK_DIVIDER:
                _bottom_rule(p)
                continue
            if blk.block_type == BLOCK_SPACER:
                p.add_run("").font.size = Pt(base_pt * max(1, blk.row_height))
                continue
            text = block_text(blk, station, ctx)
            run = p.add_run(text)
            run.font.size = Pt(base_pt * max(1, blk.row_height))
            run.bold = blk.block_type in (ENV_BM_TITLE, BLOCK_STATIC_TEXT) and blk.row_height > 1


def generate_envelopes(
    stations: list, settings: EnvelopeSettings, ctx: EnvelopeContext, out_path: Path,
) -> Path:
    """One landscape page per station, sized to the envelope."""
    if not stations:
        raise ValueError("no polling stations selected")
    w_mm, h_mm = envelope_size_landscape(settings.envelope_type)
    base_pt = _BASE_PT.get(settings.envelope_type, 12.0)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(base_pt)
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Mm(w_mm)
    section.page_height = Mm(h_mm)
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, side, Mm(_MARGIN_MM))
    v_align = OxmlElement("w:vAlign")
    v_align.set(qn("w:val"), "center")
    section._sectPr.append(v_align)

    usable_w = w_mm - 2 * _MARGIN_MM
    body = doc.element.body
    for p in list(body.iterchildren(qn("w:p"))):  # the template's empty paragraph
        body.remove(p)
    for i, station in enumerate(stations):
        _render_envelope(doc, settings.layout, station, ctx, base_pt, usable_w)
        if i < len(stations) - 1:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def output_filename(envelope_type: str) -> str:
    return f"Koverte_{envelope_type}.docx"
