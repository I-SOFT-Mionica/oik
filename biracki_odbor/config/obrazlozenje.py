"""User-editable obrazloženje (Phase 3 решење explanation) template.

The obrazloženje block in решења used to live as a hardcoded list inside
[phase3_docx.py](../core/phase3_docx.py). When the underlying laws change
or a user wants to omit the parenthetical "АКО НЕКА ПОСЛАНИЧКА ГРУПА…"
paragraph for their specific election, they had no way to do so without
editing the source.

This module turns the obrazloženje into a CMS-style seeded user file:

  - On first run, the seed template (current legal text, accurate as of
    2026) is written to `<BIRACKI_ODBOR_HOME>/obrazlozenje.json`.
  - After that, the user owns the file. App updates never overwrite it.
  - Phase 3 calls `render(election, oik)` to get the paragraph-segments
    structure with placeholders (`{rik_decision}`, `{municipality}`) filled
    in. The output shape matches what `_add_mixed_para` expects:
    `list[list[tuple[text, bold]]]`.

See [[feedback_customization_pattern]] memory for the principle.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)

_VERSION = 1


@dataclass
class Segment:
    text: str = ""
    bold: bool = False


@dataclass
class Paragraph:
    id: str = ""
    segments: list[Segment] = field(default_factory=list)
    # `optional` is informational — describes which paragraphs are
    # conditional in the legal sense. Phase 3 always renders every
    # paragraph in the file; users who want to omit one delete it from
    # their JSON (or move it under a different id and skip).
    optional: bool = False


# In-memory cache. Invalidated when set_paragraphs writes.
_cache: list[Paragraph] | None = None
_cache_path: Path | None = None


def _file_path() -> Path:
    from biracki_odbor import app_paths
    return app_paths.obrazlozenje_path()


@lru_cache(maxsize=2)
def _load_bundled_seed(resource_name: str) -> tuple[Paragraph, ...]:
    """Read one of the bundled seed JSON resources, parsed into Paragraphs.

    Cached — these are read-only package resources, re-parsing them on
    every call would be pure waste.
    """
    raw = resources.files("biracki_odbor.resources").joinpath(resource_name).read_text(
        encoding="utf-8",
    )
    return tuple(_from_json(json.loads(raw)))


def default_paragraphs(path: Path | None = None) -> list[Paragraph]:
    """The canonical (shipped-with-the-app) obrazloženje for `path`'s
    workflow — what a fresh install seeds with, and what "Врати на
    подразумевано" restores. Public so callers never need the private
    `_seed_for` resource-name mapping directly."""
    return list(_seed_for(path if path is not None else _file_path()))


def _seed_for(path: Path) -> list[Paragraph]:
    """Pick the right seed set for `path` -- stalni's obrazlozenje.json
    and prosireni's obrazlozenje_prosireni.json cite different articles
    and must not share a seed."""
    resource_name = (
        "obrazlozenje_prosireni_defaults.json" if path.name == "obrazlozenje_prosireni.json"
        else "obrazlozenje_defaults.json"
    )
    return list(_load_bundled_seed(resource_name))


def _to_json(paragraphs: list[Paragraph]) -> dict[str, Any]:
    return {
        "_comment": (
            "Текст образложења који се уноси у Phase 3 решења. "
            "Кодови: {odluka_rik} (Одлука РИК-а), {opstina} (назив општине), "
            "{pod_stalni} (рок подношења за стални), {pod_prosireni} (рок за проширени), "
            "{dana_predlog} (број дана до рока за предлог), "
            "{dana_imenovanje} (број дана до рока за именовање). "
            "Болд се контролише за сваки сегмент посебно. Поље optional описује "
            "да ли је параграф услован у правном смислу — програм га свеједно "
            "увек рендерује; ако желите да га искључите, обришите тај параграф."
        ),
        "version": _VERSION,
        "paragraphs": [
            {
                "id": p.id,
                "optional": p.optional,
                "segments": [{"text": s.text, "bold": s.bold} for s in p.segments],
            }
            for p in paragraphs
        ],
    }


def _from_json(raw: dict[str, Any]) -> list[Paragraph]:
    out: list[Paragraph] = []
    for entry in raw.get("paragraphs", []) or []:
        if not isinstance(entry, dict):
            continue
        segments = []
        for s in entry.get("segments", []) or []:
            if not isinstance(s, dict):
                continue
            segments.append(Segment(
                text=str(s.get("text", "")),
                bold=bool(s.get("bold", False)),
            ))
        out.append(Paragraph(
            id=str(entry.get("id", "")),
            segments=segments,
            optional=bool(entry.get("optional", False)),
        ))
    return out


def _seed_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_json(_seed_for(path)), f, ensure_ascii=False, indent=2)
    log.info("seeded obrazlozenje template at %s", path)


def load(force: bool = False, path: Path | None = None) -> list[Paragraph]:
    """Read the user's obrazloženje template. Seeds the file on first run.

    `path` overrides the default location so the same module can serve
    both the стални (obrazlozenje.json) and проширени
    (obrazlozenje_prosireni.json) templates without separate modules.
    """
    global _cache, _cache_path
    if path is None:
        path = _file_path()
    if not force and _cache is not None and _cache_path == path:
        return _cache
    if not path.exists():
        _seed_file(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("obrazlozenje.load: %s unreadable (%s) — falling back to seed", path, e)
        _cache = list(_seed_for(path))
        _cache_path = path
        return _cache
    if raw.get("version") != _VERSION:
        log.info(
            "obrazlozenje.load: version %s != %s — falling back to seed",
            raw.get("version"), _VERSION,
        )
        _cache = list(_seed_for(path))
        _cache_path = path
        return _cache
    paragraphs = _from_json(raw)
    if not paragraphs:
        # Empty paragraphs list would render an empty obrazloženje section —
        # treat as malformed and fall back to seed.
        log.warning("obrazlozenje.load: empty paragraphs in %s — using seed", path)
        _cache = list(_seed_for(path))
        _cache_path = path
        return _cache
    paragraphs = _ensure_legal_remedy_paragraph(paragraphs, path)
    _cache = paragraphs
    _cache_path = path
    return _cache


_LEGAL_REMEDY_ID = "uputstvo-pravno-sredstvo"


def _ensure_legal_remedy_paragraph(paragraphs: list[Paragraph], path: Path) -> list[Paragraph]:
    """Migration for files saved before УПУТСТВО О ПРАВНОМ СРЕДСТВУ became
    a normal editable paragraph here -- it used to be hardcoded directly
    in core/phase3_docx.py, outside the template entirely, so an
    operator's existing obrazlozenje.json has no way to already contain
    it. Appends it (persisted immediately, not just in memory) rather
    than bumping `_VERSION`, since a version mismatch in `load()` above
    discards the WHOLE file back to the seed -- this only adds the one
    paragraph the operator never had a chance to remove or edit, leaving
    every other customization untouched.

    Re-adds it every time it's absent, including if an operator removes
    it on purpose later -- there's no way to tell "this file predates
    the migration" apart from "deliberately removed", and given this
    text is a legally required instruction on an official decision,
    defaulting to "always present" is the safer of the two guesses. An
    operator who genuinely needs to omit/replace it should blank its
    segments rather than delete the paragraph.

    Scoped to Phase 3's own two files (obrazlozenje.json,
    obrazlozenje_prosireni.json) -- `load()` is shared infrastructure
    also used for izmene's izmena_obrazlozenje_{slug}.json files, which
    already have their OWN legal-remedy paragraph under a different id
    ("pravna-pouka") and must never get this one injected too. Checking
    the id alone isn't enough: _seed_for() falls back to the stalni
    phase3 seed for any unrecognized filename, so without this guard an
    izmene file would get this wrong (phase3-worded) paragraph appended
    as a spurious duplicate the one time the ids didn't match."""
    if path.name not in ("obrazlozenje.json", "obrazlozenje_prosireni.json"):
        return paragraphs
    if any(p.id == _LEGAL_REMEDY_ID for p in paragraphs):
        return paragraphs
    seed_remedy = next(
        (p for p in _seed_for(path) if p.id == _LEGAL_REMEDY_ID), None,
    )
    if seed_remedy is None:
        return paragraphs
    migrated = paragraphs + [seed_remedy]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_to_json(migrated), f, ensure_ascii=False, indent=2)
        tmp.replace(path)
        log.info(
            "obrazlozenje.load: migrated %s — added missing legal-remedy paragraph", path,
        )
    except OSError:
        log.exception(
            "obrazlozenje.load: could not persist legal-remedy migration for %s", path,
        )
    return migrated


