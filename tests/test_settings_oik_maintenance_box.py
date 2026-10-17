"""Maintenance box in OikSettingsTab → Систем: hidden unless a one-off
action is pending (core/maintenance.py); disappears again once run."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_tab():
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    tab = OikSettingsTab(state)
    return tab


def test_maintenance_box_hidden_by_default() -> None:
    tab = _make_tab()
    try:
        assert tab.state.app_settings.pending_maintenance_action == ""
        assert tab.maintenance_box.isHidden()
    finally:
        tab.deleteLater()


def test_maintenance_box_visible_when_action_pending() -> None:
    tab = _make_tab()
    try:
        tab.state.app_settings.pending_maintenance_action = "cleanup_legacy_migration_files"
        tab._load_from_state()  # noqa: SLF001 — simulate a reload after the flag was set
        assert not tab.maintenance_box.isHidden()
        assert tab.btn_run_maintenance.text()
        assert tab.lbl_maintenance_desc.text()
    finally:
        tab.deleteLater()


def test_unknown_pending_action_key_stays_hidden() -> None:
    """Defensive: a stale/unrecognized key (e.g. from a downgrade) must
    not crash the tab or show an empty button."""
    tab = _make_tab()
    try:
        tab.state.app_settings.pending_maintenance_action = "some_future_action_not_yet_registered"
        tab._load_from_state()  # noqa: SLF001
        assert tab.maintenance_box.isHidden()
    finally:
        tab.deleteLater()


def test_running_action_clears_flag_and_hides_box(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)

    tab = _make_tab()
    try:
        tab.state.app_settings.pending_maintenance_action = "cleanup_legacy_migration_files"
        tab._load_from_state()  # noqa: SLF001
        assert not tab.maintenance_box.isHidden()

        tab._on_run_maintenance_action()  # noqa: SLF001

        assert tab.state.app_settings.pending_maintenance_action == ""
        assert tab.maintenance_box.isHidden()

        # Persisted, not just in-memory — stays hidden across a fresh load.
        from biracki_odbor.config import settings as settings_mod
        from biracki_odbor import app_paths
        reloaded = settings_mod.load(app_paths.app_settings_path())
        assert reloaded.pending_maintenance_action == ""
    finally:
        tab.deleteLater()
