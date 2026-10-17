"""Core data shapes shared across the reader, manual-entry form, session
store, PDF fill, and NPRS-4 export.

`VoterEntry`'s field names deliberately match `reader.eid_reader.
SerbianIDReader.read_card()`'s own dict keys 1:1 — the same vocabulary
flows reader/manual-form -> session store -> overlay placeholders ->
NPRS-4 columns without per-layer renaming, and the rest of the pipeline
can't tell whether an entry came from a card read or manual typing
(`source` is the only thing that records which).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# Document-type labels for the fill-out screen's dropdown. A card read
# always implies "Лична карта" (only ID cards have the eID chip); the
# other two exist because a voter may present a driver's license or
# passport instead, which the operator selects and types up manually.
DOCUMENT_TYPES = ("Лична карта", "Возачка дозвола", "Пасош")


@dataclass
class VoterEntry:
    given_name: str = ""
    surname: str = ""
    jmbg: str = ""
    date_of_birth: str = ""
    city: str = ""
    full_address: str = ""
    document_type: str = DOCUMENT_TYPES[0]
    document_reg_no: str = ""
    date_of_issue: str = ""
    issuing_authority: str = ""
    # JPEG bytes from EID_PORTRAIT, when read from a card. None for
    # manual entries — there's no photo to carry.
    portrait_jpeg: bytes | None = None
    # "card" | "manual" — which path produced this entry. Nothing
    # downstream branches on this except display/audit; it is not part
    # of the printed declaration or the NPRS-4 export.
    source: str = "manual"
    # Values for this template's "individual" custom fields (see
    # CustomFieldDef) — anything the operator needs to type per voter
    # that isn't part of the ID card's own data, e.g. a field specific
    # to some other document this app gets used for later. Keyed by
    # CustomFieldDef.key.
    custom_values: dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.surname}".strip()

    @property
    def full_residence(self) -> str:
        """The real form has one blank labeled "(место и адреса
        пребивалишта)" — a single line, not two — so city and address
        print together here rather than needing two separate
        calibrated positions for one physical blank."""
        return ", ".join(p for p in (self.city, self.full_address) if p)

    @property
    def full_document_info(self) -> str:
        """Same reasoning as full_residence: the form's one blank reads
        "(назив службеног документа, број, датум издавања и
        издавалац)" — document type (the ЛК/возачка/пасош dropdown),
        number, issue date, and issuing authority all on one line."""
        parts = (self.document_type, self.document_reg_no, self.date_of_issue, self.issuing_authority)
        return ", ".join(p for p in parts if p)

    @property
    def jmbg_digits(self) -> dict[str, str]:
        """{{jmbg_1}}..{{jmbg_13}} — the official forms render JMBG as
        13 individual digit cells, not one field."""
        digits = (self.jmbg or "").strip()
        return {
            f"jmbg_{i + 1}": (digits[i] if i < len(digits) else "")
            for i in range(13)
        }

    def to_dict(self) -> dict[str, Any]:
        d = {
            "given_name": self.given_name,
            "surname": self.surname,
            "jmbg": self.jmbg,
            "date_of_birth": self.date_of_birth,
            "city": self.city,
            "full_address": self.full_address,
            "document_type": self.document_type,
            "document_reg_no": self.document_reg_no,
            "date_of_issue": self.date_of_issue,
            "issuing_authority": self.issuing_authority,
            "source": self.source,
        }
        d.update(self.jmbg_digits)
        d["full_name"] = self.full_name
        d["full_residence"] = self.full_residence
        d["full_document_info"] = self.full_document_info
        d.update(self.custom_values)
        return d


@dataclass
class SessionInfo:
    template_name: str = ""
    copies: int = 1
    # Which printer this sitting prints to. "" means "whatever Windows'
    # own default is", with core.print_pdf's virtual-printer rescue
    # applied on top. A name here is the operator's explicit choice and
    # overrides all of that — which is the only thing that works on a
    # domain-managed machine, where Group Policy reapplies the default
    # printer and a locally-changed default does not survive.
    printer_name: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    # Values for this template's "universal" custom fields — entered
    # once on the setup screen and printed unchanged on every copy in
    # the session (e.g. NPRS-3's certifier name/address block, which is
    # fixed data, not per-voter data — but named generically because a
    # different document this app calibrates later may need a
    # completely different set of "same for the whole sitting" fields).
    # Keyed by CustomFieldDef.key.
    custom_values: dict[str, str] = field(default_factory=dict)
    # Which ExportTemplateDef (core.export_template_catalog) this
    # session's "Заврши сесију и извези" button uses — chosen as an
    # optional step on the setup screen, right after a template is
    # picked/created. "" means the operator isn't exporting a
    # cumulative roster for this session at all.
    export_template_name: str = ""


@dataclass
class CustomFieldDef:
    """An operator-named field that isn't part of the ID card's own
    data (so it can't be one of VoterEntry's fixed attributes) — e.g. a
    certifier's name/address on NPRS-3, or whatever some other document
    this app calibrates later turns out to need. `kind` decides where
    its value comes from at fill time: "individual" is typed per voter
    on the fill-out screen (VoterEntry.custom_values); "universal" is
    typed once on the setup screen and reused for every copy in the
    session (SessionInfo.custom_values).

    `default_value` pre-fills the field's edit box (still freely
    editable, never locked) — e.g. a certifier's name that's the same
    for nearly every session, or a document type most voters share.
    Empty means no change from today's blank-by-default behaviour."""

    key: str
    label: str
    kind: str = "individual"  # "individual" | "universal"
    default_value: str = ""


