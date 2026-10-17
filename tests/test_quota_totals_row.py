"""Tests for ElectionSettingsTab's read-only municipality quota-totals row.

President/Deputy = 1 per polling station, Members+deputies = 4 per
station (Члан 1/Заменик члана 1/Члан 2/Заменик члана 2), Total = sum.
Purely derived from the BM count — not from the parties' quota entries
below it, which the operator should be able to cross-check against it.
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


def _make_tab(n_stations: int, municipality_name: str = "Мионица"):
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.municipality.name = municipality_name
    state.oik.polling_stations = [
        PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(n_stations)
    ]
    return ElectionSettingsTab(state)


def test_totals_row_computed_from_bm_count() -> None:
    tab = _make_tab(10, "Мионица")
    try:
        row = [tab.quotas_totals_table.item(0, c).text() for c in range(5)]
        assert row == ["Мионица", "10", "10", "40", "60"]
    finally:
        tab.deleteLater()


def test_totals_row_zero_stations() -> None:
    tab = _make_tab(0)
    try:
        row = [tab.quotas_totals_table.item(0, c).text() for c in range(1, 5)]
        assert row == ["0", "0", "0", "0"]
    finally:
        tab.deleteLater()


def test_totals_row_refreshes_on_oik_changed() -> None:
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab(2)
    try:
        assert tab.quotas_totals_table.item(0, 4).text() == "12"
        tab.state.oik.polling_stations.append(PollingStation(bm_number=3, name="БM 3"))
        tab.state.oik_changed.emit()
        assert tab.quotas_totals_table.item(0, 4).text() == "18"
    finally:
        tab.deleteLater()
