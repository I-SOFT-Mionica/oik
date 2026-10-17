"""Tests for biracki_odbor.installer.uninstall.

Use a tmp_path as a fake install dir so we never touch the real
%USERPROFILE%\\Biracki_Odbor on the maintainer's machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.installer import scaffold, uninstall


def _stage_install(base: Path, *, with_program: bool = True, with_data: bool = True) -> None:
    """Build a believable install layout under `base`.

    Avoids running `perform_scaffold` (which needs templates) so the test
    is fast and hermetic. Mirrors the layer 2 / layer 3 file shape that
    `uninstall._PROGRAM_FILES` / `_USER_DATA_FILES` expect.
    """
    base.mkdir(parents=True, exist_ok=True)
    if with_program:
        (base / "OIK.exe").write_bytes(b"MZ\x00")
        (base / "icon.ico").write_bytes(b"\x00\x00\x01\x00")
        (base / "desktop.ini").write_text("[.ShellClassInfo]\n", encoding="utf-8")
        (base / "УПУТСТВО.txt").write_text("Упутство", encoding="utf-8")
    if with_data:
        for name in uninstall._USER_DATA_FILES:
            (base / name).write_text("{}", encoding="utf-8")
        for sub in uninstall._USER_DATA_DIRS:
            d = base / sub
            d.mkdir(exist_ok=True)
            (d / "marker.txt").write_text("x", encoding="utf-8")


# ── Detection ──────────────────────────────────────────────


def test_describe_install_empty_dir(tmp_path: Path) -> None:
    info = uninstall.describe_install(tmp_path)
    assert info["exists"] is True
    assert info["program_files"] == []
    assert info["user_data_files"] == []
    assert info["user_data_dirs"] == []


def test_describe_install_missing_dir(tmp_path: Path) -> None:
    info = uninstall.describe_install(tmp_path / "nope")
    assert info["exists"] is False


def test_describe_install_full(tmp_path: Path) -> None:
    _stage_install(tmp_path)
    info = uninstall.describe_install(tmp_path)
    assert "OIK.exe" in info["program_files"]
    assert "icon.ico" in info["program_files"]
    assert "oik_constants.json" in info["user_data_files"]
    names = {d["name"] for d in info["user_data_dirs"]}
    assert {"sablon", "master", "resenja"} <= names


# ── Layer 2: program files ─────────────────────────────────


def test_remove_program_files_clears_only_program_set(tmp_path: Path) -> None:
    _stage_install(tmp_path)
    result = uninstall.remove_program_files(tmp_path)
    # Every program-side file gone.
    for name in ("OIK.exe", "icon.ico", "desktop.ini", "УПУТСТВО.txt"):
        assert not (tmp_path / name).exists(), f"{name} should be gone"
    # User data untouched.
    assert (tmp_path / "oik_constants.json").exists()
    assert (tmp_path / "master").exists()
    assert len(result.removed_files) == 4
    assert result.errors == []


def test_remove_program_files_idempotent(tmp_path: Path) -> None:
    _stage_install(tmp_path, with_data=False)
    uninstall.remove_program_files(tmp_path)
    # Second call shouldn't raise — missing files are silently skipped.
    second = uninstall.remove_program_files(tmp_path)
    assert second.removed_files == []
    assert second.errors == []


def test_remove_program_files_missing_dir(tmp_path: Path) -> None:
    result = uninstall.remove_program_files(tmp_path / "nope")
    assert result.skipped, "should record skip reason"
    assert result.removed_files == []


# ── Layer 3: user data ─────────────────────────────────────


def test_remove_user_data_clears_configs_and_subdirs(tmp_path: Path) -> None:
    _stage_install(tmp_path)
    uninstall.remove_user_data(tmp_path)
    # All configs gone.
    for name in ("oik_constants.json", "election_config.json", "app_settings.json",
                 "places_genitive.json", "corrections.log"):
        assert not (tmp_path / name).exists(), f"{name} should be gone"
    # All subdirs gone (rmtree, not just contents).
    for sub in ("sablon", "stranka_fajlovi", "popunjeni", "master", "resenja"):
        assert not (tmp_path / sub).exists(), f"{sub}/ should be gone"
    # Program files untouched.
    assert (tmp_path / "OIK.exe").exists()


def test_remove_user_data_clears_every_known_file_and_dir(tmp_path: Path) -> None:
    """Regression for the 2026-07-10 full-wipe bug: license.dat,
    posmatraci.json, generation_log.json, every прошириpени/observer
    subdir, etc. were left behind because _USER_DATA_FILES/_DIRS predated
    those features. Stage + assert every currently-known entry so a
    future feature that forgets to register itself here fails loudly.
    """
    _stage_install(tmp_path)
    uninstall.remove_user_data(tmp_path)
    for name in uninstall._USER_DATA_FILES:
        assert not (tmp_path / name).exists(), f"{name} should be gone"
    for sub in uninstall._USER_DATA_DIRS:
        assert not (tmp_path / sub).exists(), f"{sub}/ should be gone"


def test_remove_user_data_is_destructive_to_master(tmp_path: Path) -> None:
    """Sanity: master/zbirana_tabela.xlsx is gone after layer 3."""
    _stage_install(tmp_path)
    (tmp_path / "master" / "zbirana_tabela.xlsx").write_bytes(b"PK\x03\x04")
    uninstall.remove_user_data(tmp_path)
    assert not (tmp_path / "master").exists()


# ── Orchestration ──────────────────────────────────────────


def test_execute_full_uninstall_removes_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "Biracki_Odbor"
    _stage_install(base)
    plan = uninstall.UninstallPlan(
        remove_shortcut=False,  # tests can't rely on a real Desktop
        remove_program_files=True,
        remove_user_data=True,
    )
    result = uninstall.execute(base, plan)
    # Base dir itself removed because nothing's left.
    assert not base.exists()
    # The base path landed in removed_dirs as the final sweep.
    assert base in result.removed_dirs


def test_execute_leaves_user_data_when_only_program_chosen(tmp_path: Path) -> None:
    base = tmp_path / "Biracki_Odbor"
    _stage_install(base)
    plan = uninstall.UninstallPlan(
        remove_shortcut=False,
        remove_program_files=True,
        remove_user_data=False,
    )
    uninstall.execute(base, plan)
    assert not (base / "OIK.exe").exists()
    assert (base / "oik_constants.json").exists()
    assert (base / "master").exists()
    # Base dir stays because data is still there.
    assert base.exists()


def test_execute_leaves_program_when_only_data_chosen(tmp_path: Path) -> None:
    """The 'wipe and reinstall later' flow."""
    base = tmp_path / "Biracki_Odbor"
    _stage_install(base)
    plan = uninstall.UninstallPlan(
        remove_shortcut=False,
        remove_program_files=False,
        remove_user_data=True,
    )
    uninstall.execute(base, plan)
    assert (base / "OIK.exe").exists()
    assert not (base / "oik_constants.json").exists()
    assert not (base / "master").exists()
    assert base.exists()  # still has program files


def test_execute_skips_base_sweep_if_only_one_layer(tmp_path: Path) -> None:
    """remove_base_dir_if_empty only runs when both layer 2+3 ran."""
    base = tmp_path / "Biracki_Odbor"
    base.mkdir()
    # Only program files staged; user data layer would find nothing.
    _stage_install(base, with_data=False)
    plan = uninstall.UninstallPlan(
        remove_shortcut=False,
        remove_program_files=True,
        remove_user_data=False,
    )
    uninstall.execute(base, plan)
    # Even though the dir is now empty, we didn't sweep because user data
    # wasn't selected — protects against half-clean ambiguity.
    assert base.exists()


# ── find_install_dir ───────────────────────────────────────


def test_find_install_dir_honors_env_override(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "custom"
    target.mkdir()
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(target))
    assert uninstall.find_install_dir() == target


def test_find_install_dir_returns_none_when_nothing_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BIRACKI_ODBOR_HOME", raising=False)
    # Point USERPROFILE at an empty tmpdir so the default doesn't accidentally hit
    # the maintainer's real install.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert uninstall.find_install_dir() is None