def save(paragraphs: list[Paragraph], path: Path | None = None) -> None:
    if path is None:
        path = _file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_to_json(paragraphs), f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    load(force=True, path=path)


# ── Markdown helpers (for the in-app editor) ──────────────────────


_BOLD_SPAN_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def parse_markdown_paragraph(text: str) -> list[Segment]:
    """Split a paragraph into Segments using `**...**` bold markers.

    The editor stores each paragraph's text as a single string with
    `**bold**` markers (familiar from chat apps). At save time we split
    on the markers to produce the structured `Segment` list. Bold runs
    inside other bold runs aren't supported — `**` toggles in/out only.

    Empty input returns a single empty non-bold segment so callers can
    always assume at least one segment exists.
    """
    if not text:
        return [Segment("", bold=False)]
    out: list[Segment] = []
    cursor = 0
    for m in _BOLD_SPAN_RE.finditer(text):
        if m.start() > cursor:
            out.append(Segment(text[cursor:m.start()], bold=False))
        out.append(Segment(m.group(1), bold=True))
        cursor = m.end()
    if cursor < len(text):
        out.append(Segment(text[cursor:], bold=False))
    # Drop trailing empty non-bold segments (cosmetic — keeps round-trip
    # tight: `"**X**"` → [Segment("X", True)], not [Segment("X", True), Segment("", False)]).
    while out and out[-1].text == "" and not out[-1].bold:
        out.pop()
    return out or [Segment("", bold=False)]


