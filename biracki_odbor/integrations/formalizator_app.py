"""Locate, launch, or fetch the Formalizator companion application.

Formalizator is a separate product with its own installer and its own
release cadence; OIK only needs to know whether it is present, where,
and how to start it.

**This module deliberately imports nothing from the `formalizator`
package.** `formalizator.installer.scaffold` imports
`formalizator.core.starter_catalog`, which transitively drags pdfplumber,
reportlab, pypdf and the whole card-reader stack into OIK's PyInstaller
module graph — tens of megabytes in an installer that municipal offices
download over slow links, for three string constants. The constants are
duplicated here instead, and `tests/test_formalizator_launcher.py`
asserts they stay identical to the originals, which is what makes the
duplication safe rather than merely convenient.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

log = logging.getLogger(__name__)

# Mirrors of formalizator.installer.scaffold — see the module docstring.
APP_EXE_NAME = "Formalizator.exe"
SETUP_ASSET_NAME = "Formalizator_Setup.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Formalizator"


@dataclass(frozen=True)
class FormalizatorInstall:
    exe: Path
    base_dir: Path
    version: str = ""   # DisplayVersion from the registry, "" if unknown
    source: str = ""    # "registry" | "default_dir"


def default_install_dir() -> Path:
    """`%USERPROFILE%\\Formalizator` — matches the installer's own default."""
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Formalizator"


def _registry_install() -> FormalizatorInstall | None:
    """Read InstallLocation from the Windows uninstall entry.

    This is the authoritative answer when the operator installed
    somewhere other than the default folder."""
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover — Windows-only
        return None

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            location, _ = winreg.QueryValueEx(key, "InstallLocation")
            try:
                version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            except OSError:
                version = ""
    except (FileNotFoundError, OSError):
        return None

    base = Path(str(location))
    exe = base / APP_EXE_NAME
    if not exe.is_file():
        # Uninstalling by deleting the folder leaves the key behind, so a
        # key alone proves nothing — fall through to the default-dir probe
        # rather than reporting an install that cannot be launched.
        log.info("Formalizator uninstall key points at %s but no exe is there", base)
        return None
    return FormalizatorInstall(exe=exe, base_dir=base, version=str(version), source="registry")


def find_install() -> FormalizatorInstall | None:
    """The installed Formalizator, or None.

    Registry first (handles a custom install folder), then the default
    folder (handles a registry entry that was never written or has been
    cleaned out)."""
    if os.name != "nt":
        return None

    found = _registry_install()
    if found is not None:
        return found

    base = default_install_dir()
    exe = base / APP_EXE_NAME
    if exe.is_file():
        return FormalizatorInstall(exe=exe, base_dir=base, source="default_dir")
    return None


def launch(install: FormalizatorInstall) -> None:
    """Start Formalizator as its own process.

    Detached on purpose: Formalizator is a separate application, and an
    operator closing OIK must not take the form they are filling with
    it. Same flags as integrations.thunderbird uses for the same reason.
    """
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    subprocess.Popen(  # noqa: S603 — a located, verified executable path
        [str(install.exe)],
        cwd=str(install.exe.parent),
        close_fds=True,
        creationflags=creationflags,
    )


def installer_url(oik_download_url: str, server_url: str = "", tag: str = "") -> str:
    """Where to fetch `Formalizator_Setup.exe`.

    Both installers are built from the same tag and published side by
    side, so the Formalizator asset is a sibling of the OIK one. Deriving
    it from the URL the server actually returned keeps the server's own
    path layout authoritative instead of hard-coding it here; the
    `{server}/downloads/{tag}/` form is only a fallback for when no OIK
    URL is available to copy.
    """
    oik_download_url = (oik_download_url or "").strip()
    if oik_download_url:
        return urljoin(oik_download_url, SETUP_ASSET_NAME)

    server_url = (server_url or "").strip().rstrip("/")
    tag = (tag or "").strip()
    if not server_url or not tag:
        return ""
    return f"{server_url}/downloads/{tag}/{SETUP_ASSET_NAME}"
