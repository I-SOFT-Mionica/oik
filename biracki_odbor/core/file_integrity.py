"""Tamper/corruption detection for load-bearing internal files.

`sablon/Stalni_sastav.xlsx` (the RIK allocation template), `master/
committee.db` (the shared SQLite committee roster for both workflows —
see core/master_io.py), and `master/nacelnik_sablion.xlsx` (the
chief's takeover template) are all "written once or rarely by the app
itself, then read many times by Phase 1/2/3" artifacts — unlike `popunjeni/` party submissions, which
get re-validated (`popunjeni_io.check_file_safety`) on every single
import, these were trusted forever after their one verified write.
This module closes that gap: every write that goes through the app's
own trusted path records a SHA-256 fingerprint plus a redundant
snapshot copy; every read that feeds real business logic re-verifies
against that record first.

This is NOT ransomware prevention. A same-machine snapshot sitting
next to the live file under the same account permissions would be
swept by the same encryption pass that hits the original — it buys
no resistance against a determined, whole-profile attack. What it
DOES buy:

  1. Fast, specific detection that something touched a protected file
     outside the app — tampering, accidental manual editing, disk
     corruption, or a ransomware sweep already in progress — *before*
     the operator keeps generating decisions on top of bad data.
  2. One-click local recovery from the far more common failure mode:
     accidental edits or a bad write, not a targeted attack.

Real resilience against whole-machine loss (ransomware included) is
`core/backup.py`'s off-machine targets (USB / cloud / e-mail) — this
module is a narrower, complementary safeguard, not a replacement.

Metadata + snapshot copy live in a `.verified/` subdirectory next to
the protected file (e.g. `sablon/.verified/Stalni_sastav.xlsx` +
`.json` sidecar). Kept alongside rather than centralized so each
protected file's history travels with it and nothing has to change if
a directory is renamed or moved as a whole.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class IntegrityMismatchError(Exception):
    """Raised when a protected file's live content no longer matches
    the fingerprint recorded at its last verified (app-driven) write."""

    def __init__(self, path: Path, verified_at: str) -> None:
        self.path = path
        self.verified_at = verified_at
        super().__init__(
            f"{path.name} has changed outside the application since it was"
            f" last verified ({verified_at})."
        )


@dataclass
class Fingerprint:
    sha256: str
    size: int
    verified_at: str  # ISO 8601 UTC


def _verified_dir(path: Path) -> Path:
    return path.parent / ".verified"


def _sidecar_path(path: Path) -> Path:
    return _verified_dir(path) / f"{path.name}.json"


def _snapshot_path(path: Path) -> Path:
    return _verified_dir(path) / path.name


def compute_hash(path: Path) -> str:
    t0 = time.perf_counter()
    size = 0
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    elapsed = (time.perf_counter() - t0) * 1000
    log.info(
        "compute_hash: %s (%d bytes) took %.0f ms", path.name, size, elapsed,
    )
    return h.hexdigest()


def _load_fingerprint(path: Path) -> Fingerprint | None:
    sidecar = _sidecar_path(path)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return Fingerprint(
            sha256=str(data["sha256"]),
            size=int(data["size"]),
            verified_at=str(data["verified_at"]),
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        # A corrupt sidecar is treated as "no baseline" — record_verified()
        # will re-establish one rather than blocking on our own bookkeeping.
        return None


def record_verified(path: Path) -> None:
    """Fingerprint `path` and snapshot it into `.verified/` — call this
    immediately after a write that went through the app's own trusted
    path (never for arbitrary operator-chosen export copies)."""
    path = Path(path)
    verified_dir = _verified_dir(path)
    verified_dir.mkdir(parents=True, exist_ok=True)
    fp = Fingerprint(
        sha256=compute_hash(path),
        size=path.stat().st_size,
        verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _sidecar_path(path).write_text(
        json.dumps(fp.__dict__, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    shutil.copy2(path, _snapshot_path(path))


def check_or_raise(path: Path) -> None:
    """Verify `path` against its last recorded fingerprint before a real
    (non-re-validation) read.

    No baseline yet (feature just rolled out, or file predates it) is
    treated as "nothing to compare against" — silently establishes one
    rather than blocking an existing, perfectly fine install on upgrade.
    A baseline that exists and doesn't match is the real signal;
    raises `IntegrityMismatchError` so the caller can hard-block.
    """
    path = Path(path)
    if not path.exists():
        return
    fp = _load_fingerprint(path)
    if fp is None:
        record_verified(path)
        return
    if compute_hash(path) != fp.sha256:
        raise IntegrityMismatchError(path, fp.verified_at)


def has_verified_copy(path: Path) -> bool:
    return _snapshot_path(Path(path)).exists()


def restore_verified(path: Path) -> bool:
    """Copy the last verified snapshot back over `path`. Returns False
    (no-op) if no snapshot was ever recorded."""
    path = Path(path)
    snapshot = _snapshot_path(path)
    if not snapshot.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot, path)
    # The restored file IS the verified content — no need to recompute;
    # re-fingerprinting also refreshes verified_at to "now" which would
    # be misleading (implies a fresh app-driven write just happened).
    return True