def render_paragraph_markdown(segments: list[Segment]) -> str:
    """Inverse of `parse_markdown_paragraph`: rejoin segments to a string.

    Bold segments get wrapped in `**...**`; non-bold pass through. Empty
    segments are skipped. Adjacent same-kind segments stay separate
    (intentional — preserves explicit author intent in the JSON).
    """
    parts: list[str] = []
    for seg in segments:
        if not seg.text:
            continue
        if seg.bold:
            parts.append(f"**{seg.text}**")
        else:
            parts.append(seg.text)
    return "".join(parts)


# Paragraphs that cite the Law on Local Elections (чл. 89/91/92) — only
# true when THIS election's national vote coincides with a local election
# (ElectionInfo.types contains "local", same check gui/main_window.py
# uses to gate Посматрачи). Marked optional in the seed so they stay
# dormant by default — "right now no one has them, but that doesn't make
# the case impossible" — and un-skipped here specifically when that's
# actually the case, rather than always-on or purely manual.
_LOCAL_ELECTION_PARAGRAPH_IDS = frozenset({
    "zajednicki-izbori", "lokalni-sprovode-stalni", "predlaganje-lokalni-prosireni",
})


def commission_placeholders(commission, municipality: str = "") -> dict[str, str]:
    """{komisija_dat}/{komisija_gen} for the editable texts. Without
    explicit terms, a municipality (ОИК) is assumed -- every install
    before cities were supported."""
    if commission is None:
        from biracki_odbor.config.commission import terms_for
        from biracki_odbor.config.opstine import VRSTA_OPSTINA
        commission = terms_for(VRSTA_OPSTINA, municipality)
    return {
        "komisija": commission.subject,
        "komisija_dat": commission.dative_with_place,
        "komisija_gen": commission.subject_gen,
    }


