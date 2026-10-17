"""Structured diff between two .docx files.

Usage: python tools/compare_docx.py REF.docx OURS.docx

Walks each file as a flat list of "facts" — dotted paths keyed on body
position (e.g. `body.P[5].run[2].bold`, `body.TBL[1].cell[0,2].vAlign`) —
and prints every key where the values disagree. Repeatable: identical
inputs → identical output. Designed for iterating on the Phase 3 решење
generator against a maintainer-supplied reference document.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn


def _direct_runs(p_element):
    """Yield <w:r> children that sit directly under the paragraph (skip
    runs nested inside <w:smartTag>, <w:hyperlink>, etc — they don't
    affect our layout decisions)."""
    for r in p_element:
        if r.tag == qn("w:r"):
            yield r


def _tw(twips_str: str | None) -> int | None:
    if twips_str is None:
        return None
    try:
        return int(twips_str)
    except ValueError:
        return None


def _emu_to_twips(emu) -> int | None:
    if emu is None:
        return None
    return int(emu / 635)


def _truncate(s: str, n: int = 60) -> str:
    s = (s or "").replace("\n", "⏎").replace("\t", "⇥")
    return s if len(s) <= n else s[: n - 1] + "…"


def collect_facts(doc: Document) -> dict[str, Any]:
    facts: dict[str, Any] = {}

    # ── Section properties ──
    for si, sec in enumerate(doc.sections):
        prefix = f"section[{si}]"
        facts[f"{prefix}.page_width_tw"] = _emu_to_twips(sec.page_width)
        facts[f"{prefix}.page_height_tw"] = _emu_to_twips(sec.page_height)
        facts[f"{prefix}.margin.top_tw"] = _emu_to_twips(sec.top_margin)
        facts[f"{prefix}.margin.bottom_tw"] = _emu_to_twips(sec.bottom_margin)
        facts[f"{prefix}.margin.left_tw"] = _emu_to_twips(sec.left_margin)
        facts[f"{prefix}.margin.right_tw"] = _emu_to_twips(sec.right_margin)
        facts[f"{prefix}.diff_first_page_header"] = (
            sec.different_first_page_header_footer
        )
        sectPr = sec._sectPr
        cols = sectPr.find(qn("w:cols")) if sectPr is not None else None
        if cols is not None:
            facts[f"{prefix}.cols.num"] = cols.get(qn("w:num"))
            facts[f"{prefix}.cols.space"] = cols.get(qn("w:space"))
            facts[f"{prefix}.cols.equalWidth"] = cols.get(qn("w:equalWidth"))
            for ci, col in enumerate(cols.findall(qn("w:col"))):
                facts[f"{prefix}.cols.col[{ci}].w"] = col.get(qn("w:w"))
                facts[f"{prefix}.cols.col[{ci}].space"] = col.get(qn("w:space"))

    # ── Body order: paragraphs and tables ──
    p_idx = 0
    t_idx = 0
    for elem in doc.element.body.iterchildren():
        tag = elem.tag.split("}")[-1]
        if tag == "p":
            prefix = f"body.P[{p_idx:02d}]"
            p_idx += 1
            text = "".join(elem.itertext()).strip()
            facts[f"{prefix}.text"] = _truncate(text)

            pPr = elem.find(qn("w:pPr"))
            if pPr is not None:
                jc = pPr.find(qn("w:jc"))
                if jc is not None:
                    facts[f"{prefix}.jc"] = jc.get(qn("w:val"))
                pbb = pPr.find(qn("w:pageBreakBefore"))
                if pbb is not None:
                    facts[f"{prefix}.page_break_before"] = True
                spacing = pPr.find(qn("w:spacing"))
                if spacing is not None:
                    for attr in ("before", "after", "line", "lineRule"):
                        v = spacing.get(qn(f"w:{attr}"))
                        if v is not None:
                            facts[f"{prefix}.spacing.{attr}"] = v
                style = pPr.find(qn("w:pStyle"))
                if style is not None:
                    facts[f"{prefix}.pStyle"] = style.get(qn("w:val"))
                # Mid-document section break (a section change introduced via
                # a paragraph's pPr/sectPr — this is how multi-column blocks
                # are typically delimited).
                secPr = pPr.find(qn("w:sectPr"))
                if secPr is not None:
                    facts[f"{prefix}.sectPr"] = "PRESENT"
                    cols = secPr.find(qn("w:cols"))
                    if cols is not None:
                        facts[f"{prefix}.sectPr.cols.num"] = cols.get(qn("w:num"))
                        facts[f"{prefix}.sectPr.cols.space"] = cols.get(qn("w:space"))
                        for ci, col in enumerate(cols.findall(qn("w:col"))):
                            facts[f"{prefix}.sectPr.cols.col[{ci}].w"] = col.get(qn("w:w"))
                            facts[f"{prefix}.sectPr.cols.col[{ci}].space"] = col.get(qn("w:space"))
                    typ = secPr.find(qn("w:type"))
                    if typ is not None:
                        facts[f"{prefix}.sectPr.type"] = typ.get(qn("w:val"))

            for ri, run in enumerate(_direct_runs(elem)):
                rprefix = f"{prefix}.r[{ri}]"
                rtext = "".join(run.itertext())
                facts[f"{rprefix}.text"] = _truncate(rtext, 40)
                rPr = run.find(qn("w:rPr"))
                if rPr is not None:
                    if rPr.find(qn("w:b")) is not None:
                        facts[f"{rprefix}.bold"] = True
                    if rPr.find(qn("w:i")) is not None:
                        facts[f"{rprefix}.italic"] = True
                    sz = rPr.find(qn("w:sz"))
                    if sz is not None:
                        facts[f"{rprefix}.size_pt"] = int(sz.get(qn("w:val"))) / 2
                    spacing_r = rPr.find(qn("w:spacing"))
                    if spacing_r is not None:
                        facts[f"{rprefix}.letter_spacing"] = spacing_r.get(qn("w:val"))
                    rFonts = rPr.find(qn("w:rFonts"))
                    if rFonts is not None:
                        facts[f"{rprefix}.font"] = rFonts.get(qn("w:ascii"))
                # capture explicit page-break elements inside a run
                if run.find(qn("w:br")) is not None:
                    for br in run.findall(qn("w:br")):
                        typ = br.get(qn("w:type"))
                        if typ:
                            facts[f"{rprefix}.br.type"] = typ

        elif tag == "tbl":
            prefix = f"body.TBL[{t_idx}]"
            t_idx += 1
            grid = elem.find(qn("w:tblGrid"))
            if grid is not None:
                for gi, gc in enumerate(grid.findall(qn("w:gridCol"))):
                    facts[f"{prefix}.grid[{gi}].w"] = gc.get(qn("w:w"))

            rows = elem.findall(qn("w:tr"))
            for ri, row in enumerate(rows):
                cells = row.findall(qn("w:tc"))
                for ci, cell in enumerate(cells):
                    cprefix = f"{prefix}.cell[{ri},{ci}]"
                    tcPr = cell.find(qn("w:tcPr"))
                    if tcPr is not None:
                        tcW = tcPr.find(qn("w:tcW"))
                        if tcW is not None:
                            facts[f"{cprefix}.w"] = tcW.get(qn("w:w"))
                        vAlign = tcPr.find(qn("w:vAlign"))
                        if vAlign is not None:
                            facts[f"{cprefix}.vAlign"] = vAlign.get(qn("w:val"))
                        borders = tcPr.find(qn("w:tcBorders"))
                        if borders is not None:
                            for side in ("top", "bottom", "left", "right"):
                                b = borders.find(qn(f"w:{side}"))
                                if b is not None:
                                    val = b.get(qn("w:val"))
                                    sz = b.get(qn("w:sz"))
                                    facts[f"{cprefix}.border.{side}"] = (
                                        f"{val}/{sz}" if sz else val
                                    )
                        margins = tcPr.find(qn("w:tcMar"))
                        if margins is not None:
                            for side in ("top", "bottom", "left", "right"):
                                m = margins.find(qn(f"w:{side}"))
                                if m is not None:
                                    facts[f"{cprefix}.margin.{side}"] = m.get(qn("w:w"))
                    cell_paras = cell.findall(qn("w:p"))
                    for pi, p in enumerate(cell_paras):
                        pprefix = f"{cprefix}.p[{pi}]"
                        text = "".join(p.itertext()).strip()
                        facts[f"{pprefix}.text"] = _truncate(text, 40)
                        pPr = p.find(qn("w:pPr"))
                        if pPr is not None:
                            jc = pPr.find(qn("w:jc"))
                            if jc is not None:
                                facts[f"{pprefix}.jc"] = jc.get(qn("w:val"))
                            spacing = pPr.find(qn("w:spacing"))
                            if spacing is not None:
                                for attr in ("before", "after"):
                                    v = spacing.get(qn(f"w:{attr}"))
                                    if v is not None:
                                        facts[f"{pprefix}.spacing.{attr}"] = v
                            cs = pPr.find(qn("w:contextualSpacing"))
                            if cs is not None:
                                facts[f"{pprefix}.contextualSpacing"] = True
                        # Per-run bold inside cell (compact — only flag bold runs)
                        bold_runs = []
                        for ri2, run in enumerate(_direct_runs(p)):
                            rPr = run.find(qn("w:rPr"))
                            if rPr is not None and rPr.find(qn("w:b")) is not None:
                                bold_runs.append(ri2)
                        if bold_runs:
                            facts[f"{pprefix}.bold_runs"] = bold_runs

    return facts


def diff_facts(ref: dict[str, Any], ours: dict[str, Any]) -> list[str]:
    out: list[str] = []
    all_keys = sorted(set(ref) | set(ours))
    for k in all_keys:
        rv = ref.get(k, "—")
        ov = ours.get(k, "—")
        if rv != ov:
            out.append(f"{k}\n     REF:  {rv!r}\n     OURS: {ov!r}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    ref_path, ours_path = Path(argv[1]), Path(argv[2])
    if not ref_path.exists() or not ours_path.exists():
        print(f"missing file: {ref_path if not ref_path.exists() else ours_path}")
        return 2

    ref = collect_facts(Document(str(ref_path)))
    ours = collect_facts(Document(str(ours_path)))

    print(f"REF  = {ref_path.name}  ({len(ref)} facts)")
    print(f"OURS = {ours_path.name} ({len(ours)} facts)")
    print(f"{'=' * 70}")

    diffs = diff_facts(ref, ours)
    if not diffs:
        print("(no differences)")
        return 0

    print(f"{len(diffs)} differences:\n")
    for entry in diffs:
        print(entry)
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
