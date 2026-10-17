"""Tests for the §4 backup core.

The destination side-effects (USB copy, OneDrive copy, Outlook draft)
are headless-impossible in their full form — they need real devices /
real Outlook. These tests pin the deterministic pieces:

- build_backup_zip excludes the right dirs and round-trips file contents
- recommend_target follows the size doctrine
- detect_* helpers return None/[] gracefully on platforms without the
  targets installed
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from biracki_odbor.core import backup as backup_mod
from biracki_odbor.core.backup import (
    AvailableTargets, BackupTarget, CLOUD_MAX_BYTES, EMAIL_MAX_BYTES,
    inspect_zip, restore_from_zip,
)


def _seed_home(tmp_path: Path) -> Path:
    """Build a fake HOME with the canonical subdirs + sample files."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "oik_constants.json").write_text("{}", encoding="utf-8")
    (home / "election_config.json").write_text("{}", encoding="utf-8")
    (home / "corrections.log").write_text("event1\nevent2\n", encoding="utf-8")
    (home / "sablon").mkdir()
    (home / "sablon" / "Stalni_sastav.xlsx").write_bytes(b"PK\x03\x04")
    (home / "popunjeni").mkdir()
    (home / "popunjeni" / "СНС__2026-05-15.xlsx").write_bytes(b"PK\x03\x04hi")
    (home / "log").mkdir()
    (home / "log" / "2026-05-30.log").write_text("noise\n", encoding="utf-8")
    (home / "cache").mkdir()
    (home / "cache" / "popunjeni.json").write_text("{}", encoding="utf-8")
    return home


def test_build_backup_zip_skips_log_but_keeps_cache(tmp_path: Path) -> None:
    """`log/` is noise for recovery — must not appear in the zip.

    `cache/` is the OPPOSITE case and must be INCLUDED: it's the
    popunjeni import allowlist, not a disposable performance cache.
    Regression guard for 2026-07-16 — this test used to assert cache/
    was excluded on the incorrect assumption that it "rebuilds from
    popunjeni/*.xlsx on next Phase 2 run". It doesn't: a file present
    in popunjeni/ but missing from the cache is treated as never
    imported and silently dropped from aggregation (see
    phase2_aggregate.py's UNIMPORTED_FILE handling) — so excluding
    cache/ from backup meant every restored profile would lose every
    previously-imported submission."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        # Canonical-state files present.
        assert "oik_constants.json" in names
        assert "election_config.json" in names
        assert "corrections.log" in names
        assert "sablon/Stalni_sastav.xlsx" in names
        assert "popunjeni/СНС__2026-05-15.xlsx" in names
        assert "cache/popunjeni.json" in names
        # log/ omitted by default — rotating dailies aren't critical
        # for recovery and would inflate the zip.
        assert not any(n.startswith("log/") for n in names)
    finally:
        zip_path.unlink(missing_ok=True)


def test_build_backup_zip_round_trips_file_contents(tmp_path: Path) -> None:
    """Restoring the zip into a fresh HOME must reproduce file contents
    byte-for-byte — backup is worthless if the bytes can't survive
    the round-trip."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)
    try:
        restored = tmp_path / "restored"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(restored)
        # Spot-check key files. corrections.log is the audit-log
        # canary — if anything reorders bytes, that's where it'll show.
        assert (restored / "corrections.log").read_text(encoding="utf-8") == (
            "event1\nevent2\n"
        )
        assert (
            restored / "popunjeni" / "СНС__2026-05-15.xlsx"
        ).read_bytes() == b"PK\x03\x04hi"
    finally:
        zip_path.unlink(missing_ok=True)


def test_build_backup_zip_explicit_output(tmp_path: Path) -> None:
    """When the caller passes output_path, the zip lands there instead
    of in temp. Used by the future daily-auto-backup that drops into
    `<HOME>/backups/<date>.zip`."""
    home = _seed_home(tmp_path)
    out = tmp_path / "out" / "my_backup.zip"
    result = backup_mod.build_backup_zip(home, out)
    assert result == out
    assert out.exists()


# ── recommend_target ──────────────────────────────────────────────


def test_recommend_target_small_payload_picks_email() -> None:
    avail = [
        BackupTarget.USB, BackupTarget.ONEDRIVE,
        BackupTarget.OUTLOOK_EMAIL, BackupTarget.CUSTOM_FOLDER,
    ]
    # 5 MB → email is fastest + universal
    assert backup_mod.recommend_target(5 * 1024 * 1024, avail) == (
        BackupTarget.OUTLOOK_EMAIL
    )


def test_recommend_target_medium_payload_picks_cloud() -> None:
    avail = [
        BackupTarget.USB, BackupTarget.ONEDRIVE,
        BackupTarget.OUTLOOK_EMAIL, BackupTarget.CUSTOM_FOLDER,
    ]
    # 15 MB → above the email comfort threshold, OneDrive is preferred
    # over Google Drive when both are present (order in
    # recommend_target's loop).
    assert backup_mod.recommend_target(15 * 1024 * 1024, avail) == (
        BackupTarget.ONEDRIVE
    )


