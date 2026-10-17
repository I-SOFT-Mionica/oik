"""Filesystem teardown for the Formalizator uninstaller.

Mirrors `scaffold.py`: pure functions over an install directory, no Qt
imports, so the wizard is a thin shell on top and the destructive paths
can be unit-tested headlessly.

Uninstalling removes *everything*, deliberately and without an opt-out.
This app handles real citizens' personal data — full names, JMBGs, home
addresses and ID document numbers — collected door to door. Leaving any
of it behind on a machine that is being decommissioned, handed on, or
simply cleared after a campaign is the failure mode that matters, so
"remove the program but keep my data" is not offered. The wizard gates
the whole operation behind a typed confirmation instead.

What that covers, beyond the obvious install folder:

  * The working directory (`~/Formalizator`), which is where the
    session database lives and is not necessarily the install folder.
  * The pre-rename working directory (`~/Celik`), still present on any
    machine that ran an older build.
  * Per-session preview folders in the system temp directory. These are
    easy to forget and are the worst of the lot: each holds the filled
    PDF declarations, with the file name itself containing the voter's
    JMBG.

The install directory is removed only if it ends up empty, so anything
the operator put there themselves is never taken with it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Per-session preview/print folders (see gui.fillout_screen). The
# pre-rename prefix is included because older builds left these behind
# too, and they hold exactly the same personal data.
_TEMP_PREVIEW_GLOBS = ("formalizator_preview_*", "celik_preview_*")

_UNINSTALLER_EXE_NAME = "Formalizator_Uninstaller.exe"

# Written by scaffold.perform_scaffold — ours to remove.
_PROGRAM_FILES = (
    "Formalizator.exe",
    _UNINSTALLER_EXE_NAME,
    "icon.ico",
    "desktop.ini",
)

# Everything the operator produced. Directories are removed wholesale.
_USER_DATA_FILES = (
    "formalizator.db",
    "export_templates.json",
)
_USER_DATA_DIRS = (
    "templates",       # calibrated templates + their background PDFs
    "export_sources",  # pristine copies of real official spreadsheets
)

_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Formalizator"

# Windows attribute bits — scaffold marks the install folder Read-Only so
# Explorer honours desktop.ini, which must be cleared before removal.
_FILE_ATTRIBUTE_NORMAL = 0x80


@dataclass
class UninstallResult:
    removed_files: list[Path] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)
    base_removed: bool = False
    errors: list[str] = field(default_factory=list)
    #: The uninstaller deferred its own removal to a detached cleanup
    #: step that runs once this process exits.
    self_delete_scheduled: bool = False


def _clear_readonly(path: Path) -> None:
    """The install folder carries Read-Only so Explorer applies our
    folder icon; leaving it set makes removal fail."""
    if os.name != "nt":
        return
    import ctypes

    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(path), _FILE_ATTRIBUTE_NORMAL)
    except (OSError, AttributeError):  # pragma: no cover — Windows-only path
        pass


def _running_executable() -> Path | None:
    """The uninstaller's own .exe, when running as a frozen build.

    Only meaningful for the packaged uninstaller — from source,
    `sys.executable` is the interpreter and never sits inside an install
    folder, so this returns None and nothing below changes."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:  # pragma: no cover — pathological filesystem state
        return None


def _is_running_executable(target: Path) -> bool:
    running = _running_executable()
    if running is None:
        return False
    try:
        return target.resolve() == running
    except OSError:  # pragma: no cover
        return False


def remove_program_files(base_dir: Path | str, result: UninstallResult | None = None) -> UninstallResult:
    base = Path(base_dir)
    result = result or UninstallResult()
    _clear_readonly(base)
    for name in _PROGRAM_FILES:
        target = base / name
        if not target.exists():
            continue
        if _is_running_executable(target):
            # Windows holds an open handle on a running image, so the
            # uninstaller genuinely cannot delete itself from inside
            # itself. That is expected and is handled after this process
            # exits (see _schedule_self_delete) — reporting it as an
            # error here is what made a clean uninstall look broken.
            log.info("deferring removal of the running uninstaller: %s", target)
            continue
        _clear_readonly(target)
        try:
            target.unlink()
            result.removed_files.append(target)
        except OSError as exc:
            log.info("could not remove %s: %s", target, exc)
            result.errors.append(f"{name}: {exc}")
    return result


