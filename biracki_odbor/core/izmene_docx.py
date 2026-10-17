"""Amendment resolution (Решење о изменама) generator.

Generates one Word .docx per amendment to an existing polling-board
appointment resolution. Mirrors the templates in
``izmene/BM 9 resenje o izmeni STALNOG SASTAVA...docx`` and
``izmene/BM 7 -izmenA PROSERNOG SASTAVA...docx``.

Key design points:
- `IzmenaRecord` — one person substitution (old → new) within an amendment.
- `IzmenaSpec`   — all parameters for a single amendment document.
- `build_izmena_document()` — pure function: spec + config → Document.
- `generate_izmena()` — convenience wrapper that also writes the file.

Authorization fields (auth number, date, authorized person's name and role)
are read from ``DocumentInfo.authorization_*`` — they are fixed per
election cycle and are edited from the Измене tab.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime as _dt
from functools import lru_cache
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from biracki_odbor.config.commission import commission_terms
from biracki_odbor.config.obrazlozenje import commission_placeholders
from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from docx.enum.table import WD_TABLE_ALIGNMENT

from biracki_odbor.core.phase3_docx import (
    BODY_PT,
    FONT,
    TITLE_PT,
    _add_mixed_para,
    _add_para,
    _set_cell_borders,
    _twips,
    apply_document_format,
)


_FUNCTION_GENITIVE: dict[str, str] = {
    "Председник": "ПРЕДСЕДНИКА",
    "Заменик председника": "ЗАМЕНИКА ПРЕДСЕДНИКА",
    "Члан 1": "ЧЛАНА 1",
    "Заменик члана 1": "ЗАМЕНИКА ЧЛАНА 1",
    "Члан 2": "ЧЛАНА 2",
    "Заменик члана 2": "ЗАМЕНИКА ЧЛАНА 2",
}

_POST_RIK_EVENTS = frozenset({
    "resolve_conflict", "replace_member", "edit_member",
    "remove_member", "add_member", "nacelnik_appointment",
})

# чл. 41. став 2. Закона о избору народних посланика: ONLY председник and
# заменик председника (стални састав — прошиени has no chairman seat) can
# be replaced on these specific grounds, on a shorter deadline (up to the
# opening of the polling station, not the generic 3-days-before cutoff).
# Must match the Напомена dropdown's reason strings exactly (corrections.py
# imports these three from here as its source of truth).
REASON_SMRT = "Смрт"
REASON_NESPOSOBNOST = "Неспособност"
REASON_GUBITAK_PRAVA = "Губитак бирачког права"
CHAIRMAN_LAPSE_REASONS = (REASON_SMRT, REASON_NESPOSOBNOST, REASON_GUBITAK_PRAVA)

_CHAIRMAN_FUNCTIONS = frozenset({"Председник", "Заменик председника"})

_CHAIRMAN_FUNCTION_FULL: dict[str, str] = {
    "Председник": "ПРЕДСЕДНИКА БИРАЧКОГ ОДБОРА",
    "Заменик председника": "ЗАМЕНИКА ПРЕДСЕДНИКА БИРАЧКОГ ОДБОРА",
}


def function_to_genitive(fn: str) -> str:
    """Convert nominative function name to uppercase genitive for izmena docs."""
    return _FUNCTION_GENITIVE.get(fn, fn.upper())


def _person_dict_name(d: dict) -> str:
    """Joined display name from a Person.to_dict() snapshot.

    Person.to_dict() is a plain dataclasses.asdict() — "name" is a
    @property, not a field, so it's never actually a key in these
    dicts. A bare `d.get("name")` silently returns "" for every real
    audit event, which made events_to_izmena_records() below skip
    every genuine name change (the whole point of an amendment) and
    auto-generation return no records at all. Falls back to a legacy
    "name" key too, for any older log entries that predate the
    first_name/last_name split.
    """
    return (d.get("name") or f"{d.get('first_name', '')} {d.get('last_name', '')}".strip()).strip()


def events_to_izmena_records(events: list) -> dict[int, list[IzmenaRecord]]:
    """Group audit events by BM number and convert to IzmenaRecord lists.

    Multiple events touching the SAME (bm, function) slot in this batch
    (e.g. "Очисти место" followed by a nacelnik appointment — appointing
    requires clearing first, so these are two separate audit events but
    one semantic correction) are merged into a single record: old_name
    comes from the EARLIEST event's `before` (what the slot showed
    before any edit in this batch — i.e. what the last-issued decision
    actually says), new_name/party/mesto/appointed_by_nacelnik come from
    the LATEST event's `after` (the slot's final state). Without this, a
    clear-then-appoint pair produced two incoherent half-records — one
    "уместо X именује: [blank]", one "уместо [blank] именује Y" —
    instead of one correct "уместо X именује Y".

    Skips slots with no net meaningful change (e.g. kept-side
    resolve_conflict log entries where before is None and no old name).
    Returns ``dict[bm_number -> list[IzmenaRecord]]``.
    """
    by_slot: dict[tuple[int, str], list] = {}
    for ev in events:
        if ev.slot_bm is None:
            continue
        by_slot.setdefault((ev.slot_bm, ev.slot_function), []).append(ev)

    by_bm: dict[int, list[IzmenaRecord]] = {}
    for (bm, function), slot_events in by_slot.items():
        first_ev, last_ev = slot_events[0], slot_events[-1]
        before = first_ev.before or {}
        after = last_ev.after or {}
        old_name = _person_dict_name(before)
        new_name = _person_dict_name(after)
        # Skip kept-side resolve_conflict (before=None → no old person recorded)
        if first_ev.before is None and not old_name:
            continue
        if not old_name and not new_name:
            continue
        fn = function_to_genitive(function or "")
        party = (after.get("party") or before.get("party") or "").strip()
        new_place = (after.get("mesto") or "").strip()
        old_place = (before.get("mesto") or "").strip()
        before_jmbg = (before.get("jmbg") or "").strip()
        after_jmbg = (after.get("jmbg") or "").strip()
        is_correction = bool(before_jmbg) and before_jmbg == after_jmbg
        # A correction with no change to either field that actually
        # appears in the document (e.g. a phone/email-only edit) has
        # nothing to disclose in an appointment record — skip it rather
        # than emit a false "уместо X уписује се X" line.
        if is_correction and old_name == new_name and old_place == new_place:
            continue
        reason = (last_ev.note or "").strip()
        is_chairman_lapse = (
            not is_correction
            and function in _CHAIRMAN_FUNCTIONS
            and reason in CHAIRMAN_LAPSE_REASONS
        )
        if is_chairman_lapse:
            fn = _CHAIRMAN_FUNCTION_FULL[function]
        rec = IzmenaRecord(
            old_name=old_name,
            function=fn,
            new_name=new_name,
            new_place=new_place,
            party=party,
            appointed_by_nacelnik=bool(after.get("appointed_by_nacelnik", False)),
            is_correction=is_correction,
            old_place=old_place,
            is_chairman_lapse=is_chairman_lapse,
        )
        by_bm.setdefault(bm, []).append(rec)
    return by_bm


@dataclass
class IzmenaRecord:
    """One person substitution — or, when `is_correction` is set, one data
    correction for the SAME person — within an amendment."""

    old_name: str = ""      # "Никола Ареснић"
    function: str = ""      # "ЧЛАНА 1"  (uppercase, as it appears in the document)
    new_name: str = ""      # "Славко Максимовић"
    new_place: str = ""     # "Такова"
    party: str = ""         # abbreviation key in election.party_full_names
    appointed_by_nacelnik: bool = False  # new_name was filled by the chief
    # Same JMBG before and after: this is a data fix (name spelling,
    # residence), NOT a membership change, and must be worded as such —
    # "уместо X именује Y" on an unchanged person reads as OIK un-appointing
    # and re-appointing them to themselves.
    is_correction: bool = False
    old_place: str = ""     # only meaningful when is_correction is True
    # чл. 41. став 2.: a председник/заменик председника seat vacated by
    # death, illness, or loss of voting right — a different legal basis,
    # образложење, deadline, and single-sentence disposition from the
    # generic "на захтев овлашћеног предлагача" replacement (ст. 1).
    is_chairman_lapse: bool = False


def record_variant(rec: IzmenaRecord) -> str:
    """Which of the three legal tracks this record belongs to."""
    if rec.is_correction:
        return "correction"
    if rec.is_chairman_lapse:
        return "chairman_lapse"
    return "replacement"


def group_records_by_variant(records: list[IzmenaRecord]) -> list[list[IzmenaRecord]]:
    """Partition one BM's records into the separate documents they must
    become — the three tracks have different legal basis, образложење,
    and disposition phrasing, so they can never share one document.

    A chairman_lapse record always gets its own single-item document —
    the official "1 3" template has no numbered-list form, only one
    continuous disposition sentence. Same-variant "correction" and
    "replacement" records elsewhere in the batch still share one
    document each, in encounter order.
    """
    groups: list[list[IzmenaRecord]] = []
    bucket_index: dict[str, int] = {}
    for rec in records:
        variant = record_variant(rec)
        if variant == "chairman_lapse":
            groups.append([rec])
            continue
        if variant in bucket_index:
            groups[bucket_index[variant]].append(rec)
        else:
            bucket_index[variant] = len(groups)
            groups.append([rec])
    return groups


@dataclass
class IzmenaSpec:
    """All inputs needed to generate one amendment document."""

    bm_number: int = 1
    bm_name: str = ""               # "КУЋА ЈОКИЋ МИЛОВАНА, ВРЕЛО"
    original_broj: str = ""         # "013-5-30-9/2023"  (without "Број: " prefix)
    original_date: str = ""         # "6. децембра 2023. године"
    amendment_index: int = 1        # ordinal of this amendment (1st, 2nd, …)
    amendment_counter: int = 1      # sub-counter, usually equals amendment_index
    issue_date: str = ""            # "12. децембра 2023. године"
    records: list[IzmenaRecord] = field(default_factory=list)
    slug: str = "stalni"            # "stalni" or "prosireni"


def format_amendment_broj(original_broj: str, amendment_index: int, counter: int) -> str:
    """Derive the amendment Број from the original resolution number.

    "013-5-30-9/2023" + index=1, counter=1 → "Број: 013-5-30-9/1/2023-01"
    """
    original = original_broj.strip()
    if "/" in original:
        base, year = original.rsplit("/", 1)
        return f"Број: {base}/{amendment_index}/{year}-{counter:02d}"
    return f"Број: {original}/{amendment_index}-{counter:02d}"


def _party_proposal_text(
    party: str, election: ElectionConfig, slug: str, issue_date: str,
    nacelnik_full_name: str, *, appointed_by_nacelnik: bool = False,
) -> str:
    """Build the 'на предлог …' phrase for one disposition sub-item.

    `party` stays the RIK-allocated party even for a nacelnik-filled slot
    (needed elsewhere for quota stats), so `appointed_by_nacelnik` forces
    the lookup key to miss, triggering the nacelnik fallback in
    `ElectionConfig.party_full_name` instead of the original party's name.
    """
    full, _ = election.party_full_name(
        "" if appointed_by_nacelnik else party, nacelnik_full_name,
    )
    if not full:
        return "на предлог"
    if slug == "prosireni":
        return f"на предлог подносиоца Изборне листе {full.upper()}"
    for prefix in ("Посланичке групе ", "Посланичка група "):
        if full.startswith(prefix):
            rest = full[len(prefix):].strip()
            date_suffix = f" од {issue_date}" if issue_date else ""
            return f"на предлог Посланичке групе {rest}{date_suffix}"
    date_suffix = f" од {issue_date}" if issue_date else ""
    return f"на предлог {full}{date_suffix}"


def _correction_segments(i: int, rec: IzmenaRecord) -> list[tuple[str, bool]]:
    """Disposition text for a same-person data fix (JMBG unchanged).

    Never phrased as "уместо X именује Y" — the person's seat isn't
    changing hands, so that reads as OIK un-appointing and re-appointing
    them to themselves. Instead states plainly which stored value was
    wrong and what it's corrected to, for whichever of name/place
    actually differ (either or both).
    """
    name_changed = rec.old_name != rec.new_name
    place_changed = rec.old_place != rec.new_place
    identifier = rec.new_name or rec.old_name

    if name_changed and place_changed:
        return [
            (f"{i}) исправљају се подаци за ", False),
            (rec.function, True),
            (f" {identifier}", False),
            (": уместо „", False),
            (rec.old_name, True),
            ("” уписује се: „", False),
            (rec.new_name, True),
            ("”; уместо „", False),
            (rec.old_place, True),
            ("” уписује се: „", False),
            (rec.new_place, True),
            ("”;", False),
        ]
    if place_changed:
        return [
            (f"{i}) исправља се податак о пребивалишту за ", False),
            (rec.function, True),
            (f" {identifier}", False),
            (": уместо „", False),
            (rec.old_place, True),
            ("” уписује се: „", False),
            (rec.new_place, True),
            ("”;", False),
        ]
    # name_changed (or no textual difference at all — still state it plainly)
    return [
        (f"{i}) исправља се податак о имену и презимену за ", False),
        (rec.function, True),
        (": уместо „", False),
        (rec.old_name, True),
        ("” уписује се: „", False),
        (rec.new_name, True),
        ("”;", False),
    ]


# ── Seed obrazlozenje paragraphs for izmena documents ───────────────────────
# Canonical text lives in bundled JSON resources
# (resources/izmena_obrazlozenje_stalni_defaults.json / ..._prosireni_...),
# not as Python literals, so a wording change between election cycles is a
# data edit, not a code change. Template codes: {auth_ref}, {auth_name},
# {auth_role} — substituted by render_izmena_obrazlozenje().

_IZMENA_SEED_RESOURCE: dict[str, str] = {
    "stalni": "izmena_obrazlozenje_stalni_defaults.json",
    "prosireni": "izmena_obrazlozenje_prosireni_defaults.json",
}


@lru_cache(maxsize=4)
def _load_bundled_seed_dicts(resource_name: str) -> tuple[dict, ...]:
    """Read one bundled izmena seed JSON resource as plain paragraph dicts
    (the shape `obrazlozenje._from_json` expects). Cached — read-only
    package resource, no reason to re-parse it on every call."""
    from importlib import resources
    raw = resources.files("biracki_odbor.resources").joinpath(resource_name).read_text(
        encoding="utf-8",
    )
    return tuple(json.loads(raw)["paragraphs"])


def seed_izmena_paragraphs(slug: str) -> list[dict]:
    """The canonical (shipped-with-the-app) izmena obrazlozenje for
    `slug` — what a fresh workflow seeds with."""
    resource_name = _IZMENA_SEED_RESOURCE.get(slug, _IZMENA_SEED_RESOURCE["stalni"])
    return list(_load_bundled_seed_dicts(resource_name))


@lru_cache(maxsize=1)
def _chairman_lapse_defaults() -> tuple[str, tuple]:
    """Legal basis + образложење paragraphs for the чл. 41. ст. 2.
    track (see `resources/izmena_chairman_lapse_defaults.json`). Always
    used as-is — this variant has no user-editable override file, unlike
    the generic track's cards (see §"Legal-text override" decision: the
    citation here is forced regardless of what the operator has typed
    into Правни основ or customized in their cards, since a wrong
    citation on this specific track is the costlier failure mode)."""
    from biracki_odbor.config.obrazlozenje import _from_json
    from importlib import resources
    raw = resources.files("biracki_odbor.resources").joinpath(
        "izmena_chairman_lapse_defaults.json",
    ).read_text(encoding="utf-8")
    data = json.loads(raw)
    paragraphs = tuple(_from_json({"paragraphs": data["paragraphs"]}))
    return data["legal_basis"], paragraphs


# ── Pure data functions ───────────────────────────────────────────────────────


def load_all_post_rik_changes(log_path: Path, submitted_ts: int) -> list[dict]:
    """Read all post-RIK correction events from the log (all BMs).

    Returns one dict per event with keys:
      bm, function, old_name, new_name, before_jmbg, after_jmbg, mesto,
      old_mesto, party, note, other_bm, other_municipality,
      other_decision_broj, timestamp
    """
    if not log_path.exists() or submitted_ts == 0:
        return []
    try:
        cutoff_dt = _dt.fromtimestamp(submitted_ts).astimezone()
    except (OSError, ValueError):
        return []
    events: list[dict] = []
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if ev.get("event_type") not in _POST_RIK_EVENTS:
            continue
        ts_str = ev.get("timestamp", "")
        try:
            ev_dt = _dt.fromisoformat(ts_str)
        except ValueError:
            continue
        if ev_dt <= cutoff_dt:
            continue
        before = ev.get("before") or {}
        after = ev.get("after") or {}
        old_name = _person_dict_name(before)
        new_name = _person_dict_name(after)
        events.append({
            "bm": ev.get("slot_bm", 0),
            "function": ev.get("slot_function", ""),
            "old_name": old_name,
            "new_name": new_name,
            "before_jmbg": before.get("jmbg", ""),
            "after_jmbg": after.get("jmbg", ""),
            "mesto": after.get("mesto", "") or before.get("mesto", ""),
            "old_mesto": before.get("mesto", ""),
            "party": after.get("party", "") or before.get("party", ""),
            "appointed_by_nacelnik": bool(after.get("appointed_by_nacelnik", False)),
            "note": ev.get("note", ""),
            "other_bm": ev.get("other_bm"),
            "other_municipality": ev.get("other_municipality", ""),
            "other_decision_broj": ev.get("other_decision_broj", ""),
            "timestamp": ts_str,
        })
    return events


def render_izmena_obrazlozenje(
    paragraphs: list,
    *,
    use_authorization: bool = True,
    auth_ref: str = "",
    auth_name: str = "",
    auth_role: str = "",
    opstina: str = "",
    commission=None,
) -> list[list[tuple[str, bool]]]:
    """Render izmena obrazlozenje paragraphs with amendment-specific context.

    Paragraphs must be objects with .id, .segments (list with .text/.bold),
    and .optional attributes (compatible with obrazlozenje.Paragraph).
    Paragraphs with id 'ovlascenje' are skipped when use_authorization=False.
    """
    ctx = {
        "auth_ref": auth_ref,
        "auth_name": auth_name,
        "auth_role": auth_role,
        "opstina": opstina,
        **commission_placeholders(commission, opstina),
    }
    out: list[list[tuple[str, bool]]] = []
    for p in paragraphs:
        if getattr(p, "optional", False):
            continue
        if not use_authorization and getattr(p, "id", "") == "ovlascenje":
            continue
        rendered: list[tuple[str, bool]] = []
        for seg in p.segments:
            try:
                text = seg.text.format(**ctx)
            except (KeyError, IndexError, ValueError):
                text = seg.text
            rendered.append((text, seg.bold))
        if rendered:
            out.append(rendered)
    return out


def load_izmena_obrazlozenje(slug: str, path: Path) -> list:
    """Load izmena obrazlozenje from path, seeding from the bundled
    defaults (seed_izmena_paragraphs()) on first run."""
    from biracki_odbor.config import obrazlozenje as obr_mod
    if not path.exists():
        seed_dicts = seed_izmena_paragraphs(slug)
        seed_paragraphs = obr_mod._from_json({"paragraphs": seed_dicts})  # noqa: SLF001
        obr_mod.save(seed_paragraphs, path)
    return obr_mod.load(path=path)


# ── Document builders ─────────────────────────────────────────────────────────


def build_izmena_document(
    spec: IzmenaSpec,
    oik: OikConstants,
    election: ElectionConfig,
    *,
    rendered_obrazlozenje: list[list[tuple[str, bool]]] | None = None,
    legal_basis: str = "",
    use_authorization: bool = True,
) -> Document:
    """Generate one amendment resolution document and return it.

    Args:
        rendered_obrazlozenje: Pre-rendered paragraph segments for the Образложење
            block. When None, falls back to hardcoded defaults.
        legal_basis: User-edited legal preamble text. When non-empty, replaces
            the hardcoded "На основу..." paragraph with plain text.
        use_authorization: When False, signature block uses the OIK chairman
            identity instead of the delegated authorized person.
    """
    mun = oik.municipality
    mun_name = mun.name
    terms = commission_terms(mun)
    doc_info = election.document

    is_prosireni = spec.slug == "prosireni"

    law_article = "члана 39 став 1." if is_prosireni else "члана 35."

    # чл. 41. ст. 2.: a председник/заменик председника seat vacated by
    # death, illness, or loss of voting right. Only exists for стални
    # (прошиени has no chairman), is always a single-item document (the
    # official template has no numbered-list disposition), and carries
    # its own legal basis / образложење — see the variant-specific
    # branches below.
    is_chairman_lapse_doc = (
        not is_prosireni and bool(spec.records)
        and record_variant(spec.records[0]) == "chairman_lapse"
    )

    if is_prosireni:
        subtitle = (
            "О ИЗМЕНАМА РЕШЕЊА О ИМЕНОВАЊУ ЧЛАНОВА И ЗАМЕНИКА ЧЛАНОВА БИРАЧКОГ ОДБОРА"
        )
        composition_upper = "У ПРОШИРЕНОМ САСТАВУ"
        composition_lower = "проширеном саставу"
    else:
        subtitle = (
            "О ИЗМЕНИ" if is_chairman_lapse_doc else "О ИЗМЕНАМА"
        ) + (
            " РЕШЕЊА О ИМЕНОВАЊУ ПРЕДСЕДНИКА И ЧЛАНОВА БИРАЧКОГ ОДБОРА"
            " И ЊИХОВИХ ЗАМЕНИКА"
        )
        composition_upper = "У СТАЛНОМ САСТАВУ"
        composition_lower = "сталном саставу"

    auth_number = doc_info.authorization_number
    auth_date = doc_info.authorization_date
    auth_name = doc_info.authorized_name
    auth_role = doc_info.authorized_role
    issue_date = spec.issue_date

    if use_authorization:
        signer_name = auth_name
        signer_role = auth_role or "овлашћено лице"
    else:
        signer_name = oik.chairman.name
        signer_role = oik.chairman.title or "председник"

    amendment_broj = format_amendment_broj(
        spec.original_broj, spec.amendment_index, spec.amendment_counter
    )
    bm_num_str = str(spec.bm_number)

    doc = Document()

    # A4 page; ~2cm margins
    section = doc.sections[0]
    section.page_width = _twips(11906)
    section.page_height = _twips(16838)
    section.top_margin = _twips(1134)
    section.right_margin = _twips(1134)
    section.bottom_margin = _twips(1701)
    section.left_margin = _twips(1134)

    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(BODY_PT)
    apply_document_format(doc, oik)
    rpr = style.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(attr), FONT)

    CENTER = WD_ALIGN_PARAGRAPH.CENTER
    JUSTIFY = WD_ALIGN_PARAGRAPH.JUSTIFY

    # ── Legal basis preamble ─────────────────────────────────────────────────
    auth_ref = f"број {auth_number} од {auth_date}" if (auth_number and use_authorization) else ""
    if is_chairman_lapse_doc:
        # Always the чл. 41. ст. 2. citation — never the operator's
        # generic Правни основ text, which is written for ст. 1 and
        # would misstate which provision actually authorizes this one.
        # Text lives in resources/izmena_chairman_lapse_defaults.json —
        # see _chairman_lapse_defaults().
        chairman_lapse_legal_basis, _ = _chairman_lapse_defaults()
        _add_para(doc, chairman_lapse_legal_basis, align=JUSTIFY)
    elif legal_basis.strip():
        # User-edited plain-text preamble
        for line in legal_basis.strip().splitlines():
            if line.strip():
                _add_para(doc, line.strip(), align=JUSTIFY)
    else:
        # Hardcoded default
        _add_mixed_para(doc, [
            ("На основу члана 32. тачка 2) и ", False),
            (law_article, True),
            (" и 41. Закона о избору народних посланика"
             " (\"Службени гласник РС\", бр. 35/00, 57/03-УС, 72/11-др.закон, 18/04,"
             " 85/05-др.закон, 101/05-др.закон, 104/09-др.закон, 28/11-УС, 36/11,"
             " 12/20, 68/20 и 14/22)", False),
            (f" и\nРешења о давању овлашћења члана Комисије за доношење решења о"
             " промени састава бирачким одбором "
             if auth_ref else "", False),
            (auth_ref, True),
            (",", False),
        ], align=JUSTIFY)

    _add_mixed_para(doc, [
        (f"овлашћено лице {terms.head_gen} {terms.unit_word_gen} ", False),
        (terms.unit_name_gen, True),
        (f", {issue_date}" if issue_date else "", False),
        (", доноси", False),
    ], align=JUSTIFY)

    # ── Title block ──────────────────────────────────────────────────────────
    _add_para(doc, "Р Е Ш Е Њ Е", bold=True, size_pt=TITLE_PT,
              align=CENTER, space_before_pt=6, space_after_pt=0)
    _add_para(doc, subtitle, bold=True, align=CENTER, space_after_pt=0)
    _add_para(doc, f"- {composition_upper} -", bold=True, align=CENTER)
    _add_para(doc)

    _add_para(doc, f"ЗА БИРАЧКО МЕСТО БРОЈ {bm_num_str}. {terms.in_unit.upper()}",
              bold=True, align=CENTER, space_after_pt=0)
    _add_para(doc, spec.bm_name.upper(), bold=True, align=CENTER)
    _add_para(doc)

    # ── Disposition ──────────────────────────────────────────────────────────
    chairman_lapse_proposal = ""
    if is_chairman_lapse_doc:
        rec = spec.records[0]
        chairman_lapse_proposal = _party_proposal_text(
            rec.party, election, spec.slug, issue_date, oik.nacelnik_proposal_name,
            appointed_by_nacelnik=rec.appointed_by_nacelnik,
        )
        # One continuous sentence — the official "1 3" template has no
        # colon + numbered-item split, unlike the generic ст. 1 track.
        _add_mixed_para(doc, [
            ("1. Мења се Решење о именовању председника и чланова бирачког одбора и"
             f" њихових заменика у {composition_lower} за бирачко место број ", False),
            (f"{bm_num_str}.", True),
            (f" {terms.in_unit}, ", False),
            (f"број {spec.original_broj} од {spec.original_date}", True),
            (", тако што се у бирачки одбор, уместо ", False),
            (rec.old_name, True),
            (", за ", False),
            (rec.function, True),
            (" именује: ", False),
            (rec.new_name, True),
            (f" из {rec.new_place} ", False),
            (chairman_lapse_proposal, False),
            (".", False),
        ], align=JUSTIFY)
    else:
        _add_mixed_para(doc, [
            ("1. Мења се Решење о именовању председника и чланова бирачког одбора и"
             f" њихових заменика у {composition_lower} за бирачко место број ", False),
            (f"{bm_num_str}.", True),
            (f" {terms.in_unit}, ", False),
            (f"број {spec.original_broj} од {spec.original_date}", True),
            (", тако што се у бирачки одбор:", False),
        ], align=JUSTIFY)

        for i, rec in enumerate(spec.records, start=1):
            if rec.is_correction:
                _add_mixed_para(doc, _correction_segments(i, rec), align=JUSTIFY)
                continue
            proposal = _party_proposal_text(
                rec.party, election, spec.slug, issue_date, oik.nacelnik_proposal_name,
                appointed_by_nacelnik=rec.appointed_by_nacelnik,
            )
            _add_mixed_para(doc, [
                (f"{i}) уместо ", False),
                (rec.old_name, True),
                (", за ", False),
                (rec.function, True),
                (" именује: ", False),
                (rec.new_name, True),
                (f" из {rec.new_place} ", False),
                (proposal, False),
                (";", False),
            ], align=JUSTIFY)

    _add_para(doc, "2. Ово решење објавити у Службеном гласнику Републике Србије.",
              align=JUSTIFY)
    _add_para(doc, "3. Решење је коначно и примењује се одмах.", align=JUSTIFY)

    # ── Образложење ──────────────────────────────────────────────────────────
    # page_break_before matches the original resenja (phase3_docx) -- without
    # it, Образложење ran on directly after Item 3 on the same page instead
    # of starting fresh on page 2 (field report).
    obr_heading = _add_para(doc, "О б р а з л о ж е њ е", bold=True, align=CENTER, space_before_pt=12)
    obr_heading.paragraph_format.page_break_before = True

    if is_chairman_lapse_doc:
        # Always the чл. 41. ст. 2. rationale — never the operator's
        # customized cards/fallback, which are written for the generic
        # ст. 1 "proposer's request" track and don't name death/illness/
        # loss-of-voting-right as grounds at all. Text lives in
        # resources/izmena_chairman_lapse_defaults.json — see
        # _chairman_lapse_defaults().
        _, chairman_lapse_paragraphs = _chairman_lapse_defaults()
        rendered = render_izmena_obrazlozenje(
            list(chairman_lapse_paragraphs),
            use_authorization=use_authorization,
            auth_ref=auth_ref, auth_name=auth_name, auth_role=auth_role,
            opstina=mun_name,
            commission=terms,
        )
        for para_segments in rendered:
            _add_mixed_para(doc, para_segments, align=JUSTIFY)
    elif rendered_obrazlozenje is not None:
        for para_segments in rendered_obrazlozenje:
            _add_mixed_para(doc, para_segments, align=JUSTIFY)
    else:
        # No obraz_path given (e.g. corrections.py's auto-generate-on-save
        # path) — fall back to the same bundled official text the cards
        # system seeds from, rather than a separate hardcoded copy that
        # would silently drift out of sync with it (as the old inline
        # fallback here had).
        from biracki_odbor.config.obrazlozenje import _from_json
        fallback_paragraphs = _from_json({"paragraphs": seed_izmena_paragraphs(spec.slug)})
        rendered = render_izmena_obrazlozenje(
            fallback_paragraphs,
            use_authorization=use_authorization,
            auth_ref=auth_ref, auth_name=auth_name, auth_role=auth_role,
            opstina=mun_name,
            commission=terms,
        )
        for para_segments in rendered:
            _add_mixed_para(doc, para_segments, align=JUSTIFY)

    # ── Signature block ───────────────────────────────────────────────────────
    try:
        from biracki_odbor.config.declension import place_preposition, place_to_genitive
        prep = place_preposition(mun_name)
        gen = place_to_genitive(mun_name)
        place_line = f"{prep} {gen}, {issue_date}" if issue_date else f"{prep} {gen}"
    except Exception:
        place_line = f"У {mun_name}, {issue_date}"

    _add_para(doc, f"{amendment_broj},", space_before_pt=12, align=JUSTIFY)
    _add_para(doc, place_line, align=JUSTIFY)
    _add_para(doc, space_before_pt=24)
    _add_para(doc, " ".join(terms.signature_lines), align=CENTER)
    _add_para(doc, signer_role, align=CENTER)

    # Blank signature line — same technique as phase3_docx's original
    # resenja: an empty 1x1 table with only the bottom border visible,
    # is where the signer actually signs by hand. Without it (field
    # report), the printed name rendered with nothing to sign above.
    if signer_name:
        sig_tbl = doc.add_table(rows=1, cols=1)
        sig_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        sig_tbl.columns[0].width = _twips(2722)
        sig_cell = sig_tbl.rows[0].cells[0]
        sig_cell.width = _twips(2722)
        _set_cell_borders(sig_cell, top=False, bottom=True, left=False, right=False)
        sig_para = sig_cell.paragraphs[0]
        sig_para.paragraph_format.space_before = Pt(0)
        sig_para.paragraph_format.space_after = Pt(0)

    _add_para(doc, signer_name.upper(), bold=True, align=CENTER)

    return doc


def generate_izmena(
    spec: IzmenaSpec,
    oik: OikConstants,
    election: ElectionConfig,
    output_dir: Path,
    *,
    obraz_path: Path | None = None,
) -> Path:
    """Write amendment document to `output_dir` and return the file path.

    When `obraz_path` is given, the obrazlozenje paragraphs are loaded from
    that path (seeding from the bundled defaults on first run) and passed
    to build_izmena_document() as pre-rendered segments.
    """
    doc_info = election.document
    use_auth = doc_info.use_authorization
    legal_basis = (
        doc_info.izmena_legal_basis_prosireni
        if spec.slug == "prosireni"
        else doc_info.izmena_legal_basis_stalni
    )

    rendered: list[list[tuple[str, bool]]] | None = None
    if obraz_path is not None:
        paragraphs = load_izmena_obrazlozenje(spec.slug, obraz_path)
        auth_ref = (
            f"број {doc_info.authorization_number}"
            f" од {doc_info.authorization_date}"
            if doc_info.authorization_number and use_auth else ""
        )
        rendered = render_izmena_obrazlozenje(
            paragraphs,
            use_authorization=use_auth,
            auth_ref=auth_ref,
            auth_name=doc_info.authorized_name,
            auth_role=doc_info.authorized_role,
            opstina=oik.municipality.name,
            commission=commission_terms(oik.municipality),
        )

    slug_tag = "STALNI" if spec.slug == "stalni" else "PROSIRENI"
    filename = (
        f"БМ_{spec.bm_number:02d}_{slug_tag}"
        f"_izmena_{spec.amendment_index:02d}.docx"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / filename
    doc = build_izmena_document(
        spec, oik, election,
        rendered_obrazlozenje=rendered,
        legal_basis=legal_basis,
        use_authorization=use_auth,
    )
    doc.save(out_path)
    return out_path
