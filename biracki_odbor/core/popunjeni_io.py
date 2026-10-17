"""Import, parse, and safety pipeline for party-returned .xlsx files.

This module is the single ingress point for `popunjeni/`. It does three things:

1. **Safety pipeline** (`check_file_safety`) — pre-parse rejection of
   malicious or malformed .xlsx files. Caps file size, refuses VBA macros,
   refuses embedded OLE objects, refuses external-link sheets, refuses
   suspicious compression ratios (zip-bomb defense).
2. **Identity validation** (`read_marker`) — reads the hidden+locked
   marker cell stamped into Phase 1 output, validates it belongs to the
   current election cycle, and derives the canonical filename.
3. **Parse + import** (`parse_party_file`, `import_file`) — once a file
   passes safety + identity checks, parses rows into `Person` records
   (this is the same logic the legacy `_read_party_file` in
   `phase2_aggregate.py` used) and copies the file to `popunjeni/` at
   the canonical path, overwriting any prior version.

The Phase 2 aggregator no longer touches files directly — it consults
`popunjeni_cache` (which is populated by `import_file` here) for the set
of files it's allowed to aggregate. Files not imported through this
module appear as `UNIMPORTED_FILE` warnings on the next Phase 2 run.
"""

from __future__ import annotations

import logging
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import openpyxl

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.core import phone as phone_mod
from biracki_odbor.core.models import FUNCTIONS, Issue, Person, split_combined_name
from biracki_odbor.core.phase1_generate import MARKER_CELL, _safe_filename
from biracki_odbor.validation.reports import Codes, message


log = logging.getLogger(__name__)


# Caps tuned for the real workload: Phase 1 output is ~30-50 KB; even a
# 500-row party file is well under 200 KB. 10 MB leaves comfortable headroom
# for legitimate manually-added content (charts, comments) without admitting
# files large enough to be a DoS vector.
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MIN_FILE_BYTES = 1024

# Zip-bomb heuristic: real .xlsx files compress around 5-10×; >100× ratio AND
# >5 MB uncompressed is the suspicious zone. Tuning is conservative.
_BOMB_RATIO_THRESHOLD = 100
_BOMB_MIN_UNCOMPRESSED = 5 * 1024 * 1024

# Magic prefix inside the marker — proves the file was produced by our Phase 1.
_MARKER_PREFIX = "BO"


# ── Data classes ──────────────────────────────────────────────────


@dataclass
class SafetyResult:
    ok: bool
    code: str = ""        # one of the Codes.* safety constants when not ok
    detail: str = ""      # human-readable reason


@dataclass
class MarkerInfo:
    """Parsed identity marker from a Phase 1 .xlsx file."""

    election_uuid: str
    party: str            # the canonical (safe-filename) party name
    run_ts: int = 0       # Unix epoch of the generation run; 0 = old-format file
    election_epoch: int = 0  # Unix epoch of election day at 07:00 local time


ImportStatus = Literal[
    "imported",          # new submission, copied + cached. With timestamped
                         # filenames there's no "replaced" status — every
                         # successful import is a new entry.
    "rejected_safety",   # killed by safety pipeline
    "rejected_identity", # killed by marker validation
    "rejected_io",       # disk error, permission etc.
]


ImportSource = Literal["file_picker", "outlook"]


@dataclass
class ImportOutcome:
    source: Path
    canonical_path: Path | None
    party: str
    status: ImportStatus
    # Both fields populated on success; empty on rejection.
    received_time_iso: str = ""
    import_source: ImportSource = "file_picker"
    issue: Issue | None = None  # populated on any rejection

    @property
    def ok(self) -> bool:
        return self.status == "imported"


