"""Regression tests: importing a candidacies Excel file when lists/
candidates already exist must offer Add-new/Replace-all, not silently
replace everything (the realistic workflow is one file per individual
list, each with its own list-info + candidates, imported one at a time).

Field report (2026-07-30): _import_kandidati_from_excel had no merge
option -- Replace-or-Cancel only -- so importing list B's file after
list A's meant only the last import survived.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "", raising=False)


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    from tests.test_phase1 import _make_oik
    from tests.test_phase3 import _make_election

    state = AppState()
    state._oik = _make_oik(2)  # noqa: SLF001
    state._election = _make_election()  # noqa: SLF001
    return state


def _click_button_named(monkeypatch, text: str) -> None:
    """Make every QMessageBox.exec() in this test act as if `text`'s
    button was clicked, without actually blocking on a real dialog."""
    from PySide6.QtWidgets import QMessageBox

    def _exec(self):
        for b in self.buttons():
            if b.text().replace("&", "") == text:
                self._test_clicked = b
                return 0
        self._test_clicked = None
        return 0

    monkeypatch.setattr(QMessageBox, "exec", _exec)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda self: getattr(self, "_test_clicked", None),
    )


def _write_candidacies_xlsx(path: Path, entity_id: str, entity_name: str, cand_name: str, jmbg: str) -> None:
    from biracki_odbor.config.candidacies import CandidaciesRegistry, Candidate, Entity
    from biracki_odbor.core.template import build_candidacies_workbook

    reg = CandidaciesRegistry(
        entities=[Entity(entity_id, entity_name, "party", "local", 1, "")],
        candidates=[Candidate(cand_name, jmbg, entity_id)],
    )
    build_candidacies_workbook(reg, path)


def test_second_import_with_add_new_keeps_first_list(app, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    tab = ElectionSettingsTab(state)
    try:
        file_a = tmp_path / "a.xlsx"
        file_b = tmp_path / "b.xlsx"
        _write_candidacies_xlsx(file_a, "a-loc", "Листа А", "Ана Анић", "1234567890123")
        _write_candidacies_xlsx(file_b, "b-loc", "Листа Б", "Бора Борић", "9876543210123")

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_a), ""),
        )
        tab._import_kandidati_from_excel()  # noqa: SLF001
        assert len(tab._entity_rows) == 1  # noqa: SLF001
        assert len(tab._candidate_rows) == 1  # noqa: SLF001

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_b), ""),
        )
        _click_button_named(monkeypatch, "Add new")
        tab._import_kandidati_from_excel()  # noqa: SLF001

        entity_ids = {r["entity_id"] for r in tab._entity_rows}  # noqa: SLF001
        jmbgs = {r["jmbg"] for r in tab._candidate_rows}  # noqa: SLF001
        assert entity_ids == {"a-loc", "b-loc"}, "list A must survive importing list B's file"
        assert jmbgs == {"1234567890123", "9876543210123"}
    finally:
        tab.deleteLater()


def test_second_import_with_replace_all_drops_first_list(app, tmp_path, monkeypatch) -> None:
    """Replace All is still available and still does replace -- it's an
    explicit, clearly-labeled choice, not a silent default."""
    from PySide6.QtWidgets import QFileDialog
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    tab = ElectionSettingsTab(state)
    try:
        file_a = tmp_path / "a.xlsx"
        file_b = tmp_path / "b.xlsx"
        _write_candidacies_xlsx(file_a, "a-loc", "Листа А", "Ана Анић", "1234567890123")
        _write_candidacies_xlsx(file_b, "b-loc", "Листа Б", "Бора Борић", "9876543210123")

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_a), ""),
        )
        tab._import_kandidati_from_excel()  # noqa: SLF001

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_b), ""),
        )
        _click_button_named(monkeypatch, "Replace all")
        tab._import_kandidati_from_excel()  # noqa: SLF001

        entity_ids = {r["entity_id"] for r in tab._entity_rows}  # noqa: SLF001
        assert entity_ids == {"b-loc"}
    finally:
        tab.deleteLater()


def test_add_new_skips_duplicate_jmbg(app, tmp_path, monkeypatch) -> None:
    """Re-importing the same candidate (e.g. re-downloading the same
    file) must not create a duplicate row."""
    from PySide6.QtWidgets import QFileDialog
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    tab = ElectionSettingsTab(state)
    try:
        file_a = tmp_path / "a.xlsx"
        _write_candidacies_xlsx(file_a, "a-loc", "Листа А", "Ана Анић", "1234567890123")

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", lambda *a, **k: (str(file_a), ""),
        )
        tab._import_kandidati_from_excel()  # noqa: SLF001

        _click_button_named(monkeypatch, "Add new")
        tab._import_kandidati_from_excel()  # noqa: SLF001

        assert len(tab._entity_rows) == 1  # noqa: SLF001
        assert len(tab._candidate_rows) == 1  # noqa: SLF001
    finally:
        tab.deleteLater()
