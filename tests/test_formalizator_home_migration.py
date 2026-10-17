"""Tests for formalizator.core.home_migration and starter_catalog —
carrying a pre-rename working directory across, and shipping the
already-calibrated forms with the app."""

from __future__ import annotations

import json
from pathlib import Path

from formalizator.core import starter_catalog
from formalizator.core.home_migration import migrate_legacy_home


def _legacy_home(root: Path) -> Path:
    """A working directory as the app left it under its old name, with
    the absolute paths both catalogs really store."""
    legacy = root / "Celik"
    (legacy / "templates").mkdir(parents=True)
    (legacy / "export_sources").mkdir()

    pdf = legacy / "templates" / "NPRS-3.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    xlsx = legacy / "export_sources" / "NPRS-4.xlsx"
    xlsx.write_bytes(b"fake xlsx")
    (legacy / "celik.db").write_bytes(b"sqlite")

    (legacy / "templates" / "catalog.json").write_text(json.dumps([{
        "name": "НПРС-3", "background_pdf_path": str(pdf), "positions": [],
    }]), encoding="utf-8")
    (legacy / "export_templates.json").write_text(json.dumps([{
        "name": "НПРС-4", "source_file": str(xlsx), "columns": [],
    }]), encoding="utf-8")
    return legacy


def test_migration_moves_the_whole_working_directory(tmp_path: Path) -> None:
    legacy = _legacy_home(tmp_path)
    new_home = tmp_path / "Formalizator"

    assert migrate_legacy_home(new_home, legacy) is True

    assert not legacy.exists()
    assert (new_home / "templates" / "NPRS-3.pdf").exists()
    assert (new_home / "export_sources" / "NPRS-4.xlsx").exists()


def test_migration_repoints_the_calibrated_backgrounds(tmp_path: Path) -> None:
    """The catalog stores absolute paths, so a plain folder rename would
    leave every calibrated template pointing into a folder that no
    longer exists — losing hand-tuned work silently."""
    legacy = _legacy_home(tmp_path)
    new_home = tmp_path / "Formalizator"

    migrate_legacy_home(new_home, legacy)

    catalog = json.loads((new_home / "templates" / "catalog.json").read_text(encoding="utf-8"))
    background = Path(catalog[0]["background_pdf_path"])
    assert background.exists()
    assert str(legacy) not in str(background)


def test_migration_repoints_the_export_source_file(tmp_path: Path) -> None:
    legacy = _legacy_home(tmp_path)
    new_home = tmp_path / "Formalizator"

    migrate_legacy_home(new_home, legacy)

    exports = json.loads((new_home / "export_templates.json").read_text(encoding="utf-8"))
    source = Path(exports[0]["source_file"])
    assert source.exists()
    assert str(legacy) not in str(source)


def test_migration_renames_the_database(tmp_path: Path) -> None:
    legacy = _legacy_home(tmp_path)
    new_home = tmp_path / "Formalizator"

    migrate_legacy_home(new_home, legacy)

    assert (new_home / "formalizator.db").exists()
    assert not (new_home / "celik.db").exists()


def test_migration_leaves_an_existing_new_home_alone(tmp_path: Path) -> None:
    """Someone already using the renamed app keeps what they have — the
    old folder is never merged in blindly."""
    legacy = _legacy_home(tmp_path)
    new_home = tmp_path / "Formalizator"
    new_home.mkdir()
    (new_home / "formalizator.db").write_bytes(b"in use")

    assert migrate_legacy_home(new_home, legacy) is False

    assert legacy.exists()
    assert (new_home / "formalizator.db").read_bytes() == b"in use"


def test_migration_is_a_no_op_without_a_legacy_folder(tmp_path: Path) -> None:
    assert migrate_legacy_home(tmp_path / "Formalizator", tmp_path / "Celik") is False


def _fake_starter_root(tmp_path: Path, monkeypatch, *, name: str = "Тест образац") -> Path:
    """A synthetic `resources/starter/` — tests verify the seeding
    *mechanism* here rather than depending on whatever real forms
    happen to be bundled at any given moment (there may be none at
    all between election cycles, by design: see starter_catalog's own
    "blank slate until real forms are calibrated" handling)."""
    root = tmp_path / "fake_starter"
    root.mkdir()
    pdf = root / "form.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    xlsx = root / "export.xlsx"
    xlsx.write_bytes(b"fake xlsx")
    (root / "catalog.json").write_text(json.dumps([{
        "name": name, "background_pdf_path": "form.pdf",
        "positions": [{"field_key": "full_name", "page_index": 0, "x": 1.0, "y": 1.0}],
    }]), encoding="utf-8")
    (root / "export_templates.json").write_text(json.dumps([{
        "name": f"{name} — извоз", "source_file": "export.xlsx", "columns": [],
    }]), encoding="utf-8")
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: root)
    return root


