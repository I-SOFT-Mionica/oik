"""Tests for the quota table's Excel import/export wiring in
ElectionSettingsTab (buttons, quick-action, merge-by-declared-group
behavior) — the underlying read/write functions are covered by
test_template.py's test_quotas_workbook_* tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_tab(n_stations: int, party_abbrevs: list[str]):
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.polling_stations = [
        PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(n_stations)
    ]
    tab = ElectionSettingsTab(state)
    for abbrev in party_abbrevs:
        tab._append_party_row(abbrev, "", "", "")
    tab._refresh_parties_view()
    return tab


def test_export_then_import_round_trips_through_ui(tmp_path: Path, monkeypatch) -> None:
    tab = _make_tab(2, ["СНС", "СПС"])
    try:
        sb_pred, sb_zam, sb_clan = (
            tab.quotas_table.cellWidget(1, 1),
            tab.quotas_table.cellWidget(1, 2),
            tab.quotas_table.cellWidget(1, 3),
        )
        sb_pred.setValue(1)
        sb_zam.setValue(0)
        sb_clan.setValue(2)

        export_path = tmp_path / "quotas.xlsx"
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_election.QFileDialog.getSaveFileName",
            lambda *a, **kw: (str(export_path), ""),
        )
        tab._export_quotas_to_excel()
        assert export_path.exists()

        # Clear it in the UI, then re-import and confirm it comes back.
        sb_pred.setValue(0)
        sb_clan.setValue(0)
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_election.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(export_path), ""),
        )
        tab._import_quotas_from_excel()

        assert sb_pred.value() == 1
        assert sb_zam.value() == 0
        assert sb_clan.value() == 2
    finally:
        tab.deleteLater()


def test_import_skips_abbrev_not_in_declared_groups(tmp_path: Path, monkeypatch) -> None:
    from biracki_odbor.core.models import PartyQuota
    from biracki_odbor.core.template import build_quotas_workbook

    src = tmp_path / "quotas.xlsx"
    build_quotas_workbook(
        {"СНС": PartyQuota(predsednik=1), "ХЗС": PartyQuota(predsednik=3)}, src,
    )

    tab = _make_tab(3, ["СНС"])  # "ХЗС" is not a declared group
    try:
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_election.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(src), ""),
        )
        tab._import_quotas_from_excel()

        assert tab.quotas_table.cellWidget(1, 1).value() == 1
        assert "ХЗС" not in tab._quota_row_abbrevs
    finally:
        tab.deleteLater()


def test_export_with_no_declared_groups_shows_warning_not_crash(tmp_path: Path, monkeypatch) -> None:
    tab = _make_tab(1, [])
    try:
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.settings_election.QFileDialog.getSaveFileName",
            lambda *a, **kw: (str(tmp_path / "quotas.xlsx"), ""),
        )
        tab._export_quotas_to_excel()  # must not raise
        assert not (tmp_path / "quotas.xlsx").exists()
    finally:
        tab.deleteLater()


def test_quotas_section_has_import_quick_action() -> None:
    """Collapsed-state Import must be reachable without expanding the
    section, matching the Групе/Посматрачи quick-action convention.
    """
    tab = _make_tab(1, ["СНС"])
    try:
        assert tab._quotas_section._qa_row.count() >= 1
    finally:
        tab.deleteLater()


def test_template_section_has_import_quick_action() -> None:
    tab = _make_tab(1, ["СНС"])
    try:
        assert tab._template_section._qa_row.count() >= 1
    finally:
        tab.deleteLater()