def _schedule_self_delete(exe: Path, directories: list[Path]) -> bool:
    """Delete the uninstaller and its now-empty folders once this
    process has exited.

    A detached `cmd` waits a few seconds for Windows to release the
    image, removes it, then removes each directory — `rmdir` without
    `/s`, so it succeeds only when the folder is genuinely empty and
    anything the operator left there keeps it alive, exactly as
    `remove_base_if_empty` does. Its working directory is the system
    temp folder, because a process whose CWD is inside the target
    cannot have that target removed out from under it."""
    if os.name != "nt":
        return False
    steps = ["ping 127.0.0.1 -n 4 >nul", f'del /f /q "{exe}"']
    steps += [f'rmdir "{d}"' for d in directories]
    try:
        subprocess.Popen(  # noqa: S603 — fixed command, paths are ours
            ["cmd", "/c", " & ".join(steps)],
            cwd=tempfile.gettempdir(),
            creationflags=(
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
            close_fds=True,
        )
        return True
    except OSError as exc:  # pragma: no cover — spawn failure is not worth blocking on
        log.warning("could not schedule self-deletion: %s", exc)
        return False


def remove_user_data(base_dir: Path | str, result: UninstallResult | None = None) -> UninstallResult:
    """Destructive: removes calibrated templates, export templates and
    the session database."""
    base = Path(base_dir)
    result = result or UninstallResult()
    for name in _USER_DATA_FILES:
        target = base / name
        if target.exists():
            try:
                target.unlink()
                result.removed_files.append(target)
            except OSError as exc:
                result.errors.append(f"{name}: {exc}")
    for name in _USER_DATA_DIRS:
        target = base / name
        if target.is_dir():
            try:
                shutil.rmtree(target)
                result.removed_dirs.append(target)
            except OSError as exc:
                result.errors.append(f"{name}/: {exc}")
    return result


def remove_desktop_shortcut(name: str = "Formalizator") -> Path | None:
    from biracki_odbor.installer.scaffold import _resolve_desktop

    desktop = _resolve_desktop()
    if desktop is None:
        return None
    link = desktop / f"{name}.lnk"
    if not link.exists():
        return None
    try:
        link.unlink()
        return link
    except OSError as exc:
        log.warning("could not remove shortcut %s: %s", link, exc)
        return None


def unregister_from_windows_apps() -> None:
    if os.name != "nt":
        return
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover — permissions edge case
        log.warning("could not unregister from Windows Apps: %s", exc)


def remove_base_if_empty(base_dir: Path | str, result: UninstallResult) -> UninstallResult:
    """Only if nothing is left — anything the operator put in the folder
    themselves keeps it alive rather than being deleted with it."""
    base = Path(base_dir)
    if not base.is_dir():
        return result
    _clear_readonly(base)
    if any(base.iterdir()):
        return result
    try:
        base.rmdir()
        result.base_removed = True
    except OSError as exc:
        result.errors.append(f"{base}: {exc}")
    return result


def remove_temp_previews(result: UninstallResult | None = None) -> UninstallResult:
    """Delete the per-session preview folders.

    Each holds filled PDF declarations, and the file names embed the
    voter's JMBG — so these are personal data sitting in a
    world-readable temp directory, not scratch files."""
    result = result or UninstallResult()
    temp_root = Path(tempfile.gettempdir())
    for pattern in _TEMP_PREVIEW_GLOBS:
        for folder in temp_root.glob(pattern):
            if not folder.is_dir():
                continue
            try:
                shutil.rmtree(folder)
                result.removed_dirs.append(folder)
            except OSError as exc:
                result.errors.append(f"{folder.name}: {exc}")
    return result


def data_locations(base_dir: Path | str) -> list[Path]:
    """Every directory holding this app's data, de-duplicated.

    The working directory is not necessarily the install directory —
    an operator who installed elsewhere still has their session
    database under `~/Formalizator`."""
    from formalizator.core.home_migration import APP_DIR_NAME, LEGACY_DIR_NAME

    candidates = [
        Path(base_dir),
        Path.home() / APP_DIR_NAME,
        Path.home() / LEGACY_DIR_NAME,  # pre-rename, still present on older machines
    ]
    seen: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.is_dir() and not any(resolved.samefile(s) for s in seen):
            seen.append(resolved)
    return seen


def perform_uninstall(base_dir: Path | str, *, remove_shortcut: bool = True) -> UninstallResult:
    """Remove the program and every trace of its data.

    There is no "keep my data" path on purpose — see the module
    docstring. The caller is responsible for confirming with the
    operator first; by the time this runs, the decision is made."""
    result = UninstallResult()
    if remove_shortcut:
        link = remove_desktop_shortcut()
        if link is not None:
            result.removed_files.append(link)

    remove_program_files(base_dir, result)
    for location in data_locations(base_dir):
        remove_user_data(location, result)
        remove_program_files(location, result)
    remove_temp_previews(result)
    unregister_from_windows_apps()

    locations = data_locations(base_dir)
    running = _running_executable()

    def _holds_the_uninstaller(directory: Path) -> bool:
        # Compared resolved, not textually: base_dir arrives from the
        # command line or the registry and may be relative, unnormalised
        # or differently-cased from sys.executable's own path.
        if running is None:
            return False
        try:
            return directory.resolve() == running.parent
        except OSError:  # pragma: no cover
            return False

    # The folder still holding the running uninstaller is never "empty"
    # yet, so asking would only record a misleading error — it is handed
    # to the deferred cleanup below instead.
    deferred = [d for d in {*locations, Path(base_dir)} if _holds_the_uninstaller(d)]
    for location in locations:
        if not _holds_the_uninstaller(location):
            remove_base_if_empty(location, result)
    if not _holds_the_uninstaller(Path(base_dir)):
        remove_base_if_empty(base_dir, result)

    if running is not None and running.name == _UNINSTALLER_EXE_NAME:
        result.self_delete_scheduled = _schedule_self_delete(running, deferred or [running.parent])
    return result


def describe_install(base_dir: Path | str) -> dict:
    """What is actually present, so the wizard can tell the operator
    exactly what they are about to lose."""
    base = Path(base_dir)
    templates = 0
    catalog = base / "templates" / "catalog.json"
    if catalog.exists():
        import json

        try:
            templates = len(json.loads(catalog.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            templates = 0
    return {
        "exists": base.is_dir(),
        "has_data": any((base / n).exists() for n in _USER_DATA_FILES)
        or any((base / n).is_dir() for n in _USER_DATA_DIRS),
        "templates": templates,
    }