def test_recommend_target_large_payload_picks_usb() -> None:
    avail = [
        BackupTarget.USB, BackupTarget.ONEDRIVE,
        BackupTarget.OUTLOOK_EMAIL, BackupTarget.CUSTOM_FOLDER,
    ]
    # 30 MB → too big for cloud reliability on a bad connection.
    assert backup_mod.recommend_target(30 * 1024 * 1024, avail) == (
        BackupTarget.USB
    )


def test_recommend_target_falls_back_to_custom_folder() -> None:
    """No USB, no cloud, no Outlook → caller can still backup to a
    folder of their choice. Custom Folder is the universal fallback."""
    assert backup_mod.recommend_target(
        5 * 1024 * 1024, [BackupTarget.CUSTOM_FOLDER],
    ) == BackupTarget.CUSTOM_FOLDER


def test_recommend_target_email_threshold_boundary() -> None:
    """Exactly at the email threshold, prefer cloud (the threshold is
    the size at which email becomes unreliable, not where it stops
    working). One byte below it, email wins."""
    avail = [
        BackupTarget.ONEDRIVE, BackupTarget.OUTLOOK_EMAIL,
        BackupTarget.CUSTOM_FOLDER,
    ]
    assert backup_mod.recommend_target(
        EMAIL_MAX_BYTES - 1, avail,
    ) == BackupTarget.OUTLOOK_EMAIL
    assert backup_mod.recommend_target(
        EMAIL_MAX_BYTES, avail,
    ) == BackupTarget.ONEDRIVE


# ── detect_* ──────────────────────────────────────────────────────


def test_detect_targets_returns_dataclass() -> None:
    """detect_targets always returns AvailableTargets; never raises
    on platforms without USB/Cloud/Outlook. The GUI relies on the
    returned dataclass being safe to inspect blindly."""
    targets = backup_mod.detect_targets()
    assert isinstance(targets, AvailableTargets)
    assert isinstance(targets.usb_drives, list)
    # Custom folder is always available via the dialog; not asserted
    # here because it's added at as_target_list() time, not detected.


def test_available_targets_as_list_always_has_custom_folder() -> None:
    """Custom Folder is always in the picker so the operator has at
    least one path forward — even on a fresh Linux box with no USB,
    no cloud, no Outlook."""
    targets = AvailableTargets()  # all defaults: nothing detected
    assert BackupTarget.CUSTOM_FOLDER in targets.as_target_list()


def test_available_targets_only_lists_present() -> None:
    """Non-detected targets don't appear in the picker — no greyed-out
    radio buttons that do nothing."""
    targets = AvailableTargets(
        usb_drives=[Path("E:\\")], onedrive=None, google_drive=None,
        outlook=False,
    )
    lst = targets.as_target_list()
    assert BackupTarget.USB in lst
    assert BackupTarget.ONEDRIVE not in lst
    assert BackupTarget.GOOGLE_DRIVE not in lst
    assert BackupTarget.OUTLOOK_EMAIL not in lst
    assert BackupTarget.CUSTOM_FOLDER in lst


# ── restore_from_zip ──────────────────────────────────────────────


def test_restore_round_trip(tmp_path: Path) -> None:
    """backup → restore in a fresh HOME reproduces every file bit-for-bit."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)

    restore_home = tmp_path / "restore_home"
    restore_home.mkdir()
    result = restore_from_zip(zip_path, restore_home, make_pre_restore_backup=False)
    zip_path.unlink(missing_ok=True)

    assert len(result.restored_files) > 0
    assert result.pre_restore_backup is None

    assert (restore_home / "oik_constants.json").read_text(encoding="utf-8") == "{}"
    assert (restore_home / "corrections.log").read_text(encoding="utf-8").startswith(
        "event1\nevent2\n"
    )
    assert (
        restore_home / "popunjeni" / "СНС__2026-05-15.xlsx"
    ).read_bytes() == b"PK\x03\x04hi"
    # The popunjeni allowlist/cache must survive too, or every restored
    # profile would treat its own previously-imported submissions as
    # never-imported on the next Phase 2 run (see backup.py docstring).
    assert (restore_home / "cache" / "popunjeni.json").read_text(encoding="utf-8") == "{}"


def test_restore_writes_sentinel_to_corrections_log(tmp_path: Path) -> None:
    """A RESTORE line is appended to corrections.log so the audit trail
    records when and from which zip the restore happened."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)
    restore_home = tmp_path / "rh"
    restore_home.mkdir()

    result = restore_from_zip(zip_path, restore_home, make_pre_restore_backup=False)
    zip_path.unlink(missing_ok=True)

    assert result.log_entry_written
    log_text = (restore_home / "corrections.log").read_text(encoding="utf-8")
    assert '"event_type":"restore"' in log_text


