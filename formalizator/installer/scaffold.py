"""Filesystem work the Formalizator installer performs.

Separated from the wizard GUI so it can be unit-tested headlessly, the
same split the OIK installer uses. Deliberately much smaller than
OIK's: Formalizator keeps its data in the install folder itself, and
the only things that need laying down are the executable, the shared
icon, and the starter forms — which are seeded through the very same
`starter_catalog.seed` the app runs on first launch, so there is one
implementation of "install the bundled forms", not two.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from formalizator.core import starter_catalog

APP_EXE_NAME = "Formalizator.exe"
UNINSTALLER_EXE_NAME = "Formalizator_Uninstaller.exe"

_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Formalizator"


@dataclass
class ScaffoldResult:
    base_dir: Path
    copied_files: list[Path] = field(default_factory=list)
    seeded_forms: list[str] = field(default_factory=list)


def _resources_root() -> Path:
    """Where bundled resources live at dev time and inside a
    PyInstaller one-file bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    root = Path(meipass) if meipass else Path(__file__).resolve().parent.parent.parent
    return root


def shared_icon() -> Path:
    """Formalizator is a companion to the OIK app, not a separate
    product line, so it wears the same icon."""
    return _resources_root() / "biracki_odbor" / "resources" / "icon.ico"


def perform_scaffold(
    base_dir: Path | str, *,
    exe_source: Path | str | None = None,
    uninstaller_source: Path | str | None = None,
) -> ScaffoldResult:
    """Lay out an install into `base_dir`. Returns what changed.

    Re-running is safe: the executables are refreshed, and the starter
    forms are only added when absent, so an upgrade never overwrites a
    template the operator has since tuned.
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []

    for source, name in ((exe_source, APP_EXE_NAME), (uninstaller_source, UNINSTALLER_EXE_NAME)):
        if source is None:
            continue
        source = Path(source)
        if source.exists():
            destination = base / name
            shutil.copyfile(source, destination)
            copied.append(destination)

    icon = shared_icon()
    if icon.exists():
        icon_destination = base / "icon.ico"
        if not icon_destination.exists():
            shutil.copyfile(icon, icon_destination)
            copied.append(icon_destination)
        _apply_folder_icon(base)

    seeded = starter_catalog.seed(base, base / "templates")

    # Only advertise in Windows Settings → Apps once the uninstaller is
    # actually there — an entry whose "Uninstall" button does nothing is
    # worse than no entry at all.
    if (base / UNINSTALLER_EXE_NAME).exists():
        _register_in_windows_apps(base)

    return ScaffoldResult(base_dir=base, copied_files=copied, seeded_forms=seeded)


def _register_in_windows_apps(base_dir: Path) -> None:
    """HKCU Uninstall entry so Formalizator appears in Windows
    Settings → Apps, same as the OIK app registers itself."""
    if os.name != "nt":
        return
    import winreg

    from formalizator import __version__

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Formalizator")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, __version__)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "I-SOFT Мионица")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(base_dir))
            winreg.SetValueEx(
                key, "UninstallString", 0, winreg.REG_SZ,
                str(base_dir / UNINSTALLER_EXE_NAME),
            )
            winreg.SetValueEx(
                key, "DisplayIcon", 0, winreg.REG_SZ, str(base_dir / APP_EXE_NAME) + ",0",
            )
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except OSError as exc:
        import logging

        logging.getLogger(__name__).warning("could not register in Windows Apps: %s", exc)


def _apply_folder_icon(folder: Path) -> None:
    """Reuses the OIK installer's own desktop.ini handling so the
    install folder shows the product icon in Explorer. No-op off
    Windows."""
    from biracki_odbor.installer.scaffold import _apply_folder_icon as apply

    apply(folder)


def create_desktop_shortcut(target: Path | str, name: str = "Formalizator") -> Path | None:
    """Reuses the OIK installer's shortcut helper, which already
    resolves OneDrive-redirected Desktop folders and writes the .lnk
    through PowerShell — hard-won behaviour worth sharing rather than
    reimplementing."""
    from biracki_odbor.installer.scaffold import create_desktop_shortcut as create

    return create(target, name=name)


def existing_install_info(base_dir: Path | str) -> dict:
    """Whether an install is already present, and what would survive
    re-running the installer over it."""
    base = Path(base_dir)
    if not base.exists():
        return {"exists": False, "preserved": []}
    preserved: list[str] = []
    if (base / "templates" / "catalog.json").exists():
        preserved.append("templates/")
    if (base / "export_templates.json").exists():
        preserved.append("export_templates.json")
    if (base / "formalizator.db").exists():
        preserved.append("formalizator.db")
    return {
        "exists": bool(preserved) or (base / APP_EXE_NAME).exists(),
        "preserved": preserved,
    }
