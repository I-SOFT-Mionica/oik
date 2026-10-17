"""Tests for the "move existing exported files" prompt that fires when
the operator changes the default export folder (Поставке ОИК → System)
mid-cycle — files already exported under the old location shouldn't be
silently left behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_tab():
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    return OikSettingsTab(state)


def test_move_prompt_offered_and_moves_subfolders(app, tmp_path, monkeypatch) -> None:
    old_base = tmp_path / "old_export"
    new_base = tmp_path / "new_export"
    (old_base / "Странке").mkdir(parents=True)
    (old_base / "Странке" / "СНС.xlsx").write_text("x")
    (old_base / "Решења").mkdir(parents=True)
    (old_base / "Решења" / "БМ_01.docx").write_text("y")

    tab = _make_tab()
    try:
        tab.state.app_settings.default_files_dir = str(old_base)

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(new_base),
        )
        from PySide6.QtWidgets import QMessageBox
        asked = []

        def _question(*a, **kw):
            asked.append(True)
            return QMessageBox.Yes

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.question", _question,
        )

        tab._on_browse_files_dir()  # noqa: SLF001

        assert asked, "operator should be prompted to move existing files"
        assert tab.state.app_settings.default_files_dir == str(new_base)
        assert (new_base / "Странке" / "СНС.xlsx").read_text() == "x"
        assert (new_base / "Решења" / "БМ_01.docx").read_text() == "y"
        assert not (old_base / "Странке").exists()
        assert not (old_base / "Решења").exists()
    finally:
        tab.deleteLater()


def test_move_declined_leaves_old_files_in_place(app, tmp_path, monkeypatch) -> None:
    old_base = tmp_path / "old_export"
    new_base = tmp_path / "new_export"
    (old_base / "Странке").mkdir(parents=True)
    (old_base / "Странке" / "СНС.xlsx").write_text("x")

    tab = _make_tab()
    try:
        tab.state.app_settings.default_files_dir = str(old_base)

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(new_base),
        )
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.question",
            lambda *a, **kw: QMessageBox.No,
        )

        tab._on_browse_files_dir()  # noqa: SLF001

        assert (old_base / "Странке" / "СНС.xlsx").exists(), "declining must not move anything"
        assert not (new_base / "Странке").exists()
    finally:
        tab.deleteLater()


def test_no_prompt_when_old_location_empty(app, tmp_path, monkeypatch) -> None:
    old_base = tmp_path / "old_export"
    old_base.mkdir()
    new_base = tmp_path / "new_export"

    tab = _make_tab()
    try:
        tab.state.app_settings.default_files_dir = str(old_base)

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(new_base),
        )
        asked = []
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.question",
            lambda *a, **kw: asked.append(True),
        )

        tab._on_browse_files_dir()  # noqa: SLF001

        assert not asked, "nothing to move — must not prompt"
    finally:
        tab.deleteLater()


def test_no_prompt_when_default_files_dir_was_unset(app, tmp_path, monkeypatch) -> None:
    """First-time configuration (old value empty) — nothing to offer."""
    new_base = tmp_path / "new_export"

    tab = _make_tab()
    try:
        assert tab.state.app_settings.default_files_dir == ""

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(new_base),
        )
        asked = []
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.question",
            lambda *a, **kw: asked.append(True),
        )

        tab._on_browse_files_dir()  # noqa: SLF001

        assert not asked
        assert tab.state.app_settings.default_files_dir == str(new_base)
    finally:
        tab.deleteLater()


def test_move_survives_per_folder_failure(app, tmp_path, monkeypatch) -> None:
    old_base = tmp_path / "old_export"
    new_base = tmp_path / "new_export"
    (old_base / "Странке").mkdir(parents=True)
    (old_base / "Странке" / "СНС.xlsx").write_text("x")
    (old_base / "Решења").mkdir(parents=True)
    (old_base / "Решења" / "БМ_01.docx").write_text("y")

    tab = _make_tab()
    try:
        tab.state.app_settings.default_files_dir = str(old_base)

        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QFileDialog.getExistingDirectory",
            lambda *a, **kw: str(new_base),
        )
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.question",
            lambda *a, **kw: QMessageBox.Yes,
        )
        warned = []
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_oik.QMessageBox.warning",
            lambda *a, **kw: warned.append(True),
        )

        import shutil as _shutil
        real_move = _shutil.move

        def _flaky_move(src, dst):
            if "Решења" in str(src):
                raise OSError("locked")
            return real_move(src, dst)

        monkeypatch.setattr("biracki_odbor.gui.tabs.settings_oik.shutil.move", _flaky_move)

        tab._on_browse_files_dir()  # noqa: SLF001

        assert (new_base / "Странке" / "СНС.xlsx").exists(), "the folder that succeeded must still move"
        assert (old_base / "Решења" / "БМ_01.docx").exists(), "the failed folder stays put, not lost"
        assert warned, "operator must be told a folder failed to move"
    finally:
        tab.deleteLater()
