"""Persistent cache + allowlist for files imported into popunjeni/.

Two concerns folded into one module:

  1. **Allowlist:** the set of file paths in `popunjeni/` the Phase 2
     aggregator is allowed to read. A path is in the allowlist iff it has
     a cache entry. Files dropped manually into the folder (bypassing the
     import button) are NOT in the cache, surface as `UNIMPORTED_FILE`
     warnings, and are not aggregated.

  2. **Parse cache:** for files in the allowlist, the cache stores their
     mtime+size fingerprint and pre-parsed records. When mtime+size still
     match on the next Phase 2 run, the cached records are used directly
     and the .xlsx is never re-opened.

The cache is scoped to a single election cycle via `election_uuid`. A
mismatch at load time wipes the cache (last election's entries don't apply
to this election).

Storage: JSON at `<BIRACKI_ODBOR_HOME>/cache/popunjeni.json`, atomic write
via `.tmp + rename`. Corruption is non-fatal — a malformed cache file is
treated as empty and rebuilt on next save.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from biracki_odbor.core.models import Issue, Person


log = logging.getLogger(__name__)

# v2 (2026-05-30) added received_time_iso + import_source. Old v1 cache
# entries deserialize cleanly because the new fields default to ""
# / "file_picker" via .get() fallback in load() — older cached imports
# are treated as "earliest possible time, source unknown", so the first
# fresh import per party always wins on aggregate's max(received_time).
_VERSION = 2


@dataclass
class CacheEntry:
    """Per-file cache record."""

    mtime_ns: int
    size: int
    # Records as a list of {bm, function, person_dict} so JSON-friendly.
    records: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    # The ReceivedTime from the source email (when import_source is
    # "outlook"), or the operator's clock at import (when source is
    # "file_picker"). Stored as ISO 8601 (UTC, no microseconds) so it
    # sorts lexicographically the same way it sorts as a real datetime.
    # Empty string for legacy v1 cache entries.
    received_time_iso: str = ""
    # Which ingress path produced this entry. Surfaced in the
    # accountability log so the OIK can show provenance per submission.
    import_source: str = "file_picker"
    # The party name extracted from the M1 marker at import time.
    # Cached here so the Phase 2 "pick latest per party" group-by step
    # doesn't have to re-open the .xlsx for the marker.
    party: str = ""
    # Windows username of the operator who performed the import.
    # Captured so the accountability log can show provenance
    # (who imported the file, when, from what source). Empty for v1
    # cache entries that predate this field.
    imported_by: str = ""

    def to_records_tuples(self) -> list[tuple[tuple[int, str], Person]]:
        # Normalize the "Заменик клана" typo here too: a file imported
        # (and cached) before the 2026-10-12 fix has its old spelling
        # frozen into `records` forever, since a cache hit means the
        # .xlsx is never re-opened/re-parsed. Without this, every such
        # cached zamenik row silently mismatches the now-corrected
        # allocation keys on the next aggregation and gets dropped as
        # "unfilled" -- see master_io.py's schema v3 migration, which
        # fixes committee.db rows but can't reach this cache.
        from biracki_odbor.core.prosireni_allocation import normalize_function_typo
        out: list[tuple[tuple[int, str], Person]] = []
        for r in self.records:
            try:
                bm = int(r["bm"])
                func = normalize_function_typo(str(r["function"]))
                person = Person.from_dict(r["person"])
                person.function = normalize_function_typo(person.function)
            except (KeyError, TypeError, ValueError):
                continue
            out.append(((bm, func), person))
        return out

    def to_issues_list(self) -> list[Issue]:
        out: list[Issue] = []
        for i in self.issues:
            try:
                out.append(Issue(
                    code=str(i.get("code", "")),
                    message_sr=str(i.get("message_sr", "")),
                    severity=str(i.get("severity", "error")),
                    file=str(i.get("file", "")),
                    sheet=str(i.get("sheet", "")),
                    row=i.get("row"),
                    column=i.get("column"),
                    detail=str(i.get("detail", "")),
                ))
            except (TypeError, ValueError):
                continue
        return out

    @classmethod
    def from_parsed(
        cls,
        path: Path,
        records: list[tuple[tuple[int, str], Person]],
        issues: list[Issue],
        *,
        received_time_iso: str = "",
        import_source: str = "file_picker",
        party: str = "",
        imported_by: str = "",
    ) -> "CacheEntry":
        st = path.stat()
        return cls(
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            records=[
                {"bm": bm, "function": func, "person": person.to_dict()}
                for (bm, func), person in records
            ],
            issues=[i.to_dict() for i in issues],
            received_time_iso=received_time_iso,
            import_source=import_source,
            party=party,
            imported_by=imported_by,
        )


@dataclass
class CacheData:
    election_uuid: str = ""
    entries: dict[str, CacheEntry] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "version": _VERSION,
            "election_uuid": self.election_uuid,
            "entries": {
                path: asdict(entry) for path, entry in self.entries.items()
            },
        }


# ── Path resolution ───────────────────────────────────────────────


def cache_path() -> Path:
    """Return path to the popunjeni cache JSON. Imports lazily so the module
    is importable from test contexts without a fully-initialized app_paths."""
    from biracki_odbor import app_paths
    return app_paths.popunjeni_cache_path()


# ── Load / save ───────────────────────────────────────────────────


def load(election_uuid: str = "") -> CacheData:
    """Read the cache JSON. Returns an empty CacheData if:
      - file is missing
      - JSON is corrupt
      - version doesn't match
      - stored election_uuid doesn't match `election_uuid` (when caller
        passes one; pass "" to skip the scope check)

    A wrong-election cache isn't an error condition — it just means the
    cache was built for a different cycle and shouldn't be reused.
    """
    path = cache_path()
    if not path.exists():
        return CacheData(election_uuid=election_uuid)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("popunjeni_cache.load: %s unreadable (%s); starting fresh", path, e)
        return CacheData(election_uuid=election_uuid)
    raw_version = raw.get("version")
    # v1 caches load forward — the new fields just default to empty.
    # Anything older or newer than our supported range gets reset.
    if raw_version not in (1, _VERSION):
        log.info(
            "popunjeni_cache.load: version %s outside [1,%s]; starting fresh",
            raw_version, _VERSION,
        )
        return CacheData(election_uuid=election_uuid)
    stored_uuid = str(raw.get("election_uuid", ""))
    if election_uuid and stored_uuid != election_uuid:
        log.info(
            "popunjeni_cache.load: election_uuid mismatch (stored=%s, "
            "current=%s) — discarding cache",
            stored_uuid, election_uuid,
        )
        return CacheData(election_uuid=election_uuid)
    entries: dict[str, CacheEntry] = {}
    for path_str, entry_dict in (raw.get("entries") or {}).items():
        if not isinstance(entry_dict, dict):
            continue
        try:
            entries[path_str] = CacheEntry(
                mtime_ns=int(entry_dict.get("mtime_ns", 0)),
                size=int(entry_dict.get("size", 0)),
                records=list(entry_dict.get("records") or []),
                issues=list(entry_dict.get("issues") or []),
                # Defaults preserve v1 cache compatibility (these fields
                # didn't exist before v2).
                received_time_iso=str(entry_dict.get("received_time_iso", "")),
                import_source=str(entry_dict.get("import_source", "file_picker")),
                party=str(entry_dict.get("party", "")),
                imported_by=str(entry_dict.get("imported_by", "")),
            )
        except (TypeError, ValueError):
            continue
    return CacheData(election_uuid=stored_uuid or election_uuid, entries=entries)


def save(data: CacheData) -> None:
    """Atomic write of the cache JSON (.tmp + rename)."""
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data.to_json_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ── Hit/miss ──────────────────────────────────────────────────────


def hit(file_path: Path, entry: CacheEntry | None) -> bool:
    """True iff `file_path`'s current stat matches the cached fingerprint.

    Returns False when:
      - entry is None (file not in cache → allowlist miss)
      - file doesn't exist on disk
      - mtime_ns differs (file was modified)
      - size differs (file content changed even if mtime didn't)
    """
    if entry is None:
        return False
    p = Path(file_path)
    if not p.exists():
        return False
    try:
        st = p.stat()
    except OSError:
        return False
    return st.st_mtime_ns == entry.mtime_ns and st.st_size == entry.size


# ── Prune ─────────────────────────────────────────────────────────


def prune_missing(data: CacheData) -> list[str]:
    """Remove cache entries for files that no longer exist on disk.

    Returns the list of pruned paths (for logging). Mutates `data` in place.
    """
    removed: list[str] = []
    for path_str in list(data.entries.keys()):
        if not Path(path_str).exists():
            removed.append(path_str)
            del data.entries[path_str]
    if removed:
        log.info("popunjeni_cache.prune_missing: dropped %d entries", len(removed))
    return removed


# ── Per-party lookup ──────────────────────────────────────────────


def latest_submission_path_for_party(election_uuid: str, party: str) -> Path | None:
    """Return the most recently received on-disk submission for `party`,
    or None if it has no cached submission this cycle.

    Same "pick latest by received_time_iso" rule Phase 2's aggregator
    uses (see phase2_aggregate.py) — kept as its own small helper here
    rather than reusing the aggregator's inline version, since that one
    is embedded in a larger report-building loop. Used by the
    Корекције → Сви чланови "reply email" feature to attach the exact
    file a party submitted, not a re-derived export.
    """
    data = load(election_uuid=election_uuid)
    candidates = [
        (Path(path_str), entry)
        for path_str, entry in data.entries.items()
        if entry.party == party
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[1].received_time_iso or "")
    latest_path = candidates[-1][0]
    return latest_path if latest_path.exists() else None


def latest_submission_received_time_for_party(election_uuid: str, party: str) -> str:
    """Return the ISO 8601 received_time_iso of the latest cached submission
    for `party`, or "" if it has no cached submission this cycle.

    Same "pick latest by received_time_iso" rule as
    latest_submission_path_for_party, split out separately since a
    caller that only wants the timestamp (Корекције's conflict cards —
    see core.corrections.detect_conflicts) shouldn't have to stat a
    path it never uses.
    """
    data = load(election_uuid=election_uuid)
    times = [
        entry.received_time_iso
        for entry in data.entries.values()
        if entry.party == party and entry.received_time_iso
    ]
    return max(times) if times else ""
