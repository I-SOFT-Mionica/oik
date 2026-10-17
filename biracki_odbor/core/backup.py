"""Backup / disaster-recovery utilities.

Election-eve scenario: the OIK's laptop disk fails at 22:00 the night
before voting. Everything lives in `BIRACKI_ODBOR_HOME`. Without an
out-of-machine copy, hours of `corrections.log` + the master
spreadsheet are gone. This module is the manual safety net: the
operator clicks „Сачувај резервну копију…" in the sidebar, picks a
destination, and gets the settings + database packaged as one .zip.

Scope: settings (all JSON config files + license.dat), observer
accreditation registry (posmatraci.json), phase-generation tracking
(generation_log.json), audit trails (corrections*.log), the popunjeni
import cache (cache/popunjeni.json), and the "database" (sablon/
template, popunjeni*/ raw submissions, popunjeni_odbijeno*/ rejected
submissions, master*/ generated rosters) for both стални and
проширени workflows.

The program binaries (Biracki_Odbor.exe, the uninstaller), installer
artifacts (icon.ico, desktop.ini, УПУТСТВО.txt), and derived outputs
(stranka_fajlovi*/, resenja*/, audit*/, posmatraci/liste/,
posmatraci/legitimacije/) are NOT in the backup — they're either
reinstallable or regenerable from the included data and just bloat
the zip.

**cache/popunjeni.json is NOT a disposable performance cache — it is
the allowlist.** `aggregate_party_files()` only aggregates files that
have a cache entry; a file present in popunjeni/ but absent from the
cache surfaces as an UNIMPORTED_FILE warning and is silently excluded
from the master roster (see phase2_aggregate.py). It also carries
received_time_iso/import_source/imported_by provenance that cannot be
reconstructed from the .xlsx files themselves. Found 2026-07-16: this
module previously excluded cache/ on the (incorrect) assumption that
it "rebuilds from popunjeni/*.xlsx on next Phase 2 run" — it does not.
Excluding it meant every restored profile would silently lose every
previously-imported submission on the next Phase 2 run. Do not
re-exclude it without re-verifying that assumption against
phase2_aggregate.py's actual behavior.

Three destinations, all routed through the same `.zip`:
  - **USB**: copy to a removable drive (operator picks which).
  - **Cloud**: copy to `~/OneDrive` or `~/Google Drive` if either is
    installed — the desktop sync client handles the upload.
  - **Outlook email**: create a draft with the .zip attached, addressed
    to the operator (or a fixed OIK archive address); they review +
    send. Reuses `integrations/outlook.create_drafts`.

Size-based recommendation (see `recommend_target`):
  < 10 MB  → Outlook (fastest, universal)
  10-25 MB → Cloud (above most Exchange attachment limits)
  > 25 MB  → USB (cloud unreliable on slow election-eve internet)

`log/` is excluded from the backup — rotating daily logs are not
critical for recovery and would inflate the .zip considerably. Every
other top-level subdir of HOME is included verbatim.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


log = logging.getLogger(__name__)


# Top-level names allowed into the backup. Everything else under HOME
# is either an installer artifact (the .exes, icon.ico, desktop.ini,
# УПУТСТВО.txt) or derived/transient state (log/, cache/,
# stranka_fajlovi/, resenja/, audit/) — both kinds are excluded.
DEFAULT_INCLUDE: tuple[str, ...] = (
    # Settings (JSON config files + activated license).
    "oik_constants.json",
    "election_config.json",
    "app_settings.json",
    "places_genitive.json",
    "places_prepositions.json",
    "obrazlozenje.json",
    "obrazlozenje_prosireni.json",
    "license.dat",
    # Observer accreditation registry (orgs + observers + legitimacija layout).
    "posmatraci.json",
    # Phase-generation tracking — gates Решења/Измене tabs on restore.
    "generation_log.json",
    # Audit trails — required to reconstruct what corrections were made.
    "corrections.log",
    "corrections_prosireni.log",
    # User-editable amendment (izmena) obrazloženje templates.
    "izmena_obrazlozenje_stalni.json",
    "izmena_obrazlozenje_prosireni.json",
    # Popunjeni import cache/allowlist — see the module docstring's
    # warning above. Not disposable: it gates which files Phase 2 will
    # aggregate and holds provenance data found nowhere else.
    "cache",
    # "Database" directories — working template, raw party submissions,
    # rejected/late submissions, and generated master spreadsheets.
    # Стални workflow:
    "sablon",
    "popunjeni",
    "popunjeni_odbijeno",
    "master",
    # Проширени workflow:
    "popunjeni_prosireni",
    "popunjeni_odbijeno_prosireni",
    "master_prosireni",
)

# Backwards-compatible alias retained so any out-of-tree callers that
# still pass `exclude=` keep working. Unused inside this module after
# the include-list rewrite. NOTE: "cache" removed 2026-07-16 — it's
# in DEFAULT_INCLUDE now (see that list's comment); this tuple must
# not silently re-exclude it for whatever still reads it.
DEFAULT_EXCLUDE: tuple[str, ...] = ("log",)


# Size thresholds for `recommend_target`. Tuned to the Outlook /
# Exchange landscape OIKs typically use:
#   - Most Exchange tenants allow 25 MB attachments
#   - Email is fastest if it fits
#   - Cloud upload is reliable up to ~100 MB but slow on weak rural
#     internet at 22:00 on election eve
#   - USB always works and doesn't need connectivity
EMAIL_MAX_BYTES = 10 * 1024 * 1024     # 10 MB — comfortable Outlook attach
CLOUD_MAX_BYTES = 25 * 1024 * 1024     # 25 MB — above email but still cloud-OK


class BackupTarget(str, Enum):
    USB = "usb"
    ONEDRIVE = "onedrive"
    GOOGLE_DRIVE = "google_drive"
    OUTLOOK_EMAIL = "outlook_email"
    CUSTOM_FOLDER = "custom_folder"


@dataclass
class AvailableTargets:
    """What backup destinations exist on this machine right now."""

    usb_drives: list[Path] = field(default_factory=list)
    onedrive: Path | None = None
    google_drive: Path | None = None
    outlook: bool = False  # True iff OUTLOOK_AVAILABLE — checked at call time

    def as_target_list(self) -> list[BackupTarget]:
        """Enumerate which BackupTarget options the GUI should show."""
        out: list[BackupTarget] = []
        if self.usb_drives:
            out.append(BackupTarget.USB)
        if self.onedrive is not None:
            out.append(BackupTarget.ONEDRIVE)
        if self.google_drive is not None:
            out.append(BackupTarget.GOOGLE_DRIVE)
        if self.outlook:
            out.append(BackupTarget.OUTLOOK_EMAIL)
        # Custom folder is always available — operator picks a path.
        out.append(BackupTarget.CUSTOM_FOLDER)
        return out


# ── ZIP builder ─────────────────────────────────────────────────────


def build_backup_zip(
    home: Path,
    output_path: Path | None = None,
    *,
    include: tuple[str, ...] = DEFAULT_INCLUDE,
) -> Path:
    """Pack the settings + database under `home` into a single `.zip`.

    Args:
      home: directory to back up (the app's `BIRACKI_ODBOR_HOME`).
      output_path: explicit destination .zip path. When None, writes
        to a unique temp file the caller is responsible for moving /
        deleting.
      include: top-level names (files or dirs) to keep. Anything not
        on this list is skipped — the binaries, installer artifacts,
        and derived outputs are not part of recoverable state.

    Files are stored with paths relative to `home` so extracting back
    over a fresh `BIRACKI_ODBOR_HOME` reconstructs the layout exactly.
    Uses `ZIP_DEFLATED` — .xlsx and .docx files are already compressed
    archives internally so the marginal gain is small, but it still
    helps the JSON + .log files.
    """
    home = Path(home)
    if output_path is None:
        # mkstemp leaves an empty file at the path; we overwrite it.
        # Using mkstemp (not NamedTemporaryFile) so the caller can move
        # the file freely without fighting the cleanup that
        # NamedTemporaryFile attaches.
        fd, tmp_path = tempfile.mkstemp(
            suffix=".zip",
            prefix=f"biracki_odbor_backup_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_",
        )
        os.close(fd)
        output_path = Path(tmp_path)
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    include_set = set(include)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in home.rglob("*"):
            if not src.is_file():
                continue
            try:
                rel = src.relative_to(home)
            except ValueError:
                # Shouldn't happen with rglob from `home`, but guard
                # against symlinks pointing outside.
                continue
            if not rel.parts or rel.parts[0] not in include_set:
                continue
            zf.write(src, str(rel))
    log.info(
        "build_backup_zip: %s → %s (%.1f MB)",
        home, output_path, output_path.stat().st_size / (1024 * 1024),
    )
    return output_path


# ── Destination detection ───────────────────────────────────────────


def detect_targets() -> AvailableTargets:
    """Probe the local system for available backup destinations.

    Safe on every platform — non-Windows returns no USB drives and
    no Outlook availability. OneDrive / Google Drive detection works
    on any OS that mounts them under the home dir.
    """
    return AvailableTargets(
        usb_drives=detect_usb_drives(),
        onedrive=detect_onedrive(),
        google_drive=detect_google_drive(),
        outlook=_outlook_available(),
    )


def detect_usb_drives() -> list[Path]:
    """Return mount points of removable drives.

    Windows: walks the bitmask of logical drives and asks the Win32
    `GetDriveTypeW` for each one, filtering to `DRIVE_REMOVABLE` (2).
    Other platforms: returns an empty list — the GUI falls back to
    Custom Folder.
    """
    if sys.platform != "win32":
        return []
    try:
        DRIVE_REMOVABLE = 2  # noqa: N806 — Win32 constant
        kernel32 = ctypes.windll.kernel32
        bitmask = kernel32.GetLogicalDrives()
        drives: list[Path] = []
        for i in range(26):
            if not (bitmask & (1 << i)):
                continue
            letter = chr(ord("A") + i)
            root = f"{letter}:\\"
            if kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE:
                drives.append(Path(root))
        return drives
    except Exception as e:  # noqa: BLE001
        log.warning("detect_usb_drives failed: %s", e)
        return []


def detect_onedrive() -> Path | None:
    """Return the OneDrive sync folder if installed, else None.

    Reads from the `OneDrive` environment variable (set by the
    OneDrive client) and falls back to `~/OneDrive`. Skips Personal vs.
    Business distinction — copying into whichever the user is signed
    into is the right behavior.
    """
    env = os.environ.get("OneDrive") or os.environ.get("OneDriveCommercial")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    # Fallback: the conventional location even without the env var
    # (some installs don't propagate it to all sessions).
    candidate = Path.home() / "OneDrive"
    return candidate if candidate.is_dir() else None


def detect_google_drive() -> Path | None:
    """Return the Google Drive Desktop sync folder if installed.

    The desktop client mounts as `~/Google Drive` on Windows by
    default, or as a virtual drive letter (G:) in Streaming mode.
    We only catch the simpler home-dir mount; G:-letter setups can
    use the Custom Folder option.
    """
    for name in ("Google Drive", "GoogleDrive", "GoogleDriveDesktop"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return None


def _outlook_available() -> bool:
    """True iff at least one e-mail client (Outlook OR Thunderbird) is
    usable on this machine. Kept named `_outlook_available` for backwards
    compat with the `AvailableTargets.outlook` field + the test suite;
    the semantic meaning is "the e-mail-draft destination is offerable".
    The actual backend gets resolved later by `email_client.create_drafts`
    based on the operator's preference."""
    try:
        from biracki_odbor.integrations import email_client as ec_mod
        return bool(ec_mod.any_available())
    except Exception:  # noqa: BLE001
        return False


# ── Size-based recommendation ──────────────────────────────────────


def recommend_target(
    zip_size: int,
    available: list[BackupTarget],
) -> BackupTarget:
    """Pick the most appropriate target from those actually available.

    The thresholds are doctrine, not policy — they're the size at
    which each medium becomes unreliable, not user preference.
    Override by passing a different selection at the GUI level if a
    given site has different constraints.
    """
    if zip_size < EMAIL_MAX_BYTES and BackupTarget.OUTLOOK_EMAIL in available:
        return BackupTarget.OUTLOOK_EMAIL
    if zip_size < CLOUD_MAX_BYTES:
        for t in (BackupTarget.ONEDRIVE, BackupTarget.GOOGLE_DRIVE):
            if t in available:
                return t
    if BackupTarget.USB in available:
        return BackupTarget.USB
    return BackupTarget.CUSTOM_FOLDER


# ── Copy + email helpers (used by the dialog) ──────────────────────


def copy_to_folder(zip_path: Path, dest_folder: Path) -> Path:
    """Copy the backup .zip into `dest_folder`. Returns the final path.

    The filename is preserved (already carries an ISO timestamp from
    `build_backup_zip`) so successive backups don't overwrite each
    other on the same destination.
    """
    dest_folder = Path(dest_folder)
    dest_folder.mkdir(parents=True, exist_ok=True)
    final = dest_folder / Path(zip_path).name
    shutil.copy2(zip_path, final)
    log.info("backup copy: %s → %s", zip_path, final)
    return final


# ── Restore ─────────────────────────────────────────────────────────


@dataclass
class ZipInfo:
    """Summary of a backup .zip for the pre-flight preview dialog."""

    path: Path
    # UTC timestamp of the newest entry in the archive (proxy for
    # when the backup was made when the outer filename is unavailable).
    newest_entry_mtime: datetime | None
    # Number of files inside.
    file_count: int
    # True when at least one file in the zip would overwrite a *newer*
    # local file — the dialog uses this to show the staleness warning.
    has_stale_entries: bool
    # The set of archive-relative paths that exist on disk and would be
    # overwritten.
    would_overwrite: list[str]


def inspect_zip(zip_path: Path, home: Path) -> ZipInfo:
    """Read a backup .zip and return a summary for the pre-flight dialog.

    Does not write anything. Comparing modification times uses the
    archive entry's `date_time` tuple (stored by `build_backup_zip`
    via the OS mtime) vs. the file's current on-disk mtime.
    """
    zip_path = Path(zip_path)
    home = Path(home)
    newest: datetime | None = None
    file_count = 0
    has_stale = False
    would_overwrite: list[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            file_count += 1
            # date_time is a 6-tuple of local time (ZIP uses DOS timestamps,
            # 2-second resolution, no timezone). Compare as naive local time
            # against the file's on-disk mtime (also converted to naive local).
            entry_dt = datetime(*info.date_time)
            if newest is None or entry_dt > newest:
                newest = entry_dt
            on_disk = home / info.filename
            if on_disk.exists():
                would_overwrite.append(info.filename)
                disk_mtime = datetime.fromtimestamp(on_disk.stat().st_mtime)
                if disk_mtime > entry_dt:
                    has_stale = True

    return ZipInfo(
        path=zip_path,
        newest_entry_mtime=newest,
        file_count=file_count,
        has_stale_entries=has_stale,
        would_overwrite=would_overwrite,
    )


@dataclass
class RestoreResult:
    """Outcome of a `restore_from_zip` call."""

    restored_files: list[str]
    pre_restore_backup: Path | None  # path to the safety backup, if made
    log_entry_written: bool


def restore_from_zip(
    zip_path: Path,
    home: Path,
    *,
    make_pre_restore_backup: bool = True,
) -> RestoreResult:
    """Extract a backup .zip back into `home`.

    Steps:
      1. Optionally archive the current HOME state to
         ``home/backups/pre-restore-<iso>.zip`` so the operation is
         reversible.
      2. Extract every file from the zip, creating parent directories
         as needed.
      3. Append a RESTORE sentinel line to ``corrections.log`` so the
         audit trail records that a restore happened.

    Only files from `DEFAULT_INCLUDE` paths are extracted — if someone
    hands us an arbitrary .zip, entries outside that set are silently
    skipped as a safety measure.

    Does NOT reload the in-memory AppState — the caller (main_window)
    is responsible for restarting or reloading after the restore.
    """
    zip_path = Path(zip_path)
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)

    pre_backup: Path | None = None
    if make_pre_restore_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backups_dir = home / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        pre_backup = backups_dir / f"pre-restore-{ts}.zip"
        try:
            build_backup_zip(home, pre_backup)
        except Exception as e:  # noqa: BLE001
            log.warning("pre-restore backup failed: %s", e)
            pre_backup = None

    include_set = set(DEFAULT_INCLUDE)
    restored: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            # Only extract paths whose top-level component is in the
            # allow-list — mirrors the include-list used by build_backup_zip.
            if not rel.parts or rel.parts[0] not in include_set:
                continue
            dest = home / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            restored.append(str(rel))

    # Append RESTORE sentinel to corrections.log (create if absent).
    log_path = home / "corrections.log"
    ts_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f'{{"event_type":"restore","zip":"{zip_path.name}",'
                f'"restored_files":{len(restored)},'
                f'"timestamp":"{ts_human}","operator":"system"}}\n'
            )
        log_written = True
    except OSError as e:
        log.warning("could not write RESTORE sentinel: %s", e)
        log_written = False

    log.info(
        "restore_from_zip: %s → %s (%d files)", zip_path, home, len(restored),
    )
    return RestoreResult(
        restored_files=restored,
        pre_restore_backup=pre_backup,
        log_entry_written=log_written,
    )


