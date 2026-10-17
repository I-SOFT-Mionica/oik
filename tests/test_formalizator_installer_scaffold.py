"""Tests for formalizator.installer.scaffold — the filesystem half of
the setup wizard, kept separate from the GUI so it can run headlessly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formalizator.core import starter_catalog
from formalizator.installer import scaffold


@pytest.fixture(autouse=True)
def _no_real_registry_writes(monkeypatch):
    """Keep scaffolding out of the developer's actual registry.

    perform_scaffold registers an Add/Remove Programs entry via HKCU.
    Run from a test that points it at a pytest tmp_path, that leaves a
    real uninstall entry on the machine aimed at a folder which is then
    deleted -- and OIK's Formalizator tab, which probes exactly that key
    to decide whether Formalizator is installed, then believes it is.
    Found while building that tab, from a key a previous run had left
    behind.
    """
    from formalizator.installer import scaffold as _scaffold
    monkeypatch.setattr(_scaffold, "_register_in_windows_apps", lambda *_a, **_kw: None)
    from biracki_odbor.installer import scaffold as _oik_scaffold
    monkeypatch.setattr(_oik_scaffold, "_register_in_windows_apps", lambda *_a, **_kw: None)


def _fake_starter_root(tmp_path: Path, monkeypatch) -> Path:
    """A synthetic `resources/starter/` so these tests verify the
    scaffold's own seeding behaviour rather than depending on whatever
    real forms happen to be bundled — there may be none at all between
    election cycles, by design."""
    root = tmp_path / "fake_starter"
    root.mkdir()
    (root / "form.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "export.xlsx").write_bytes(b"fake xlsx")
    (root / "catalog.json").write_text(json.dumps([{
        "name": "Тест образац", "background_pdf_path": "form.pdf",
        "positions": [{"field_key": "full_name", "page_index": 0, "x": 1.0, "y": 1.0}],
    }]), encoding="utf-8")
    (root / "export_templates.json").write_text(json.dumps([{
        "name": "Тест образац — извоз", "source_file": "export.xlsx", "columns": [],
    }]), encoding="utf-8")
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: root)
    return root


def test_scaffold_creates_the_install_folder(tmp_path: Path) -> None:
    base = tmp_path / "Formalizator"

    result = scaffold.perform_scaffold(base)

    assert base.is_dir()
    assert result.base_dir == base


def test_scaffold_copies_the_application_exe(tmp_path: Path) -> None:
    source = tmp_path / "built" / "Formalizator.exe"
    source.parent.mkdir()
    source.write_bytes(b"MZ fake exe")
    base = tmp_path / "install"

    result = scaffold.perform_scaffold(base, exe_source=source)

    installed = base / scaffold.APP_EXE_NAME
    assert installed.exists()
    assert installed.read_bytes() == b"MZ fake exe"
    assert installed in result.copied_files


def test_scaffold_installs_the_starter_forms(tmp_path: Path, monkeypatch) -> None:
    """A fresh install is usable immediately when there are forms
    calibrated for this cycle to bundle — see the "no bundled forms"
    test below for the equally-important other half: between cycles,
    seeding zero forms must not be an error either."""
    _fake_starter_root(tmp_path, monkeypatch)
    base = tmp_path / "install"

    result = scaffold.perform_scaffold(base)

    assert result.seeded_forms
    assert (base / "templates" / "catalog.json").exists()
    assert (base / "export_templates.json").exists()


def test_scaffold_with_no_bundled_forms_still_installs_cleanly(tmp_path: Path, monkeypatch) -> None:
    """The actual state of this repo between election cycles:
    `resources/starter/` is deliberately blank until the next cycle's
    official forms are calibrated. The app and icon still have to
    install correctly with nothing to seed."""
    empty_root = tmp_path / "empty_starter"
    empty_root.mkdir()
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: empty_root)
    base = tmp_path / "install"

    result = scaffold.perform_scaffold(base)

    assert result.seeded_forms == []
    assert base.is_dir()


def test_reinstalling_preserves_existing_forms(tmp_path: Path, monkeypatch) -> None:
    """Running setup again over an install must not throw away work the
    operator has done since."""
    from formalizator.core import template_catalog

    _fake_starter_root(tmp_path, monkeypatch)
    base = tmp_path / "install"
    scaffold.perform_scaffold(base)
    catalog_dir = base / "templates"
    name = template_catalog.load_catalog(catalog_dir)[0].name
    edited = template_catalog.find_by_name(catalog_dir, name)
    edited.positions = []
    template_catalog.save_template(catalog_dir, edited)

    result = scaffold.perform_scaffold(base)

    assert result.seeded_forms == []
    assert template_catalog.find_by_name(catalog_dir, name).positions == []


def test_scaffold_is_repeatable(tmp_path: Path) -> None:
    source = tmp_path / "Formalizator.exe"
    source.write_bytes(b"MZ v1")
    base = tmp_path / "install"
    scaffold.perform_scaffold(base, exe_source=source)

    source.write_bytes(b"MZ v2")
    scaffold.perform_scaffold(base, exe_source=source)

    assert (base / scaffold.APP_EXE_NAME).read_bytes() == b"MZ v2"


def test_existing_install_info_reports_a_fresh_folder(tmp_path: Path) -> None:
    info = scaffold.existing_install_info(tmp_path / "nothing-here")

    assert info["exists"] is False
    assert info["preserved"] == []


def test_existing_install_info_lists_what_survives(tmp_path: Path, monkeypatch) -> None:
    _fake_starter_root(tmp_path, monkeypatch)
    base = tmp_path / "install"
    scaffold.perform_scaffold(base)
    (base / "formalizator.db").write_bytes(b"sqlite")

    info = scaffold.existing_install_info(base)

    assert info["exists"] is True
    assert "templates/" in info["preserved"]
    assert "export_templates.json" in info["preserved"]
    assert "formalizator.db" in info["preserved"]


def test_shared_icon_points_at_the_main_apps_icon() -> None:
    """Formalizator is a companion to OIK, so it deliberately wears the
    same icon rather than shipping its own."""
    icon = scaffold.shared_icon()

    assert icon.name == "icon.ico"
    assert "biracki_odbor" in icon.parts
    assert icon.exists()