@dataclass
class FieldPosition:
    """One field's calibrated overlay position on a PDF page (points,
    bottom-left origin — matches reportlab/pypdf page coordinates).

    `field_key` is either one of VoterEntry's fixed attribute names or
    a CustomFieldDef.key defined on the same template."""

    field_key: str
    page_index: int
    x: float
    y: float
    font_size: float = 10.0
    # "" = use overlay_fill's registered Unicode font. reportlab's base-14
    # fonts (e.g. "Helvetica") use WinAnsiEncoding and silently corrupt
    # Cyrillic (confirmed directly: drawing "(име и презиме)" with
    # Helvetica came back as garbage when read back) — never default to
    # one of those here.
    font_name: str = ""
    # 0.0 = auto, sized from font_size (see auto_box_size() below). Lets
    # the operator widen/narrow the on-screen preview box to match a
    # real field's width while calibrating — most importantly JMBG's 13
    # individual digit cells, each much narrower than the generic
    # auto-sized box for a name/address field. `width` also doubles as
    # the real box `align` centers/right-aligns text within, and the
    # box overlay_fill.fill_declaration shrinks the font to fit rather
    # than let unusually long text spill past — see that function's own
    # comment for why shrinking, not wrapping, is the correct response
    # on these forms. `height` stays preview-only either way; printing
    # never wraps or clips vertically.
    width: float = 0.0
    height: float = 0.0
    bold: bool = False
    italic: bool = False
    align: str = "center"  # "left" | "center" | "right"


def auto_box_size(field_key: str, font_size_pt: float) -> tuple[float, float]:
    """Default box size (points) for a field the operator hasn't given
    an explicit `FieldPosition.width`/`height` — narrow for a single
    JMBG digit cell, generous for a free-text field like a name or
    address.

    Two uses, both needing the exact same answer so they can't drift
    apart: the calibration wizard sizes a field's on-screen preview box
    from this before the operator ever sets a real width, and
    `overlay_fill.fill_declaration` uses it as the shrink-to-fit ceiling
    for a field nobody explicitly measured — so a long name still gets
    *some* overflow protection instead of none at all, without the
    operator having to know to set a width just for that.
    """
    height = font_size_pt * 1.6
    if field_key.startswith("jmbg_"):
        return font_size_pt * 1.8, height
    return max(90.0, font_size_pt * 10.0), height


@dataclass
class CalibratedTemplate:
    """A background PDF plus the field->position map needed to fill it.
    Saved to the local template catalog for reuse (`core.template_catalog`)."""

    name: str
    background_pdf_path: str
    positions: list[FieldPosition] = field(default_factory=list)
    custom_fields: list[CustomFieldDef] = field(default_factory=list)
    form_id: str = ""       # e.g. "NPRS-3" / official form number
    year: str = ""
    municipality: str = ""
    calibrated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


# A column mapped to this key isn't read from the voter at all — it's
# the entry's own 1-based position in the finished, already-sorted
# export (the "Редни број" an official roster numbers its rows with).
# Assigned after sorting, so the numbering always runs 1..N down the
# page regardless of the order entries were collected in.
ROW_NUMBER_FIELD_KEY = "__row_number__"


@dataclass
class ExportColumnDef:
    """One column of a cumulative (multi-voter) export — a header plus
    which field(s) feed it. Each key in `field_keys` resolves through
    the exact same value pool a print position does (VoterEntry.
    to_dict(), SessionInfo.custom_values) — see core.generic_export.
    export_roster — so a column can point at a built-in field, a
    custom field defined on the calibrated template, or a "universal"
    session field, without this app needing to already know what any
    future document's roster looks like.

    `field_keys` holds one or more field keys, joined in order; when
    there's more than one, `separators[i]` sits between `field_keys[i]`
    and `field_keys[i+1]` (so len(separators) == len(field_keys) - 1),
    letting the operator build any composite column themselves — e.g.
    surname + " " + given name, or municipality + " - " + certifier
    name + ", " + certifier address — with their own choice of fields
    and separator text per join, entirely from the export-template
    screen. Nothing about what any of these fields "mean" is known
    here; this is pure ordered string concatenation.

    `column_index` (1-based) is the real spreadsheet column this
    header was detected at when the operator loaded an existing Excel
    file — export writes to that exact column, not to columns 1..N in
    whatever order the mapping table happens to list them, so removing
    or reordering a row in the mapping table can't shift the rest of
    the data sideways relative to the file's own header row. 0 means
    "not tied to a real column" (a column the operator added by hand,
    with no file loaded) — export_roster appends those after every
    column that does have a known position."""

    header: str
    field_keys: list[str] = field(default_factory=list)
    separators: list[str] = field(default_factory=list)
    column_index: int = 0


@dataclass
class ExportTemplateDef:
    """A cumulative export layout the operator defines and reuses —
    e.g. a stand-in for NPRS-4 built from whichever fields a given
    document actually calibrated, instead of one hardcoded roster
    shape. Saved to its own local catalog (`core.export_template_
    catalog`), independent of which CalibratedTemplate produced the
    entries being exported.

    `source_file` + `header_row`, when set, point at a pristine copy of
    a real official spreadsheet the operator loaded while building this
    template (see gui.export_template_wizard) — every export re-opens
    that untouched file fresh and inserts this session's rows right
    below the header, so whatever sits above and below (boilerplate,
    footer legal text, signature blocks) survives byte-for-byte in
    every exported file, letting many machines' files be merged by
    hand later because they all keep the exact same physical shape.
    `sort_column_1`/`sort_column_2` name columns by their own `header`
    text (not a fixed field) — the operator picks which of their own
    columns to sort by, in priority order; "" means no sorting on that
    level."""

    name: str
    columns: list[ExportColumnDef] = field(default_factory=list)
    source_file: str = ""
    header_row: int = 1
    sort_column_1: str = ""
    sort_column_2: str = ""