def _iso_no_colons(dt: datetime) -> str:
    """ISO 8601 with no `:` so it's safe to embed in filenames.

    Filenames containing `:` are illegal on Windows; we substitute `-`
    in the time portion. The result still sorts lexicographically the
    same as the underlying datetime, which is what the aggregator
    relies on for "pick latest".
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


# ── Safety pipeline ──────────────────────────────────────────────


def check_file_safety(path: Path) -> SafetyResult:
    """Cheap pre-parse checks against a candidate import.

    Runs BEFORE any openpyxl call and BEFORE any copy into `popunjeni/`,
    so a rejected file never enters the working folder.
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError as e:
        return SafetyResult(False, Codes.NOT_XLSX, f"стат пропао: {e}")
    if st.st_size > _MAX_FILE_BYTES:
        return SafetyResult(False, Codes.FILE_TOO_LARGE,
                            f"величина {st.st_size} > {_MAX_FILE_BYTES}")
    if st.st_size < _MIN_FILE_BYTES:
        return SafetyResult(False, Codes.FILE_TOO_SMALL,
                            f"величина {st.st_size} < {_MIN_FILE_BYTES}")

    try:
        with zipfile.ZipFile(p) as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
    except zipfile.BadZipFile:
        return SafetyResult(False, Codes.NOT_XLSX, "није zip формат")
    except OSError as e:
        return SafetyResult(False, Codes.NOT_XLSX, f"zip отварање: {e}")

    if "xl/vbaProject.bin" in names:
        return SafetyResult(False, Codes.MACROS_PRESENT, "садржи vbaProject.bin")
    if any(n.startswith("xl/embeddings/") for n in names):
        return SafetyResult(False, Codes.EMBEDDED_OBJECTS, "садржи xl/embeddings/")
    if any(n.startswith("xl/externalLinks/") for n in names):
        return SafetyResult(False, Codes.EXTERNAL_LINKS, "садржи xl/externalLinks/")

    for info in infos:
        if (info.compress_size > 0
                and info.file_size > _BOMB_MIN_UNCOMPRESSED
                and info.file_size / max(info.compress_size, 1) > _BOMB_RATIO_THRESHOLD):
            return SafetyResult(
                False, Codes.SUSPICIOUS_COMPRESSION,
                f"{info.filename}: {info.file_size}/{info.compress_size}",
            )

    return SafetyResult(True)


# ── Identity marker ──────────────────────────────────────────────


# UUID segment accepts any non-slash content (handles both `uuid.uuid4().hex`
# in production AND friendlier strings like "test-uuid-1234" in tests).
# Extended format appends /<run_ts>/<election_epoch> (both digits); the group
# is optional so old-format files (no run_ts) are still accepted.
_MARKER_RE = re.compile(r"^BO/([^/]+)/([^/]+)(?:/(\d+)/(\d+))?$")


def read_marker(path: Path) -> MarkerInfo | None:
    """Read the M1 marker from a candidate workbook. Returns None if missing
    or malformed; caller maps that to NO_MARKER.

    Uses `read_only=True, data_only=True` — no formula evaluation, streaming
    parse. The hardening from the safety pipeline still applies; this just
    extracts the cell.
    """
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as e:  # noqa: BLE001
        log.warning("read_marker: cannot open %s: %s", path, e)
        return None
    try:
        ws = wb.active
        if ws is None:
            return None
        cell = ws[MARKER_CELL]
        value = cell.value if cell else None
    finally:
        wb.close()
    if not isinstance(value, str):
        return None
    m = _MARKER_RE.match(value.strip())
    if not m:
        return None
    return MarkerInfo(
        election_uuid=m.group(1),
        party=m.group(2),
        run_ts=int(m.group(3)) if m.group(3) else 0,
        election_epoch=int(m.group(4)) if m.group(4) else 0,
    )


# ── Row parsing ──────────────────────────────────────────────────


