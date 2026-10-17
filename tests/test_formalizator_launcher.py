"""Tests for biracki_odbor.integrations.formalizator_app.

OIK locates and starts the Formalizator companion app without importing
the `formalizator` package — see that module's docstring for why. These
tests are what make the duplicated constants safe.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from biracki_odbor.integrations import formalizator_app as fa


def test_the_duplicated_constants_match_formalizator_itself() -> None:
    """The duplication exists to keep pdfplumber/reportlab/pypdf out of
    OIK's frozen bundle. It is only safe while the copies agree, so this
    test is the reason it is allowed at all."""
    from formalizator.installer import scaffold

    assert fa.APP_EXE_NAME == scaffold.APP_EXE_NAME
    assert fa.UNINSTALL_KEY == scaffold._UNINSTALL_KEY  # noqa: SLF001


def test_oik_does_not_import_formalizator() -> None:
    """A stray `from formalizator...` here would pull that whole package
    into OIK.exe — tens of MB over municipal connections."""
    source = Path(fa.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "import formalizator" not in code
    assert "from formalizator" not in code


def _fake_winreg(monkeypatch, values: dict | None, *, missing: bool = False):
    """Stand in for the Windows registry; the real one is unavailable on
    CI and must never be written to from a test."""
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER = 1

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def open_key(_root, _path):
        if missing:
            raise FileNotFoundError("no such key")
        return _Key()

    def query(_key, name):
        if values is None or name not in values:
            raise OSError("no such value")
        return values[name], 1

    mod.OpenKey = open_key
    mod.QueryValueEx = query
    monkeypatch.setitem(sys.modules, "winreg", mod)
    monkeypatch.setattr(fa.os, "name", "nt")


def test_the_registry_location_is_preferred(monkeypatch, tmp_path: Path) -> None:
    """An operator who installed somewhere other than the default folder
    must still be found."""
    custom = tmp_path / "D_Programs" / "Formalizator"
    custom.mkdir(parents=True)
    (custom / fa.APP_EXE_NAME).write_bytes(b"MZ")
    _fake_winreg(monkeypatch, {"InstallLocation": str(custom), "DisplayVersion": "1.2.3"})

    found = fa.find_install()

    assert found is not None
    assert found.exe == custom / fa.APP_EXE_NAME
    assert found.version == "1.2.3"
    assert found.source == "registry"


def test_a_stale_registry_key_does_not_shadow_a_real_install(
    monkeypatch, tmp_path: Path,
) -> None:
    """Uninstalling by deleting the folder leaves the key behind, so a
    key alone proves nothing. Reporting an install that cannot be
    launched is worse than reporting none."""
    gone = tmp_path / "deleted"
    default = tmp_path / "home" / "Formalizator"
    default.mkdir(parents=True)
    (default / fa.APP_EXE_NAME).write_bytes(b"MZ")
    _fake_winreg(monkeypatch, {"InstallLocation": str(gone)})
    monkeypatch.setattr(fa, "default_install_dir", lambda: default)

    found = fa.find_install()

    assert found is not None
    assert found.source == "default_dir"
    assert found.exe == default / fa.APP_EXE_NAME


def test_no_registry_entry_falls_back_to_the_default_folder(
    monkeypatch, tmp_path: Path,
) -> None:
    default = tmp_path / "Formalizator"
    default.mkdir()
    (default / fa.APP_EXE_NAME).write_bytes(b"MZ")
    _fake_winreg(monkeypatch, None, missing=True)
    monkeypatch.setattr(fa, "default_install_dir", lambda: default)

    found = fa.find_install()

    assert found is not None
    assert found.source == "default_dir"


def test_nothing_installed_reports_nothing(monkeypatch, tmp_path: Path) -> None:
    _fake_winreg(monkeypatch, None, missing=True)
    monkeypatch.setattr(fa, "default_install_dir", lambda: tmp_path / "absent")

    assert fa.find_install() is None


def test_launching_detaches_so_closing_oik_does_not_kill_it(
    monkeypatch, tmp_path: Path,
) -> None:
    """Formalizator is a separate application — an operator closing OIK
    must not lose the form they are filling."""
    exe = tmp_path / "Formalizator" / fa.APP_EXE_NAME
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    captured = {}
    monkeypatch.setattr(fa.os, "name", "nt")
    monkeypatch.setattr(
        fa.subprocess, "Popen",
        lambda args, **kw: captured.update({"args": args, **kw}),
    )

    fa.launch(fa.FormalizatorInstall(exe=exe, base_dir=exe.parent))

    assert captured["args"] == [str(exe)]
    assert captured["cwd"] == str(exe.parent)
    assert captured["close_fds"] is True
    flags = captured["creationflags"]
    assert flags & subprocess.DETACHED_PROCESS
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP


# ── Installer URL ────────────────────────────────────────────────────


def test_the_installer_is_a_sibling_of_the_oik_one() -> None:
    """Both installers are built from the same tag and published side by
    side, so deriving one from the other keeps the server's own layout
    authoritative instead of hard-coding a path here."""
    url = fa.installer_url("https://api.isoft.rs/downloads/v0.82.1/OIK_Setup.exe")

    assert url == "https://api.isoft.rs/downloads/v0.82.1/Formalizator_Setup.exe"


def test_the_url_falls_back_to_server_and_tag() -> None:
    url = fa.installer_url("", "https://api.isoft.rs", "v0.82.1")

    assert url == "https://api.isoft.rs/downloads/v0.82.1/Formalizator_Setup.exe"


def test_a_trailing_slash_on_the_server_does_not_double_up() -> None:
    url = fa.installer_url("", "https://api.isoft.rs/", "v0.82.1")

    assert "//downloads" not in url.replace("https://", "")


def test_no_usable_information_yields_no_url() -> None:
    """An empty string is a decidable "we cannot offer this"; a malformed
    URL would become a confusing download failure instead."""
    assert fa.installer_url("", "", "") == ""
    assert fa.installer_url("", "https://api.isoft.rs", "") == ""
