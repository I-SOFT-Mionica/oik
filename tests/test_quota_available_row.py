"""Tests for the quotas table's row-0 "Available" summary + live spinbox
capping — available can never go negative; once a bucket hits 0, the
remaining group spinboxes in that column refuse to go any higher.
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


def _row_spinboxes(tab, row: int):
    return (
        tab.quotas_table.cellWidget(row, 1),
        tab.quotas_table.cellWidget(row, 2),
        tab.quotas_table.cellWidget(row, 3),
    )


def test_quotas_table_columns_are_not_manually_resizable() -> None:
    """Fixed, not Interactive — an operator dragging "Група" wide could
    push Председник/Заменик/etc. out of the visible box behind a
    horizontal scrollbar.
    """
    from PySide6.QtWidgets import QHeaderView
    tab = _make_tab(1, ["СНС"])
    try:
        h = tab.quotas_table.horizontalHeader()
        for col in range(5):
            assert h.sectionResizeMode(col) == QHeaderView.Fixed
    finally:
        tab.deleteLater()


def test_available_row_matches_expected_totals_before_any_input() -> None:
    tab = _make_tab(2, ["СНС"])
    try:
        assert [tab.quotas_table.item(0, c).text() for c in range(5)] == [
            "Available", "2", "2", "8", "12",
        ]
    finally:
        tab.deleteLater()


def test_available_row_decreases_as_quotas_entered() -> None:
    tab = _make_tab(2, ["СНС", "СПС"])
    try:
        sb_pred, _sb_zam, _sb_clan = _row_spinboxes(tab, 1)  # СНС's row
        sb_pred.setValue(1)
        assert tab.quotas_table.item(0, 1).text() == "1"  # Председник available: 2-1
    finally:
        tab.deleteLater()


def test_available_total_column_is_sum_of_bucket_availables() -> None:
    tab = _make_tab(1, ["СНС"])
    try:
        sb_pred, sb_zam, sb_clan = _row_spinboxes(tab, 1)
        sb_pred.setValue(1)
        sb_zam.setValue(1)
        sb_clan.setValue(2)
        # expected: predsednik=1, zamenik=1, clan=4 -> available 0,0,2 -> total 2
        assert tab.quotas_table.item(0, 4).text() == "2"
    finally:
        tab.deleteLater()


def test_spinbox_cannot_exceed_available_across_groups() -> None:
    """1 BM -> 1 Председник seat total. Once СНС takes it, ССП's
    Председник spinbox must refuse to go above 0 (can't go negative).
    """
    tab = _make_tab(1, ["СНС", "ССП"])
    try:
        sns_pred, _, _ = _row_spinboxes(tab, 1)
        ssp_pred, _, _ = _row_spinboxes(tab, 2)

        sns_pred.setValue(1)
        assert ssp_pred.maximum() == 0

        ssp_pred.setValue(5)  # attempt to exceed max — QSpinBox clamps
        assert ssp_pred.value() == 0
    finally:
        tab.deleteLater()


def test_spinbox_max_recovers_when_sibling_reduced() -> None:
    tab = _make_tab(1, ["СНС", "ССП"])
    try:
        sns_pred, _, _ = _row_spinboxes(tab, 1)
        ssp_pred, _, _ = _row_spinboxes(tab, 2)

        sns_pred.setValue(1)
        assert ssp_pred.maximum() == 0

        sns_pred.setValue(0)
        assert ssp_pred.maximum() == 1
        ssp_pred.setValue(1)
        assert ssp_pred.value() == 1
    finally:
        tab.deleteLater()


def test_collect_quotas_uses_correct_row_offset() -> None:
    """Row 0 is the Available summary — party rows start at row 1. A
    regression here would silently save the wrong group's numbers.
    """
    tab = _make_tab(5, ["СНС", "СПС"])
    try:
        sns_pred, sns_zam, sns_clan = _row_spinboxes(tab, 1)
        sps_pred, sps_zam, sps_clan = _row_spinboxes(tab, 2)
        sns_pred.setValue(2)
        sps_pred.setValue(1)

        quotas = tab._collect_quotas()

        assert quotas["СНС"].predsednik == 2
        assert quotas["СПС"].predsednik == 1
    finally:
        tab.deleteLater()


def test_quotas_table_values_painted_without_marking_dirty() -> None:
    """A spinbox that gets its value while still unparented (setValue()
    before setCellWidget()) doesn't reliably repaint once it lands in the
    table -- the value is genuinely there, it just isn't painted until
    something forces a repaint (confirmed: clicking into a "blank" box
    reveals the number). Fixed by setting values AFTER setCellWidget();
    signals are blocked for that initial set so it doesn't look like an
    operator edit -- only _import_quotas_from_excel() firing _mark_dirty
    is correct, not a plain table rebuild reflecting already-saved data."""
    from biracki_odbor.core.models import PartyQuota

    tab = _make_tab(5, ["СНС"])
    try:
        tab.state.election.party_quotas = {
            "СНС": PartyQuota(predsednik=1, zamenik=1, clan_i_zamenik=15),
        }
        tab.dirty = False
        tab._refresh_quotas_table()

        sb_pred, sb_zam, sb_clan = _row_spinboxes(tab, 1)
        assert sb_pred.value() == 1
        assert sb_zam.value() == 1
        assert sb_clan.value() == 15
        assert tab.dirty is False
    finally:
        tab.deleteLater()
