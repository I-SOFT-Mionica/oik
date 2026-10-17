"""Tests for MatrixGridWidget — embedded БМ × функција Raspodela grid,
including RIK seat-quota hard-limit enforcement.
"""

from __future__ import annotations

import pytest

from biracki_odbor.core.models import FUNCTIONS, Allocation, PartyQuota, PollingStation
from biracki_odbor.gui.widgets.matrix_grid_widget import _HEADER_LABELS, MatrixGridWidget


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _stations(n: int) -> list[PollingStation]:
    return [PollingStation(bm_number=i + 1, name=f"БM {i + 1}") for i in range(n)]


def test_columns_are_not_manually_resizable(app) -> None:
    """Fixed, not Interactive — a draggable БМ-matrix column could be
    stretched wide enough to push other columns out of the visible box.
    """
    from PySide6.QtWidgets import QHeaderView
    grid = MatrixGridWidget(_stations(1), ["СНС"], [])
    try:
        assert grid.table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    finally:
        grid.deleteLater()


def test_combo_wheel_event_does_not_change_selection(app) -> None:
    """A mouse-wheel scroll over a cell combo must never silently swap
    the assigned party — only an explicit dropdown pick should.
    """
    from PySide6.QtCore import QPoint, QPointF, Qt as QtCoreQt
    from PySide6.QtGui import QWheelEvent

    grid = MatrixGridWidget(_stations(1), ["СНС", "СПС"], [])
    try:
        combo = grid.table.cellWidget(0, 0)
        combo.setCurrentText("СНС")
        event = QWheelEvent(
            QPointF(0, 0), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
            QtCoreQt.MouseButton.NoButton, QtCoreQt.KeyboardModifier.NoModifier,
            QtCoreQt.ScrollPhase.NoScrollPhase, False,
        )
        combo.wheelEvent(event)
        assert combo.currentText() == "СНС"
        assert not event.isAccepted()
    finally:
        grid.deleteLater()


def test_grid_shape_matches_stations_and_functions(app) -> None:
    stations = _stations(4)
    grid = MatrixGridWidget(stations, ["СНС", "СПС"], [])
    try:
        assert grid.table.rowCount() == 4
        assert grid.table.columnCount() == len(FUNCTIONS)
        # QHeaderView can't do multi-line text, so headers show single-line
        # abbreviations (_HEADER_LABELS) rather than the exact FUNCTIONS
        # strings — those stay untouched for Excel round-tripping.
        headers = [grid.table.horizontalHeaderItem(c).text() for c in range(len(FUNCTIONS))]
        assert tuple(headers) == tuple(_HEADER_LABELS[f] for f in FUNCTIONS)
    finally:
        grid.deleteLater()


def test_dropdown_items_are_unassigned_plus_declared_parties_sorted(app) -> None:
    grid = MatrixGridWidget(_stations(1), ["ЗЛФ", "СНС"], [])
    try:
        combo = grid.table.cellWidget(0, 0)
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == ["—", "ЗЛФ", "СНС"]
    finally:
        grid.deleteLater()


def test_prefill_from_existing_allocations(app) -> None:
    stations = _stations(2)
    existing = [
        Allocation(bm_number=1, function="Председник", party="СНС"),
        Allocation(bm_number=2, function="Члан 1", party="СПС"),
    ]
    grid = MatrixGridWidget(stations, ["СНС", "СПС"], existing)
    try:
        combo_bm1_president = grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        assert combo_bm1_president.currentText() == "СНС"
        combo_bm2_clan1 = grid.table.cellWidget(1, FUNCTIONS.index("Члан 1"))
        assert combo_bm2_clan1.currentText() == "СПС"
        combo_bm1_clan1 = grid.table.cellWidget(0, FUNCTIONS.index("Члан 1"))
        assert combo_bm1_clan1.currentText() == "—"
    finally:
        grid.deleteLater()


def test_stale_value_not_in_declared_list_is_preserved_and_flagged(app) -> None:
    """Building the grid must never silently drop or overwrite a slot just
    because its party isn't (or is no longer) declared — it must show up
    in that cell's dropdown with a visual/tooltip warning.
    """
    stations = _stations(1)
    existing = [Allocation(bm_number=1, function="Председник", party="СТАРА")]
    grid = MatrixGridWidget(stations, ["СНС"], existing)
    try:
        combo = grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        assert combo.currentText() == "СТАРА"
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "СТАРА" in items
        assert combo.toolTip() != ""
    finally:
        grid.deleteLater()