def run_daily_backup_if_due(home: Path) -> Path | None:
    """Create a dated backup in ``home/backups/`` if one hasn't been made in 24h.

    Naming: ``autobackup_<UTC-ISO>.zip`` so pre-restore safety backups
    (``pre-restore-*.zip``) are never touched by the rotation logic.
    Backups older than 14 days are silently deleted after each new one
    is written.

    Returns the path of the new .zip if a backup was made, None otherwise.
    Failures are logged but not re-raised — a missing nightly backup is a
    recoverable nuisance, not a crash.
    """
    home = Path(home)
    backups_dir = home / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Find the most recent existing auto-backup.
    newest_mtime: float | None = None
    for p in backups_dir.glob("autobackup_*.zip"):
        try:
            mtime = p.stat().st_mtime
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime
        except OSError:
            pass

    now = datetime.now(timezone.utc)
    if newest_mtime is not None and (now.timestamp() - newest_mtime) < 86_400:
        return None  # last backup is less than 24 hours old

    ts = now.strftime("%Y%m%dT%H%M%SZ")
    dest = backups_dir / f"autobackup_{ts}.zip"
    try:
        build_backup_zip(home, dest)
    except Exception as e:  # noqa: BLE001
        log.warning("auto-backup failed: %s", e)
        return None

    # Rotate: delete auto-backups older than 14 days.
    cutoff = now.timestamp() - 14 * 86_400
    for p in backups_dir.glob("autobackup_*.zip"):
        try:
            if p != dest and p.stat().st_mtime < cutoff:
                p.unlink()
                log.debug("auto-backup rotation: deleted %s", p.name)
        except OSError as e:
            log.warning("could not delete old auto-backup %s: %s", p.name, e)

    log.info("auto-backup created: %s", dest)
    return dest


def email_subject_body() -> tuple[str, str]:
    """Default subject + body for the Outlook draft. Kept here so the
    dialog can override; the body explains what the .zip contains so
    the operator's future self knows what to do with it."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"Бирачки одбор — резервна копија ({now})"
    body = (
        "У прилогу се налази .zip резервне копије радне фасцикле "
        "Бирачког одбора у тренутку када је направљена.\n\n"
        "Шта је унутра: поставке (sve .json фајлови), акредитација "
        "посматрача (posmatraci.json), евиденција генерисања "
        "(generation_log.json), аудит трагови (corrections*.log), "
        "радни шаблон (sablon/), попуњени фајлови странака "
        "(popunjeni/, popunjeni_prosireni/), одбијени фајлови "
        "(popunjeni_odbijeno*/) и збирне табеле (master/, master_prosireni/).\n\n"
        "Шта НИЈЕ унутра: програмски фајлови (OIK.exe и сродни), "
        "ни изведени документи (stranka_fajlovi*/, resenja*/, audit*/) "
        "— они се поново производе кроз апликацију.\n\n"
        "Kako вратити: распакуј .zip преко локалне фасцикле "
        "OIK (обично у %USERPROFILE%) и покрени апликацију."
    )
    return subject, body
