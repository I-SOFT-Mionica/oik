"""Filesystem scaffolding logic the installer runs.

Separated from the installer GUI so it can be unit-tested headlessly.
The installer GUI is just a thin wizard on top of these functions.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Subdir layout owned by the installed app.
# Derived from all registered WorkflowSpecs so a new workflow automatically
# gets its directories created on fresh install without touching this file.
def _build_subdirs() -> tuple[str, ...]:
    from biracki_odbor.core.workflow import all_specs
    dirs: list[str] = [
        # Workflow-independent
        "sablon", "cache", "log", "resenja_izmene",
        # Observer accreditation (nested dirs listed explicitly)
        "posmatraci", "posmatraci/liste", "posmatraci/legitimacije",
    ]
    for spec in all_specs():
        p = spec.paths
        dirs.extend([
            p.stranke_subdir,
            p.popunjeni_subdir,
            p.popunjeni_odbijeno_subdir,
            p.master_subdir,
            p.resenja_subdir,
            p.audit_subdir,
        ])
    # Stable order, no duplicates
    seen: set[str] = set()
    result: list[str] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return tuple(result)


SUBDIRS = _build_subdirs()

# Windows file-attribute bits used to enable a custom folder icon.
_FILE_ATTRIBUTE_READONLY = 0x01
_FILE_ATTRIBUTE_HIDDEN = 0x02
_FILE_ATTRIBUTE_SYSTEM = 0x04


@dataclass
class ScaffoldResult:
    base_dir: Path
    created_dirs: list[Path]
    copied_files: list[Path]
    preserved_files: list[Path]


def _resources_root() -> Path:
    """Find the bundled resources/ dir at dev-time AND inside PyInstaller bundle."""
    # PyInstaller sets sys._MEIPASS; in dev, fall back to relative paths
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "biracki_odbor" / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def perform_scaffold(
    base_dir: Path | str,
    *,
    upgrade: bool = False,
    exe_source: Path | str | None = None,
    uninstaller_source: Path | str | None = None,
) -> ScaffoldResult:
    """Lay out the install. Returns what changed.

    Args:
      base_dir: target directory, e.g. %USERPROFILE%\\OIK\\.
      upgrade: if True, preserve oik_constants.json, election_config.json,
               corrections.log, and the popunjeni/master/resenja contents.
      exe_source: optional path to OIK.exe to copy in. None means
                  skip the copy step (useful in tests).
      uninstaller_source: optional path to OIK_Uninstaller.exe
                  to copy in. Same shape as `exe_source`. Dropped next to
                  the main exe so operators can do clean install/uninstall
                  test cycles without hunting for a separate tool.
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    copied: list[Path] = []
    preserved: list[Path] = []

    # Subdirs
    for sub in SUBDIRS:
        d = base / sub
        if not d.exists():
            d.mkdir(parents=True)
            created.append(d)

    res = _resources_root()
    templates = res / "templates"

    # Configs: write examples ONLY if absent (preserve on upgrade)
    targets = {
        "oik_constants.example.json": "oik_constants.json",
        "election_config.example.json": "election_config.json",
    }
    for src_name, dst_name in targets.items():
        dst = base / dst_name
        src = templates / src_name
        if dst.exists():
            preserved.append(dst)
        elif src.exists():
            shutil.copyfile(src, dst)
            copied.append(dst)

    # УПУТСТВО.txt — always rewrite, never user-edited
    upustvo = res / "upustvo.txt"
    if upustvo.exists():
        out = base / "УПУТСТВО.txt"
        shutil.copyfile(upustvo, out)
        copied.append(out)

    # Blank Stalni_sastav.xlsx — drop into sablon/ if absent so users have a
    # fill-in-the-blanks workbook the very first time they open the app.
    sablon_template = base / "sablon" / "Stalni_sastav.xlsx"
    if not sablon_template.exists():
        from biracki_odbor.core.template import build_blank_template
        build_blank_template(sablon_template)
        copied.append(sablon_template)
    else:
        preserved.append(sablon_template)

    # icon.ico + desktop.ini so Windows Explorer shows the OIK icon on the
    # install folder. Both files are idempotent — re-running is safe.
    icon_src = res / "icon.ico"
    if icon_src.exists():
        icon_dst = base / "icon.ico"
        if not icon_dst.exists():
            shutil.copyfile(icon_src, icon_dst)
            copied.append(icon_dst)
        _apply_folder_icon(base)

    # Main .exe
    if exe_source is not None:
        src_exe = Path(exe_source)
        if src_exe.exists():
            dst_exe = base / "OIK.exe"
            shutil.copyfile(src_exe, dst_exe)
            copied.append(dst_exe)

    # Uninstaller .exe — dropped beside the main exe so the operator
    # can run "Uninstall" without searching for a separate download.
    # Overwrite on upgrade so the latest cleanup logic wins.
    if uninstaller_source is not None:
        src_un = Path(uninstaller_source)
        if src_un.exists():
            dst_un = base / "OIK_Uninstaller.exe"
            shutil.copyfile(src_un, dst_un)
            copied.append(dst_un)

    # corrections.log: never overwrite — preserve audit trail
    log = base / "corrections.log"
    if log.exists():
        preserved.append(log)

    # Bake licensing_server_url into app_settings.json. On fresh install the
    # file is absent so we write defaults + URL. On reinstall we read the
    # existing prefs (email_client, debug_logging) and only update the URL,
    # so operator preferences survive an upgrade. No-op when the build was
    # made without a URL (dev / CI builds keep licensing DISABLED).
    from biracki_odbor._build_config import LICENSING_SERVER_URL
    if LICENSING_SERVER_URL:
        from biracki_odbor.config import settings as _settings_mod
        settings_path = base / "app_settings.json"
        s = _settings_mod.load(settings_path)  # returns defaults if absent
        s.licensing_server_url = LICENSING_SERVER_URL
        _settings_mod.save(s, settings_path)

    _register_in_windows_apps(base)

    return ScaffoldResult(
        base_dir=base, created_dirs=created,
        copied_files=copied, preserved_files=preserved,
    )