def test_starter_forms_are_installed_into_a_fresh_home(tmp_path: Path, monkeypatch) -> None:
    """A fresh install ships with whatever forms are actually
    calibrated for this cycle rather than an empty catalog — when
    there are none bundled, seeding is correctly a no-op instead of a
    crash (see the "absent starter data" tests below)."""
    _fake_starter_root(tmp_path, monkeypatch)
    home = tmp_path / "home"
    catalog_dir = home / "templates"

    added = starter_catalog.seed(home, catalog_dir)

    assert added, "expected the bundled starter forms to be installed"
    catalog = json.loads((catalog_dir / "catalog.json").read_text(encoding="utf-8"))
    assert catalog, "no calibrated template seeded"
    background = Path(catalog[0]["background_pdf_path"])
    assert background.is_absolute() and background.exists()

    exports = json.loads((home / "export_templates.json").read_text(encoding="utf-8"))
    assert exports, "no export template seeded"
    source = Path(exports[0]["source_file"])
    assert source.is_absolute() and source.exists()


def test_seeded_template_loads_through_the_normal_catalog_api(tmp_path: Path, monkeypatch) -> None:
    from formalizator.core import template_catalog

    _fake_starter_root(tmp_path, monkeypatch)
    home = tmp_path / "home"
    catalog_dir = home / "templates"
    starter_catalog.seed(home, catalog_dir)

    templates = template_catalog.load_catalog(catalog_dir)

    assert templates
    assert templates[0].positions, "starter template arrived without its calibration"
    assert Path(templates[0].background_pdf_path).exists()


def test_seeding_twice_does_not_duplicate(tmp_path: Path, monkeypatch) -> None:
    _fake_starter_root(tmp_path, monkeypatch)
    home = tmp_path / "home"
    catalog_dir = home / "templates"

    first = starter_catalog.seed(home, catalog_dir)
    before = json.loads((catalog_dir / "catalog.json").read_text(encoding="utf-8"))

    second = starter_catalog.seed(home, catalog_dir)

    assert first
    assert second == []
    after = json.loads((catalog_dir / "catalog.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in after] == [t["name"] for t in before]


def test_seeding_never_overwrites_an_operators_own_edits(tmp_path: Path, monkeypatch) -> None:
    """An upgrade must not clobber a template the operator has since
    tuned — only genuinely new ones are added."""
    from formalizator.core import template_catalog

    _fake_starter_root(tmp_path, monkeypatch)
    home = tmp_path / "home"
    catalog_dir = home / "templates"
    starter_catalog.seed(home, catalog_dir)
    name = template_catalog.load_catalog(catalog_dir)[0].name

    edited = template_catalog.find_by_name(catalog_dir, name)
    edited.positions = []
    template_catalog.save_template(catalog_dir, edited)

    starter_catalog.seed(home, catalog_dir)

    assert template_catalog.find_by_name(catalog_dir, name).positions == []


def test_seeding_with_no_bundled_starter_data_is_a_harmless_no_op(tmp_path: Path, monkeypatch) -> None:
    """The actual state between election cycles: `resources/starter/`
    is intentionally blank-slated until the next cycle's official
    forms are calibrated. Seeding against that must not crash or
    write anything — just quietly do nothing."""
    empty_root = tmp_path / "empty_starter"
    empty_root.mkdir()
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: empty_root)
    home = tmp_path / "home"
    catalog_dir = home / "templates"

    added = starter_catalog.seed(home, catalog_dir)

    assert added == []
    assert not (catalog_dir / "catalog.json").exists()
    assert not (home / "export_templates.json").exists()


def test_seeding_with_missing_starter_directory_is_a_harmless_no_op(tmp_path: Path, monkeypatch) -> None:
    """Same as above but the directory doesn't exist at all — the
    state a fresh checkout of this repo is actually in."""
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: tmp_path / "does_not_exist")
    home = tmp_path / "home"

    added = starter_catalog.seed(home, home / "templates")

    assert added == []