def test_result_allocations_skips_unassigned_cells(app) -> None:
    stations = _stations(2)
    grid = MatrixGridWidget(stations, ["СНС", "СПС"], [])
    try:
        grid.table.cellWidget(0, FUNCTIONS.index("Председник")).setCurrentText("СНС")
        grid.table.cellWidget(1, FUNCTIONS.index("Члан 2")).setCurrentText("СПС")

        result = grid.result_allocations()

        assert len(result) == 2
        by_slot = {(a.bm_number, a.function): a.party for a in result}
        assert by_slot[(1, "Председник")] == "СНС"
        assert by_slot[(2, "Члан 2")] == "СПС"
    finally:
        grid.deleteLater()


# ── Quota hard-limit enforcement ────────────────────────────────────────

def _activate(combo, text: str) -> None:
    """Simulate a genuine user pick — `activated` fires, unlike setCurrentText."""
    idx = combo.findText(text)
    assert idx >= 0, f"{text!r} not in combo items"
    combo.setCurrentIndex(idx)
    combo.activated.emit(idx)


def test_quota_blocks_assignment_past_limit(app, monkeypatch) -> None:
    monkeypatch.setattr(
        "biracki_odbor.gui.widgets.matrix_grid_widget.QMessageBox.warning",
        lambda *a, **kw: None,
    )
    stations = _stations(2)
    quotas = {"СНС": PartyQuota(predsednik=1)}
    grid = MatrixGridWidget(stations, ["СНС"], [], quotas)
    try:
        combo_bm1 = grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        combo_bm2 = grid.table.cellWidget(1, FUNCTIONS.index("Председник"))

        _activate(combo_bm1, "СНС")
        assert combo_bm1.currentText() == "СНС"

        _activate(combo_bm2, "СНС")
        # Quota (1) already used by BM1 -> BM2 assignment must be reverted.
        assert combo_bm2.currentText() == "—"
    finally:
        grid.deleteLater()


def test_quota_allows_assignment_within_limit(app) -> None:
    stations = _stations(2)
    quotas = {"СНС": PartyQuota(predsednik=2)}
    grid = MatrixGridWidget(stations, ["СНС"], [], quotas)
    try:
        combo_bm1 = grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        combo_bm2 = grid.table.cellWidget(1, FUNCTIONS.index("Председник"))

        _activate(combo_bm1, "СНС")
        _activate(combo_bm2, "СНС")

        assert combo_bm1.currentText() == "СНС"
        assert combo_bm2.currentText() == "СНС"
    finally:
        grid.deleteLater()


def test_missing_quota_entry_does_not_block(app) -> None:
    """A party with no quota row entered yet is unlimited, not blocked."""
    stations = _stations(3)
    grid = MatrixGridWidget(stations, ["СНС"], [], {})
    try:
        combos = [grid.table.cellWidget(i, FUNCTIONS.index("Председник")) for i in range(3)]
        for c in combos:
            _activate(c, "СНС")
        assert all(c.currentText() == "СНС" for c in combos)
    finally:
        grid.deleteLater()


def test_quota_bucket_shared_across_member_functions(app, monkeypatch) -> None:
    """Члан 1/Заменик члана 1/Члан 2/Заменик члана 2 share one combined
    quota bucket (clan_i_zamenik) — matches RIK's own table shape.
    """
    monkeypatch.setattr(
        "biracki_odbor.gui.widgets.matrix_grid_widget.QMessageBox.warning",
        lambda *a, **kw: None,
    )
    stations = _stations(1)
    quotas = {"СНС": PartyQuota(clan_i_zamenik=2)}
    grid = MatrixGridWidget(stations, ["СНС"], [], quotas)
    try:
        c1 = grid.table.cellWidget(0, FUNCTIONS.index("Члан 1"))
        c2 = grid.table.cellWidget(0, FUNCTIONS.index("Заменик члана 1"))
        c3 = grid.table.cellWidget(0, FUNCTIONS.index("Члан 2"))

        _activate(c1, "СНС")
        _activate(c2, "СНС")
        _activate(c3, "СНС")  # third assignment exceeds combined quota of 2

        assert c1.currentText() == "СНС"
        assert c2.currentText() == "СНС"
        assert c3.currentText() == "—"
    finally:
        grid.deleteLater()
