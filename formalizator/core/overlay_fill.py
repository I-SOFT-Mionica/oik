"""Fill one voter's declaration by drawing values on a transparent
overlay and merging it onto a frozen background PDF page.

This is the finished form of `Celik/Formalizator.py`'s
`overlay_on_pdf_template` (sketched, never completed — its "get the
coordinates" step was a stub). The background PDF (a one-time export
of the already-tuned official Word document, see `core.pdf_template`)
is never edited — only ever read — so the client's hand-tuned layout
(days of work fitting JMBG digits into their boxes) cannot drift, no
matter how many times a fill runs.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from formalizator.core.field_values import resolve_values
from formalizator.core.models import (
    CalibratedTemplate, SessionInfo, VoterEntry, auto_box_size,
)

# Floor for the shrink-to-fit below. Below this a name is still drawn,
# just no longer shrunk further — an unusually long value overflowing
# its box slightly stays more legible than one crushed down to an
# illegible size trying to force it to fit exactly.
_MIN_SHRINK_FONT_PT = 6.0

# reportlab's base-14 fonts ("Helvetica" etc.) use WinAnsiEncoding and
# silently corrupt Cyrillic — confirmed directly (drawing
# "(име и презиме)" with Helvetica read back as garbage, not an error).
# Every value this app overlays is Serbian Cyrillic or Latin, so a
# real Unicode TTF is registered once and used unless a calibrated
# position explicitly names a different font.
_DEFAULT_FONT_NAME = "CelikOverlayFont"
# (regular, bold, italic, bold+italic) filenames for each candidate
# family, tried in order — same families as before, now with their
# style siblings so a calibrated bold/italic position doesn't fall back
# to a fake (non-existent) style.
_FONT_FAMILIES = (
    ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
)
_FONT_DIR = Path(r"C:\Windows\Fonts")
_registered_fonts: dict[str, str] = {}  # style key -> registered reportlab font name


def _style_key(bold: bool, italic: bool) -> str:
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


def _font_for_style(bold: bool = False, italic: bool = False) -> str:
    """Registers (once, cached) and returns the Unicode TTF matching
    this bold/italic combination, from whichever font family is
    actually installed on this machine. Falls back to that family's
    plain regular file if a specific style sibling is missing —
    never to a base-14 font, which would silently corrupt Cyrillic."""
    key = _style_key(bold, italic)
    if key in _registered_fonts:
        return _registered_fonts[key]
    variant_index = {"regular": 0, "bold": 1, "italic": 2, "bolditalic": 3}[key]
    for family in _FONT_FAMILIES:
        regular_path = _FONT_DIR / family[0]
        if not regular_path.exists():
            continue
        variant_path = _FONT_DIR / family[variant_index]
        path = variant_path if variant_path.exists() else regular_path
        font_name = f"{_DEFAULT_FONT_NAME}_{key}"
        pdfmetrics.registerFont(TTFont(font_name, str(path)))
        _registered_fonts[key] = font_name
        return font_name
    raise RuntimeError(
        "No Unicode TTF font found to render Cyrillic text — tried: "
        + ", ".join(f[0] for f in _FONT_FAMILIES)
    )


def _default_font() -> str:
    return _font_for_style()


def fill_declaration(
    template: CalibratedTemplate, entry: VoterEntry, out_path: Path | str,
    session_info: SessionInfo | None = None,
) -> Path:
    """Draw `entry`'s values at `template`'s calibrated positions onto
    its frozen background, one merged PDF per voter. `session_info`
    supplies this session's fixed values — its own list_name/
    submitter_name/municipality/certifier_name fields plus any
    "universal" custom-field values — all the same on every voter's
    copy, so they're typed once on the setup screen rather than per
    entry."""
    # Pages are cloned into the writer FIRST (pypdf's recommended
    # pattern) rather than merging onto pages read straight off a bare
    # PdfReader — merge_page() on a page not yet attached to a writer
    # is explicitly documented by pypdf as unreliable.
    writer = PdfWriter(clone_from=str(template.background_pdf_path))

    values = resolve_values(entry, session_info)
    by_page: dict[int, list] = {}
    for pos in template.positions:
        by_page.setdefault(pos.page_index, []).append(pos)

    for page_index, page in enumerate(writer.pages):
        positions = by_page.get(page_index, [])
        if not positions:
            continue
        box = page.mediabox
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=(float(box.width), float(box.height)))
        for pos in positions:
            text = str(values.get(pos.field_key, ""))
            if text:
                font_name = pos.font_name or _font_for_style(pos.bold, pos.italic)
                font_size = pos.font_size

                # A value longer than its blank must not spill into
                # whatever the real form prints beside or below it —
                # these are single-line blanks on a hand-tuned official
                # form, there is no second line to wrap into the way a
                # word processor would. Shrinking the font is the
                # correct response, not wrapping: it keeps the value on
                # its one real line, which is the only place the form
                # has room for it. `pos.width` is the operator's own
                # measurement when they set one; otherwise the same
                # auto-computed box the calibration wizard already shows
                # as the field's preview box is reused, so a field
                # nobody explicitly measured still gets *some*
                # protection instead of none.
                box_width = pos.width if pos.width > 0 else auto_box_size(pos.field_key, font_size)[0]
                text_width = c.stringWidth(text, font_name, font_size)
                if text_width > box_width:
                    font_size = max(_MIN_SHRINK_FONT_PT, font_size * box_width / text_width)
                    text_width = c.stringWidth(text, font_name, font_size)
                c.setFont(font_name, font_size)

                x = pos.x
                # Center/right need a real box width to align within —
                # width is 0 ("auto") unless the operator explicitly
                # set one, so with no width there's nothing to align
                # against and text draws from the anchor as normal.
                if pos.align in ("center", "right") and pos.width > 0:
                    if pos.align == "center":
                        x = pos.x + (pos.width - text_width) / 2
                    else:  # "right"
                        x = pos.x + pos.width - text_width
                c.drawString(x, pos.y, text)
        c.showPage()
        c.save()
        buf.seek(0)
        overlay_page = PdfReader(buf).pages[0]
        page.merge_page(overlay_page)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path
