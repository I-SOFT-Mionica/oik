"""Regression: clicking the main "Save settings" action must also persist
the embedded matrix grid's current edits.

Found 2026-07-12: the grid had its own separate "Сачувај матрицу" save
action; the main Save button only persisted ElectionConfig (dates,
parties, quotas, candidacies...), never the grid. An operator who filled
in the grid and only clicked the main Save button silently lost those
assignments — the on-disk Raspodela sheet stayed blank. Fixed by having
`_save()` call `_save_matrix()` too, so there's one save action for the
whole page.
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


def test_save_settings_persists_matrix_grid_assignment(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from biracki_odbor import app_paths
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.core.models import FUNCTIONS, PollingStation
    from biracki_odbor.core.template import read_template
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.municipality.name = "Мионица"
    state.oik.polling_stations = [PollingStation(bm_number=1, name="Школа А")]
    # The matrix grid's dropdown reads declared parties from
    # state.election.party_full_names directly (not the tab's in-memory
    # _parties_rows, which only reaches state.election on Save) — seed
    # it here so the grid is built with a real party option available.
    # Must be a fully _save()-valid config too, or _save() bails out at
    # validate() before ever reaching the matrix-save step under test.
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "Српска напредна странка"},
    )
    tab = ElectionSettingsTab(state)
    try:
        tab._load_from_state()

        assert tab._matrix_grid is not None
        combo = tab._matrix_grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        idx = combo.findText("СНС")
        combo.setCurrentIndex(idx)
        combo.activated.emit(idx)

        tab._save()

        canonical = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
        assert canonical.exists()
        data, report = read_template(canonical)
        assert report.ok, [i.message_sr for i in report.issues]
        assert any(
            a.bm_number == 1 and a.function == "Председник" and a.party == "СНС"
            for a in data.allocations
        ), "Save settings must persist the grid's current assignment, not just ElectionConfig fields."
    finally:
        tab.deleteLater()


def test_save_settings_does_not_warn_about_partially_filled_matrix(tmp_path: Path, monkeypatch) -> None:
    """Regression: `_save_matrix()` used to route through the same
    `_on_template_chosen()` path as importing an external file, which
    includes a "BM mismatch" warning meant to catch a genuinely stale
    import. `result_allocations()` only returns filled cells, so any BM
    with nothing assigned yet — completely normal mid-editing, before
    the whole matrix is filled in — always tripped that warning on every
    routine Save (field report: "trying to save with just a party drops
    an error that matrix has bms that are not on the list, when in fact
    its complaining because slots where not filled")."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.core.models import FUNCTIONS, PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.municipality.name = "Мионица"
    # Two stations — only one gets an allocation below, leaving the
    # other with zero: exactly the "not filled yet" state that used to
    # false-positive as a BM mismatch.
    state.oik.polling_stations = [
        PollingStation(bm_number=1, name="Школа А"),
        PollingStation(bm_number=2, name="Школа Б"),
    ]
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "Српска напредна странка"},
    )

    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **kw: warned.append("warned") or QMessageBox.StandardButton.Ok,
    )

    tab = ElectionSettingsTab(state)
    try:
        tab._load_from_state()

        assert tab._matrix_grid is not None
        combo = tab._matrix_grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        idx = combo.findText("СНС")
        combo.setCurrentIndex(idx)
        combo.activated.emit(idx)
        # BM 2's row is left entirely unassigned.

        tab._save()

        assert warned == [], (
            "An incompletely-filled matrix must not pop up a 'BM mismatch' "
            "warning on a routine Save — that's expected mid-editing state, "
            "not a data-integrity error."
        )
    finally:
        tab.deleteLater()