def _coerce_bm(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return int(s)
    return None


def parse_party_file(
    file_path: Path,
) -> tuple[list[tuple[tuple[int, str], Person]], list[Issue]]:
    """Parse one Phase-1-style .xlsx into (records, issues).

    Records are `((bm, function), Person)` pairs in file order. The caller
    handles cross-file deduplication and `ROW_OVERWRITE` detection.

    Schema: A=Р.бр  B=БМ  C=Гласачко место  D=Функција  E=Име  F=Презиме
            G=ЈМБГ  H=Место  I=Адреса  J=Телефон  K=Е-пошта  L=Предлагач
            M=marker. Column positions never shift: when Phase 1's
            combined_name_header merged E:F into one "Име и презиме"
            box, F is simply always blank in the file (detected below)
            and E's text gets split back into first/last name here —
            see the combined_name/NAME_AMBIGUOUS_SPLIT handling.
    """
    issues: list[Issue] = []
    records: list[tuple[tuple[int, str], Person]] = []

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    except PermissionError:
        issues.append(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(file_path)),
            severity="error",
            file=str(file_path),
        ))
        return records, issues
    except Exception as e:  # noqa: BLE001
        issues.append(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(file_path)) + f" ({e})",
            severity="error",
            file=str(file_path),
        ))
        return records, issues

    try:
        ws = wb.active
        if ws is None:
            return records, issues

        # combined_name_header (Phase 1) merges E:F into one "Име и
        # презиме" box per row instead of two Име/Презиме columns —
        # detected from the file's own header row, not from the live
        # election setting, so an older split-column submission (or one
        # from a cycle that had the toggle off) always still parses as
        # split. F3 is only ever blank in the merged shape; a real
        # "Презиме" header always has text.
        header_row = next(ws.iter_rows(min_row=3, max_row=3, values_only=True), ())
        header_e = str(header_row[4]).strip() if len(header_row) > 4 and header_row[4] else ""
        header_f = str(header_row[5]).strip() if len(header_row) > 5 and header_row[5] else ""
        combined_name = bool(header_e) and not header_f

        for row_idx, row_values in enumerate(
            ws.iter_rows(min_row=4, values_only=True), start=4,
        ):
            raw_bm = row_values[1] if len(row_values) > 1 else None
            func = row_values[3] if len(row_values) > 3 else None
            if raw_bm is None or func is None:
                continue
            # Skip non-data rows. Phase 1 writes a summary row two rows
            # below the data ("Укупно позиција: N", "Попуњено:", "Неисправних
            # ЈМБГ:") with values in cols B, D, L. Without this guard, that
            # summary row gets parsed as a fake data row whose `party`
            # field comes from the COUNTIF formula's cached result — and
            # then the marker-row-mismatch check trips because row_parties
            # = {"СНС", "0"} ≠ {"СНС"}. Filtering by `func ∈ FUNCTIONS`
            # silently drops the summary row (and any other oddity) without
            # affecting real data rows.
            #
            # BUG (found via live testing): this used to check ONLY the
            # fixed stalni FUNCTIONS tuple, so EVERY prosireni row ("Члан
            # [1]", "Заменик члана [1]", ...) silently hit this `continue`
            # too -- a prosireni submission always imported "successfully"
            # (the file-level checks upstream don't look at row content)
            # but produced zero records, so the master stayed permanently
            # blank no matter what was filled in. Accept prosireni's
            # bracket-numbered slot format here too -- the two formats
            # never collide, so no spec parameter is needed to disambiguate.
            from biracki_odbor.core.prosireni_allocation import (
                normalize_function_typo, parse_slot_function,
            )
            func_str = str(func).strip()
            if func_str not in FUNCTIONS and parse_slot_function(func_str) is None:
                continue

            bm = _coerce_bm(raw_bm)
            if bm is None:
                issues.append(Issue(
                    code=Codes.BM_NUMBER_NOT_INT,
                    message_sr=message(Codes.BM_NUMBER_NOT_INT, detail=str(raw_bm)),
                    severity="error",
                    file=file_path.name, row=row_idx, detail=str(raw_bm),
                ))
                continue

            def _str(idx: int) -> str:
                v = row_values[idx] if len(row_values) > idx else None
                return str(v or "").strip()

            # Normalize going forward so Person.function and the (bm, func)
            # slot key both use the corrected spelling, regardless of
            # what's literally in the cell (an old pre-fix Phase 1 file
            # sent to a party still carries the typo verbatim).
            func_s = normalize_function_typo(_str(3))
            if combined_name:
                full_name = _str(4)
                tokens = full_name.split()
                first_name, last_name = split_combined_name(full_name)
                if len(tokens) > 2:
                    # Given-name(s) vs a (possibly multi-word) surname
                    # isn't decidable from word count alone — the split
                    # above (first token = given name, rest = surname)
                    # is still applied rather than leaving the seat's
                    # surname blank, but flagged for a quick operator
                    # check in Корекције since a compound given name
                    # ("Ана Марија Петровић") would split wrong.
                    issues.append(Issue(
                        code=Codes.NAME_AMBIGUOUS_SPLIT,
                        message_sr=message(Codes.NAME_AMBIGUOUS_SPLIT, detail=full_name),
                        severity="warning",
                        file=file_path.name, row=row_idx, detail=full_name,
                    ))
            else:
                first_name = _str(4)
                last_name = _str(5)
            jmbg = str(jmbg_mod.normalize(
                row_values[6] if len(row_values) > 6 else None
            ))
            mesto = _str(7)
            adresa = _str(8)
            telefon = phone_mod.normalize(
                row_values[9] if len(row_values) > 9 else None
            )
            email = _str(10)
            party = _str(11)

            person = Person(
                bm_number=bm, function=func_s, party=party,
                first_name=first_name, last_name=last_name,
                jmbg=jmbg, mesto=mesto, adresa=adresa,
                telefon=telefon, email=email,
            )
            records.append(((bm, func_s), person))
    finally:
        wb.close()
    return records, issues


