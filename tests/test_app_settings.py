"""Tests for biracki_odbor.config.settings (app-wide preferences)."""

from __future__ import annotations

from pathlib import Path

from biracki_odbor.config import settings as settings_mod


def test_load_missing_returns_defaults(tmp_path: Path) -> None:
    s = settings_mod.load(tmp_path / "nope.json")
    assert s.debug_logging is False


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "app_settings.json"
    s = settings_mod.AppSettings(debug_logging=True)
    settings_mod.save(s, p)
    assert p.exists()
    loaded = settings_mod.load(p)
    assert loaded.debug_logging is True


def test_load_corrupt_returns_defaults(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = settings_mod.load(p)
    assert s.debug_logging is False


def test_oik_template_path_round_trip(tmp_path: Path) -> None:
    """OikConstants now persists template_path."""
    from biracki_odbor.config import oik as oik_mod

    p = tmp_path / "oik.json"
    c = oik_mod.OikConstants()
    c.template_path = r"C:\Users\test\Biracki_Odbor\sablon\Stalni_sastav.xlsx"
    oik_mod.save(c, p)
    loaded = oik_mod.load(p)
    assert loaded.template_path == c.template_path


def test_default_files_dir_defaults_empty() -> None:
    assert settings_mod.AppSettings().default_files_dir == ""


def test_default_files_dir_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "app_settings.json"
    s = settings_mod.AppSettings(default_files_dir=r"D:\OIK Files")
    settings_mod.save(s, p)
    loaded = settings_mod.load(p)
    assert loaded.default_files_dir == r"D:\OIK Files"


def test_last_run_version_defaults_empty_and_round_trips(tmp_path: Path) -> None:
    assert settings_mod.AppSettings().last_run_version == ""
    p = tmp_path / "app_settings.json"
    settings_mod.save(settings_mod.AppSettings(last_run_version="0.77.3"), p)
    assert settings_mod.load(p).last_run_version == "0.77.3"


def test_pending_maintenance_action_defaults_empty_and_round_trips(tmp_path: Path) -> None:
    assert settings_mod.AppSettings().pending_maintenance_action == ""
    p = tmp_path / "app_settings.json"
    settings_mod.save(
        settings_mod.AppSettings(pending_maintenance_action="cleanup_legacy_migration_files"), p,
    )
    loaded = settings_mod.load(p)
    assert loaded.pending_maintenance_action == "cleanup_legacy_migration_files"