_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\OIK"


def _register_in_windows_apps(base_dir: Path) -> None:
    """Write the HKCU Uninstall entry so OIK appears in Windows Settings → Apps."""
    if os.name != "nt":
        return
    import winreg
    from biracki_odbor import __version__
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "OIK")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, __version__)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "I-SOFT Мионица")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(base_dir))
            winreg.SetValueEx(
                key, "UninstallString", 0, winreg.REG_SZ,
                str(base_dir / "OIK_Uninstaller.exe"),
            )
            winreg.SetValueEx(
                key, "DisplayIcon", 0, winreg.REG_SZ,
                str(base_dir / "OIK.exe") + ",0",
            )
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except OSError as exc:
        import logging as _log
        _log.getLogger(__name__).warning("could not register in Windows Apps: %s", exc)


def _apply_folder_icon(folder: Path) -> None:
    """Drop a desktop.ini next to `folder/icon.ico` so Explorer uses our icon.

    Windows requires:
      - desktop.ini in the folder referencing IconResource
      - the folder itself marked Read-Only OR System
      - desktop.ini marked Hidden + System

    Idempotent: re-runs on upgrade clear the hidden+system flags on the
    existing .ini before rewriting, then restore them.
    No-op on non-Windows platforms.
    """
    if os.name != "nt":
        return
    import ctypes
    set_attr = ctypes.windll.kernel32.SetFileAttributesW
    FILE_ATTRIBUTE_NORMAL = 0x80

    ini = folder / "desktop.ini"
    if ini.exists():
        set_attr(str(ini), FILE_ATTRIBUTE_NORMAL)  # unhide before rewrite
    ini.write_text(
        "[.ShellClassInfo]\r\n"
        "IconResource=icon.ico,0\r\n"
        "IconFile=icon.ico\r\n"
        "IconIndex=0\r\n",
        encoding="utf-8",
    )
    set_attr(str(folder), _FILE_ATTRIBUTE_READONLY)
    set_attr(str(ini), _FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM)