# ── Import orchestration ────────────────────────────────────────


def import_file(
    src: Path,
    election: ElectionConfig,
    popunjeni_dir: Path,
    *,
    received_at: datetime | None = None,
    source: ImportSource = "file_picker",
    phase1_run_ts: int = 0,
) -> ImportOutcome:
    """Run the full import pipeline against a single source file.

    Pipeline order (each step short-circuits on failure):
      1. Safety pipeline (size, zip, macros, OLE, externals, compression).
      2. Identity marker read + election-UID match.
      3. Cross-check: every row's party column matches the marker's party.
      4. Copy to a timestamped canonical path in `popunjeni/` — never
         overwrites a prior submission; the aggregator picks the
         newest by received_time on the next Phase 2 run.
      5. Parse rows into records (caller stores them in the cache).

    Args:
      received_at: when the party actually submitted the file. For
        Outlook imports, the email's ReceivedTime. For file-picker
        imports, defaults to the operator's clock at import time (UTC).
        Either way it's the "submitted at" timestamp the accountability
        log surfaces.
      source: provenance tag — "outlook" means we pulled it from a
        message via the COM integration; "file_picker" means the
        operator browsed/dropped a file directly. Stored on the cache
        entry so the audit log can show "imported from Outlook" vs
        "imported manually".

    Returns `ImportOutcome` whose `.issue` is populated on any rejection.
    The cache update is left to the caller so the cache module can stay
    independent of import orchestration.
    """
    src = Path(src)
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    elif received_at.tzinfo is None:
        # Treat naive datetimes as UTC. Outlook's COM ReceivedTime
        # comes through as a `pywintypes.datetime` with a real tzinfo
        # in practice, but the file-picker path passes datetime.now()
        # which may be naive depending on how the caller wrote it.
        received_at = received_at.replace(tzinfo=timezone.utc)
    received_iso = received_at.astimezone(timezone.utc).isoformat(timespec="seconds")

    # 1. Safety
    safety = check_file_safety(src)
    if not safety.ok:
        return ImportOutcome(
            source=src, canonical_path=None, party="",
            status="rejected_safety",
            issue=Issue(
                code=safety.code,
                message_sr=message(safety.code, file=src.name),
                severity="error",
                file=src.name, detail=safety.detail,
            ),
        )

    # 2. Identity marker
    marker = read_marker(src)
    if marker is None:
        return ImportOutcome(
            source=src, canonical_path=None, party="",
            status="rejected_identity",
            issue=Issue(
                code=Codes.NO_MARKER,
                message_sr=message(Codes.NO_MARKER, file=src.name),
                severity="error",
                file=src.name,
            ),
        )
    expected_uuid = election.election_uuid.strip()
    if not expected_uuid or marker.election_uuid != expected_uuid:
        return ImportOutcome(
            source=src, canonical_path=None, party=marker.party,
            status="rejected_identity",
            issue=Issue(
                code=Codes.WRONG_ELECTION,
                message_sr=message(Codes.WRONG_ELECTION, file=src.name),
                severity="error",
                file=src.name, detail=marker.election_uuid,
            ),
        )

    # 2b. Generation-run check: reject files from an older Phase 1 run when
    # the operator has invalidated and regenerated within the same cycle.
    # Only active when both sides carry a run_ts (old-format files are exempt).
    if phase1_run_ts and marker.run_ts and marker.run_ts != phase1_run_ts:
        return ImportOutcome(
            source=src, canonical_path=None, party=marker.party,
            status="rejected_identity",
            issue=Issue(
                code=Codes.STALE_GENERATION,
                message_sr=message(Codes.STALE_GENERATION, file=src.name),
                severity="error",
                file=src.name, detail=str(marker.run_ts),
            ),
        )

    # 3. Cross-check: parse rows now (we need them for the cache anyway),
    # then verify every row's party column matches the marker.
    records, parse_issues = parse_party_file(src)
    row_parties = {p.party for _, p in records if p.party}
    if row_parties and row_parties != {marker.party}:
        return ImportOutcome(
            source=src, canonical_path=None, party=marker.party,
            status="rejected_identity",
            issue=Issue(
                code=Codes.MARKER_ROW_MISMATCH,
                message_sr=message(
                    Codes.MARKER_ROW_MISMATCH,
                    file=src.name, detail=marker.party,
                ),
                severity="error",
                file=src.name, detail=marker.party,
            ),
        )

    # 4. Copy to a timestamped canonical path. The filename embeds the
    # received_at so two submissions from the same party coexist on
    # disk — the aggregator picks the latest by received_time_iso on
    # the next Phase 2 run. Format: `<party>__<iso8601-no-colons>.xlsx`.
    popunjeni_dir = Path(popunjeni_dir)
    popunjeni_dir.mkdir(parents=True, exist_ok=True)
    timestamp_token = _iso_no_colons(received_at)
    canonical = (
        popunjeni_dir
        / f"{_safe_filename(marker.party)}__{timestamp_token}.xlsx"
    )
    # Collision case: the same party submitted twice in the same
    # second. Unlikely in practice (Outlook ReceivedTime resolves to
    # seconds; file-picker uses now() which also has sub-second
    # precision but we truncate). When it happens, fall back to
    # appending the microseconds to keep the filename unique.
    if canonical.exists():
        canonical = (
            popunjeni_dir
            / f"{_safe_filename(marker.party)}__"
              f"{timestamp_token}-{received_at.microsecond:06d}.xlsx"
        )
    try:
        shutil.copy2(src, canonical)
    except OSError as e:
        return ImportOutcome(
            source=src, canonical_path=None, party=marker.party,
            status="rejected_io",
            issue=Issue(
                code=Codes.FILE_LOCKED,
                message_sr=message(Codes.FILE_LOCKED, file=str(canonical))
                + f" ({e})",
                severity="error",
                file=str(canonical),
            ),
        )

    log.info(
        "import_file: %s → %s (party=%s, received_at=%s, source=%s)",
        src, canonical, marker.party, received_iso, source,
    )
    return ImportOutcome(
        source=src, canonical_path=canonical, party=marker.party,
        status="imported",
        received_time_iso=received_iso,
        import_source=source,
        # parse_issues become part of the cached `issues` blob — caller
        # decides how to surface them; the import itself succeeded.
        issue=None,
    )


def parse_for_cache(canonical_path: Path) -> tuple[
    list[tuple[tuple[int, str], Person]], list[Issue]
]:
    """Convenience for callers that want the records for a just-imported file
    without re-running the full import pipeline (already validated)."""
    return parse_party_file(canonical_path)
