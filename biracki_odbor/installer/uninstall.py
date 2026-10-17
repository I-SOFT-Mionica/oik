"""Filesystem teardown logic for the uninstaller.

Mirrors `scaffold.py`: pure functions over an install directory, no Qt
imports, so the wizard can be a thin shell on top and the destructive
paths can be unit-tested headlessly.

Three layers of removal, each opt-in:

  1. Desktop shortcut (`OIK.lnk` on the user's Desktop).
  2. Program files written by the installer (Biracki_Odbor.exe, icon.ico,
     desktop.ini, УПУТСТВО.txt). Folder Read-Only flag is cleared first.
  3. User data (configs, master/, popunjeni/, resenja/, sablon/,
     stranka_fajlovi/, corrections.log, places_genitive.json). This is
     the destructive path — wizard gates it behind a typed-confirmation.

After layers 2 and 3 both run, the base directory itself is removed iff
empty. Layer 3 without layer 2 leaves the .exe sitting next to an empty
data set — uncommon, but supported for "wipe my data, reinstall later".
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from biracki_odbor import app_paths


log = logging.getLogger(__name__)


# Files installed by scaffold.perform_scaffold that we own and can safely
# remove. User-created files in the same directory are NOT in this list —
# they fall under user data (layer 3) or stay behind.
_PROGRAM_FILES = (
    "OIK.exe",
    "OIK_Uninstaller.exe",
    "icon.ico",
    "desktop.ini",
    "УПУТСТВО.txt",
)

# Files holding user-edited state: configs, license, audit logs, and the
# per-workflow customization/template files (places declension overrides,
# obrazloženje + izmena templates). This list previously predated the
# проширени workflow, licensing, and generation-log features and silently
# left them behind on "БРИШИ" — found 2026-07-10 doing a full-wipe test.
# Keep in sync with `core/backup.py`'s DEFAULT_INCLUDE (same underlying
# set, different purpose: backup keeps only what's needed to restore;
# this one must list literally everything so nothing survives a wipe).
_USER_DATA_FILES = (
    "oik_constants.json",
    "election_config.json",
    "app_settings.json",
    "places_genitive.json",
    "places_prepositions.json",
    "obrazlozenje.json",
    "obrazlozenje_prosireni.json",
    "license.dat",
    "posmatraci.json",
    "generation_log.json",
    "corrections.log",
    "corrections_prosireni.log",
    "izmena_obrazlozenje_stalni.json",
    "izmena_obrazlozenje_prosireni.json",
)

# Subdirs that hold user-generated data. Removed wholesale under layer 3.
# Derived from `app_paths.SUBDIRS` (the authoritative directory layout)
# instead of a separately hand-maintained list, so a future workflow/tab
# addition can't silently drift out of sync again the way this one did —
# `SUBDIRS` already has to be updated for the app itself to work. `dict.
# fromkeys` dedupes while preserving order (SUBDIRS lists some nested
# entries like "posmatraci/liste" purely for scaffold.py's mkdir pass —
# rmtree on the top-level "posmatraci" already recurses into those).
_USER_DATA_DIRS = tuple(dict.fromkeys(sub.split("/", 1)[0] for sub in app_paths.SUBDIRS)) + (
    "backups",  # not used yet, but reserve the name (see TODO §6)
)


@dataclass
class UninstallPlan:
    """What the user has chosen to remove. Defaults are conservative."""

    remove_shortcut: bool = True
    remove_program_files: bool = True
    remove_user_data: bool = False


@dataclass
class UninstallResult:
    removed_files: list[Path] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable reasons
    errors: list[str] = field(default_factory=list)


# ── Detection ──────────────────────────────────────────────────────


def find_install_dir() -> Path | None:
    """Best guess at where the app is installed.

    Honors `BIRACKI_ODBOR_HOME` env var (same as `app_paths.home`) so a
    custom-install user gets pointed at the right place. Default is
    `%USERPROFILE%\\OIK`. Returns None only if neither exists.
    """
    override = os.environ.get("BIRACKI_ODBOR_HOME")
    if override:
        p = Path(override)
        if p.exists():
            return p
    profile = os.environ.get("USERPROFILE")
    if profile:
        default = Path(profile) / "OIK"
        if default.exists():
            return default
    return None


def describe_install(base_dir: Path | str) -> dict:
    """Return what's present at `base_dir` so the wizard can show the user.

    Doesn't delete anything. Lists are sorted for deterministic display.
    """
    base = Path(base_dir)
    info: dict = {
        "exists": base.exists(),
        "program_files": [],
        "user_data_files": [],
        "user_data_dirs": [],  # only the non-empty ones
    }
    if not base.exists():
        return info
    for name in _PROGRAM_FILES:
        if (base / name).exists():
            info["program_files"].append(name)
    for name in _USER_DATA_FILES:
        if (base / name).exists():
            info["user_data_files"].append(name)
    for name in _USER_DATA_DIRS:
        d = base / name
        if d.exists():
            info["user_data_dirs"].append({
                "name": name,
                "entries": sum(1 for _ in d.iterdir()),
            })
    return info


# ── Helpers ────────────────────────────────────────────────────────


def _clear_attributes(path: Path) -> None:
    """Strip Read-Only/Hidden/System bits on Windows so delete can proceed.

    No-op on non-Windows. Folder gets Read-Only via `_apply_folder_icon`
    in scaffold.py; that flag blocks `shutil.rmtree` on some Windows
    setups. desktop.ini is Hidden+System and refuses delete until cleared.
    """
    if os.name != "nt":
        return
    import ctypes
    FILE_ATTRIBUTE_NORMAL = 0x80
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_NORMAL)
    except (OSError, AttributeError) as e:
        log.warning("clear_attributes failed for %s: %s", path, e)


def _safe_unlink(path: Path, result: UninstallResult) -> None:
    """Delete a single file, recording success/failure in `result`."""
    try:
        _clear_attributes(path)
        path.unlink()
        result.removed_files.append(path)
        log.info("removed file %s", path)
    except FileNotFoundError:
        pass
    except OSError as e:
        msg = f"{path.name}: {e}"
        result.errors.append(msg)
        log.warning("could not remove %s: %s", path, e)


def _safe_rmtree(path: Path, result: UninstallResult) -> None:
    """Recursively delete a directory."""
    if not path.exists():
        return
    try:
        _clear_attributes(path)
        shutil.rmtree(path)
        result.removed_dirs.append(path)
        log.info("removed dir %s", path)
    except OSError as e:
        msg = f"{path.name}/: {e}"
        result.errors.append(msg)
        log.warning("could not remove dir %s: %s", path, e)


# ── Layer 1: desktop shortcut ──────────────────────────────────────


def remove_desktop_shortcut(name: str = "OIK") -> Path | None:
    """Remove the `{name}.lnk` from the user's Desktop if present.

    Returns the path that was deleted, or None if nothing was there.
    Cross-platform safe (no-op when Desktop isn't resolvable).
    """
    # Reuse the installer's robust Desktop resolution (handles OneDrive).
    from biracki_odbor.installer.scaffold import _resolve_desktop
    desktop = _resolve_desktop()
    if desktop is None:
        return None
    lnk = desktop / f"{name}.lnk"
    if not lnk.exists():
        return None
    try:
        lnk.unlink()
        log.info("removed desktop shortcut %s", lnk)
        return lnk
    except OSError as e:
        log.warning("could not remove %s: %s", lnk, e)
        return None


_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\OIK"


def _unregister_from_windows_apps() -> None:
    """Remove the HKCU Uninstall entry so OIK disappears from Windows Settings → Apps."""
    if os.name != "nt":
        return
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("could not unregister from Windows Apps: %s", exc)


# ── Layer 2: program files ─────────────────────────────────────────


def remove_program_files(base_dir: Path | str) -> UninstallResult:
    """Delete files written by the installer (NOT user data)."""
    base = Path(base_dir)
    result = UninstallResult()
    if not base.exists():
        result.skipped.append(f"{base} не постоји")
        return result
    _unregister_from_windows_apps()
    # Clear the folder Read-Only flag set by `_apply_folder_icon` so subsequent
    # unlinks aren't blocked on some Windows setups.
    _clear_attributes(base)
    for name in _PROGRAM_FILES:
        _safe_unlink(base / name, result)
    return result


# ── Layer 3: user data ─────────────────────────────────────────────


def remove_user_data(base_dir: Path | str) -> UninstallResult:
    """Delete all user-authored state. **Destructive.**

    Removes configs, audit log, override file, and every populated
    subdirectory. Empty directories that were never touched also go.
    """
    base = Path(base_dir)
    result = UninstallResult()
    if not base.exists():
        result.skipped.append(f"{base} не постоји")
        return result
    _clear_attributes(base)
    for name in _USER_DATA_FILES:
        _safe_unlink(base / name, result)
    for name in _USER_DATA_DIRS:
        _safe_rmtree(base / name, result)
    return result


# ── Final sweep ────────────────────────────────────────────────────


def remove_base_dir_if_empty(base_dir: Path | str) -> Path | None:
    """Remove the install root iff nothing the user might want remains.

    Skips if there are unexpected files (anything the user dropped in
    themselves) so we never silently delete content we don't recognize.
    """
    base = Path(base_dir)
    if not base.exists():
        return None
    leftover = list(base.iterdir())
    if leftover:
        log.info("leaving %s in place — non-empty: %d entries", base, len(leftover))
        return None
    try:
        _clear_attributes(base)
        base.rmdir()
        log.info("removed empty install dir %s", base)
        return base
    except OSError as e:
        log.warning("could not rmdir %s: %s", base, e)
        return None


# ── Orchestration ──────────────────────────────────────────────────


def execute(base_dir: Path | str, plan: UninstallPlan) -> UninstallResult:
    """Run the chosen removal steps in the right order and aggregate results.

    Order matters:
      1. Shortcut (cheapest, no path dependencies)
      2. Program files
      3. User data
      4. Empty base-dir sweep (only if both layer 2 + 3 ran)
    """
    base = Path(base_dir)
    agg = UninstallResult()

    if plan.remove_shortcut:
        lnk = remove_desktop_shortcut()
        if lnk is not None:
            agg.removed_files.append(lnk)

    if plan.remove_program_files:
        sub = remove_program_files(base)
        agg.removed_files.extend(sub.removed_files)
        agg.removed_dirs.extend(sub.removed_dirs)
        agg.skipped.extend(sub.skipped)
        agg.errors.extend(sub.errors)

    if plan.remove_user_data:
        sub = remove_user_data(base)
        agg.removed_files.extend(sub.removed_files)
        agg.removed_dirs.extend(sub.removed_dirs)
        agg.skipped.extend(sub.skipped)
        agg.errors.extend(sub.errors)

    if plan.remove_program_files and plan.remove_user_data:
        rd = remove_base_dir_if_empty(base)
        if rd is not None:
            agg.removed_dirs.append(rd)

    return agg