def _resolve_desktop() -> Path | None:
    """Find the canonical Desktop path, honoring Win 11 OneDrive redirection.

    Order of attempts:
      1. SHGetFolderPathW(CSIDL_DESKTOPDIRECTORY) — what Explorer itself uses.
      2. %USERPROFILE%\\OneDrive\\Desktop (personal OneDrive).
      3. %USERPROFILE%\\OneDrive*\\Desktop globbed (work / school accounts
         have folders like "OneDrive - Company Name").
      4. %USERPROFILE%\\Desktop — last-resort non-OneDrive setup.
    """
    if os.name != "nt":
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    CSIDL_DESKTOPDIRECTORY = 0x10
    try:
        rc = ctypes.windll.shell32.SHGetFolderPathW(0, CSIDL_DESKTOPDIRECTORY, 0, 0, buf)
        if rc == 0:
            p = Path(buf.value)
            if p.exists():
                return p
    except (OSError, AttributeError):
        pass
    profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    # Personal OneDrive, then Work/School variants ("OneDrive - Company"),
    # then plain Desktop. sorted() so result is deterministic.
    candidates: list[Path] = [profile / "OneDrive" / "Desktop"]
    try:
        for od in sorted(profile.glob("OneDrive*")):
            cand = od / "Desktop"
            if cand not in candidates:
                candidates.append(cand)
    except OSError:
        pass
    candidates.append(profile / "Desktop")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def create_desktop_shortcut(target_path: Path | str, name: str = "OIK") -> Path | None:
    """Create a .lnk on the user's Desktop using Windows-specific tooling.

    `target_path` may be an .exe (WorkingDirectory = its containing folder,
    icon taken from the exe itself) or a plain folder (WorkingDirectory = the
    folder itself, no custom IconLocation — Explorer's own folder icon
    applies) — a .lnk can target a directory directly, same as any "folder
    shortcut" a user drags to their own Desktop.

    Returns the path to the .lnk on success, None if the tool isn't available
    (e.g. cross-platform dev). Best-effort: failures are logged but don't raise.
    """
    import logging
    log = logging.getLogger(__name__)

    if os.name != "nt":
        return None
    desktop = _resolve_desktop()
    if desktop is None:
        log.warning("create_desktop_shortcut: could not resolve Desktop path")
        return None
    lnk = desktop / f"{name}.lnk"
    target = Path(target_path)
    if not target.exists():
        log.warning("create_desktop_shortcut: target missing at %s", target)
        return None
    is_dir = target.is_dir()
    working_dir = target if is_dir else target.parent
    icon_line = "" if is_dir else f'$Shortcut.IconLocation = "{target},0";'
    # Use PowerShell to drop a shortcut — no external libs needed.
    ps_script = (
        f'$WshShell = New-Object -ComObject WScript.Shell;'
        f'$Shortcut = $WshShell.CreateShortcut("{lnk}");'
        f'$Shortcut.TargetPath = "{target}";'
        f'$Shortcut.WorkingDirectory = "{working_dir}";'
        f'{icon_line}'
        f'$Shortcut.Save()'
    )
    import base64
    import subprocess
    # -EncodedCommand takes a UTF-16 LE base64 blob. This avoids the OEM-codepage
    # mangling that broke Cyrillic shortcut names when passed via -Command.
    encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
    # Suppress the brief PowerShell black-console flash on user's screen.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            check=True, capture_output=True, creationflags=creationflags,
        )
        # PowerShell can report success while the .lnk silently never lands
        # (rare, but seen with antivirus quarantines). Verify before returning.
        if not lnk.exists():
            log.warning(
                "create_desktop_shortcut: powershell reported success but %s is missing",
                lnk,
            )
            return None
        log.info("create_desktop_shortcut: wrote %s", lnk)
        return lnk
    except subprocess.CalledProcessError as e:
        log.warning(
            "create_desktop_shortcut: powershell failed (rc=%s) for desktop=%s target=%s; stderr=%s",
            e.returncode, desktop, target, (e.stderr or b"").decode("utf-8", "replace"),
        )
        return None
    except FileNotFoundError:
        log.warning("create_desktop_shortcut: powershell.exe not found in PATH")
        return None


def existing_install_info(base_dir: Path | str) -> dict:
    """Detect whether an install already exists and what would be preserved."""
    base = Path(base_dir)
    if not base.exists():
        return {"exists": False, "preserved": []}
    preserved: list[str] = []
    for name in ("oik_constants.json", "election_config.json", "corrections.log"):
        if (base / name).exists():
            preserved.append(name)
    for sub in ("popunjeni", "master", "resenja"):
        d = base / sub
        if d.exists() and any(d.iterdir()):
            preserved.append(f"{sub}/")
    return {"exists": preserved or (base / "OIK.exe").exists(),
            "preserved": preserved}