def test_restore_makes_pre_restore_backup(tmp_path: Path) -> None:
    """With make_pre_restore_backup=True the existing HOME is zipped into
    backups/pre-restore-*.zip before anything is overwritten."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)

    restore_home = tmp_path / "rh2"
    restore_home.mkdir()
    # Seed restore_home with a file that should survive in the safety backup.
    (restore_home / "oik_constants.json").write_text('{"existing": true}', encoding="utf-8")

    result = restore_from_zip(zip_path, restore_home, make_pre_restore_backup=True)
    zip_path.unlink(missing_ok=True)

    assert result.pre_restore_backup is not None
    assert result.pre_restore_backup.exists()
    # The safety backup must contain the pre-restore file content.
    with zipfile.ZipFile(result.pre_restore_backup) as zf:
        names = zf.namelist()
    assert "oik_constants.json" in names


def test_restore_skips_non_include_entries(tmp_path: Path) -> None:
    """Entries in the zip whose top-level component is not in DEFAULT_INCLUDE
    are silently skipped — a hand-crafted or tampered zip can't write
    outside the allowed paths."""
    import io
    home = _seed_home(tmp_path)
    restore_home = tmp_path / "rh3"
    restore_home.mkdir()

    # Build a zip with a legitimate file + an extra that's not in DEFAULT_INCLUDE.
    zip_path = tmp_path / "crafted.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("oik_constants.json", "{}")
        zf.writestr("log/sneaky.log", "sneaky")
        zf.writestr("resenja/some.docx", "docx")

    restore_from_zip(zip_path, restore_home, make_pre_restore_backup=False)

    assert (restore_home / "oik_constants.json").exists()
    assert not (restore_home / "log" / "sneaky.log").exists()
    assert not (restore_home / "resenja" / "some.docx").exists()


def test_inspect_zip_detects_stale_entries(tmp_path: Path) -> None:
    """inspect_zip sets has_stale_entries=True when a file on disk is newer
    than the corresponding zip entry — the dialog uses this for the
    staleness warning."""
    import os, time as _time
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)

    # Force the on-disk file's mtime to 10 seconds in the future so it's
    # definitely newer than the zip entry regardless of FAT 2-s resolution.
    target = home / "oik_constants.json"
    future = _time.time() + 10
    os.utime(target, (future, future))

    info = inspect_zip(zip_path, home)
    zip_path.unlink(missing_ok=True)

    assert info.has_stale_entries is True
    assert info.file_count > 0


def test_inspect_zip_no_stale_on_fresh_home(tmp_path: Path) -> None:
    """No stale entries when restoring into a directory that has no
    existing files (the typical disaster-recovery scenario)."""
    home = _seed_home(tmp_path)
    zip_path = backup_mod.build_backup_zip(home)
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()

    info = inspect_zip(zip_path, empty_home)
    zip_path.unlink(missing_ok=True)

    assert info.has_stale_entries is False
    assert info.would_overwrite == []


# ── run_daily_backup_if_due ───────────────────────────────────────


def test_auto_backup_creates_zip_on_first_run(tmp_path: Path) -> None:
    """No prior auto-backup → a new autobackup_*.zip is created."""
    home = _seed_home(tmp_path)
    result = backup_mod.run_daily_backup_if_due(home)
    assert result is not None
    assert result.exists()
    assert result.name.startswith("autobackup_")
    # Verify it's a valid zip with at least the settings file.
    with zipfile.ZipFile(result) as zf:
        assert "oik_constants.json" in zf.namelist()


def test_auto_backup_skips_when_recent(tmp_path: Path) -> None:
    """A backup made just now → next call returns None (no duplicate)."""
    import time
    home = _seed_home(tmp_path)
    first = backup_mod.run_daily_backup_if_due(home)
    assert first is not None
    # Should be skipped because the first backup is < 24 h old.
    second = backup_mod.run_daily_backup_if_due(home)
    assert second is None


def test_auto_backup_rotates_old_files(tmp_path: Path) -> None:
    """Auto-backups older than 14 days are deleted after a new one is made."""
    import os, time as _time
    home = _seed_home(tmp_path)
    backups_dir = home / "backups"
    backups_dir.mkdir(exist_ok=True)

    # Plant a stale autobackup (mtime = 15 days ago).
    stale = backups_dir / "autobackup_19700101T000000Z.zip"
    stale.write_bytes(b"PK\x03\x04")
    old_mtime = _time.time() - 15 * 86_400
    os.utime(stale, (old_mtime, old_mtime))

    backup_mod.run_daily_backup_if_due(home)
    # Stale file should be gone; new file should exist.
    assert not stale.exists()
    new_zips = list(backups_dir.glob("autobackup_*.zip"))
    assert len(new_zips) == 1


def test_copy_to_folder_preserves_filename(tmp_path: Path) -> None:
    """The .zip filename carries an ISO timestamp from
    build_backup_zip — the copy must preserve it so successive
    backups don't overwrite each other in the same destination."""
    src = tmp_path / "biracki_odbor_backup_2026-05-30T12-00-00Z.zip"
    src.write_bytes(b"PK\x03\x04")
    dest = tmp_path / "dest"
    final = backup_mod.copy_to_folder(src, dest)
    assert final.name == src.name
    assert final.parent == dest
    assert final.read_bytes() == b"PK\x03\x04"