def render(
    rik_decision: str,
    municipality: str,
    days_before_proposal: int = 15,
    days_before_appointment: int = 10,
    cutoff_stalni: str = "",
    cutoff_prosireni: str = "",
    municipality_website: str = "",
    local_elections: bool = False,
    path: Path | None = None,
    commission=None,
) -> list[list[tuple[str, bool]]]:
    """Return the obrazloženje in the (text, bold)-tuple shape Phase 3 expects.

    Substitutes placeholders into each segment's text. `path` selects which
    workflow's template to read — defaults to the стални template
    (`obrazlozenje.json`) if omitted; pass
    `app_paths.obrazlozenje_path_for(spec)` for проширени so the same
    workflow separation used everywhere else (master files, corrections,
    izmene) also applies to the решење's Образложење text.

    `local_elections`: True when this election coincides with a local
    election — un-skips the чл. 89/91/92 paragraphs (see
    `_LOCAL_ELECTION_PARAGRAPH_IDS`) even though they're marked optional.

    Current (Serbian-friendly) names:
      {odluka_rik}      — ElectionInfo.rik_decision
      {opstina}         — OIK municipality name
      {pod_stalni}      — stalni nomination cutoff, Serbian genitive date
      {pod_prosireni}   — prošireni nomination cutoff, Serbian genitive date
      {dana_predlog}    — days between pod_stalni and election date
      {dana_imenovanje} — days between pod_prosireni and election date
      {municipality_website} — Municipality.website (config/oik.py)
      {komisija_dat}    — "Општинској изборној комисији у општини X" /
                          "Градској изборној комисији у граду X" / … (commission)
      {komisija_gen}    — "Општинске изборне комисије" / "Градске …" / …
      {komisija}        — "Општинска изборна комисија" / "Градска …" / …

    Legacy aliases (kept for backward-compat with existing user JSON files):
      {rik_decision}, {municipality}, {cutoff_stalni}, {cutoff_prosireni},
      {days_before_proposal}, {days_before_appointment}

    Any unrecognised braces are passed through unchanged so a user who
    accidentally types literal braces won't crash the render.
    """
    paragraphs = load(path=path)
    ctx = {
        # Current Serbian-friendly names
        "odluka_rik": rik_decision or "",
        "opstina": municipality or "",
        "pod_stalni": cutoff_stalni or "",
        "pod_prosireni": cutoff_prosireni or "",
        "dana_predlog": days_before_proposal,
        "dana_imenovanje": days_before_appointment,
        "municipality_website": municipality_website or "",
        **commission_placeholders(commission, municipality or ""),
        # Legacy aliases — keep old user JSON files working
        "rik_decision": rik_decision or "",
        "municipality": municipality or "",
        "cutoff_stalni": cutoff_stalni or "",
        "cutoff_prosireni": cutoff_prosireni or "",
        "days_before_proposal": days_before_proposal,
        "days_before_appointment": days_before_appointment,
    }
    out: list[list[tuple[str, bool]]] = []
    for p in paragraphs:
        if p.optional and not (local_elections and p.id in _LOCAL_ELECTION_PARAGRAPH_IDS):
            continue   # optional=True means hidden/excluded by default
        rendered: list[tuple[str, bool]] = []
        for seg in p.segments:
            try:
                text = seg.text.format(**ctx)
            except (KeyError, IndexError, ValueError):
                # Treat unknown placeholders / malformed braces as literal text.
                text = seg.text
            rendered.append((text, seg.bold))
        if rendered:
            out.append(rendered)
    return out


def active_paragraph_ids(path: Path | None = None, *, local_elections: bool = False) -> list[str]:
    """IDs of paragraphs `render()` actually includes, in the same order
    as `render()`'s own output list.

    `render()` silently drops `optional` paragraphs whose condition isn't
    met (see the loop above) — so its output can be SHORTER than, and at
    different positions from, the full paragraph list `load()` returns
    (which is what the editor's cards are built from, one card per
    paragraph, optional or not). A caller matching cards to rendered
    output by plain position (card N -> rendered item N) silently
    misaligns the moment any optional paragraph sits before the one it's
    trying to reach — this is that correspondence, computed with the
    exact same predicate render() uses, so a caller can zip it against
    render()'s output and always get the right paragraph id for a given
    rendered item.
    """
    paragraphs = load(path=path)
    return [
        p.id for p in paragraphs
        if not (p.optional and not (local_elections and p.id in _LOCAL_ELECTION_PARAGRAPH_IDS))
    ]
