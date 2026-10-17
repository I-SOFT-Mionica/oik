"""Tests for biracki_odbor.core.maintenance — one-off operator actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.core import maintenance


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    yield


def test_get_unknown_key_returns_none() -> None:
    assert maintenance.get("") is None
    assert maintenance.get("not_a_real_action") is None


def test_get_known_action() -> None:
    action = maintenance.get("cleanup_legacy_migration_files")
    assert action is not None
    assert action.key == "cleanup_legacy_migration_files"
    assert action.label_sr
    assert action.description_sr


def test_cleanup_legacy_migration_files_removes_migrated_and_sidecar(tmp_path: Path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import STALNI_SPEC

    legacy = app_paths.legacy_xlsx_master_path_for(STALNI_SPEC)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    migrated = legacy.with_name(legacy.name + ".migrated")
    migrated.write_bytes(b"old xlsx bytes")
    verified_dir = legacy.parent / ".verified"
    verified_dir.mkdir(parents=True, exist_ok=True)
    sidecar = verified_dir / f"{legacy.name}.json"
    snapshot = verified_dir / legacy.name
    sidecar.write_text("{}", encoding="utf-8")
    snapshot.write_bytes(b"old snapshot")

    action = maintenance.get("cleanup_legacy_migration_files")
    result = action.run()

    assert not migrated.exists()
    assert not sidecar.exists()
    assert not snapshot.exists()
    assert migrated.name in result


def test_cleanup_legacy_migration_files_is_a_noop_when_nothing_to_clean() -> None:
    action = maintenance.get("cleanup_legacy_migration_files")
    result = action.run()  # must not raise even with nothing present
    assert isinstance(result, str)
    assert result
