"""Regression guard: the embedded matrix grid must show already-saved
allocations on a fresh app start (`ElectionSettingsTab` constructed
cold against on-disk state), not just after an in-session edit.

2026-07-12 investigation: a report of "grid doesn't show saved values
on restart" turned out NOT to be a construction-order bug — verified
directly against the real app data that a save→fresh-construction
round-trip already worked correctly. The actual cause was a save-flow
UX gap (a separate "Сачувај матрицу" action that's easy to forget,
since the main "Save settings" button didn't persist grid edits) —
now fixed by having `_save()` also call `_save_matrix()`. This test
stays as a plain regression guard for the construction-time prefill
behavior itself, independent of that fix.
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


def test_matrix_grid_shows_saved_allocations_on_fresh_construction(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from biracki_odbor import app_paths
    from biracki_odbor.config import election as election_mod
    from biracki_odbor.config import oik as oik_mod
    from biracki_odbor.config.election import ElectionConfig
    from biracki_odbor.core.models import Allocation, FUNCTIONS, PollingStation
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    stations = [PollingStation(bm_number=1, name="Школа А"), PollingStation(bm_number=2, name="Школа Б")]

    # Write a real template file with a saved allocation, as if a
    # previous session had already used "Save matrix".
    template_path = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
    build_blank_template(
        template_path, stations=stations,
        allocations=[Allocation(bm_number=1, function="Председник", party="СНС")],
    )

    oik = oik_mod.OikConstants(polling_stations=stations, template_path=str(template_path))
    oik_mod.save(oik, app_paths.oik_constants_path())

    ec = ElectionConfig(
        party_full_names={"СНС": "Српска напредна странка"},
    )
    election_mod.save(ec, app_paths.election_config_path())

    # Fresh construction, exactly as happens on app launch.
    state = AppState()
    tab = ElectionSettingsTab(state)
    try:
        assert tab._matrix_grid is not None, (
            "Matrix grid must be built with real data on first construction, "
            "not stuck showing the 'configure parties' placeholder."
        )
        combo = tab._matrix_grid.table.cellWidget(0, FUNCTIONS.index("Председник"))
        assert combo.currentText() == "СНС", (
            "Previously saved allocation must be prefilled on a fresh app start."
        )
    finally:
        tab.deleteLater()


def test_matrix_grid_appears_after_adding_party_before_save(tmp_path: Path) -> None:
    """Regression: adding a party (e.g. right after 'New election cycle'
    reset, when the list starts empty) must make the grid appear
    immediately, without requiring 'Save settings' first.

    _rebuild_matrix_grid() used to read party abbreviations from
    self.state.election.party_full_names — the last-SAVED config —
    instead of the tab's own live _parties_rows, so a freshly-added,
    not-yet-saved party never made the grid show up (field report:
    "matrix is missing its gui component only import/export" after
    adding a party post-reset)."""
    from PySide6.QtWidgets import QApplication

    from biracki_odbor import app_paths
    from biracki_odbor.config import oik as oik_mod
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    stations = [PollingStation(bm_number=1, name="Школа А")]
    oik = oik_mod.OikConstants(polling_stations=stations)
    oik_mod.save(oik, app_paths.oik_constants_path())

    # No election_config.json yet — ElectionConfig() loads with an empty
    # party_full_names, exactly like right after "New election cycle".
    state = AppState()
    tab = ElectionSettingsTab(state)
    try:
        assert tab._matrix_grid is None, (
            "Sanity: with no parties declared, the grid must not be built yet."
        )
        # Mirrors exactly what _add_party_row() does once its (modal) dialog
        # is accepted — appends a row, then refreshes the views. Calling
        # these two directly avoids driving the modal dialog in the test.
        tab._append_party_row("СНС", "Српска напредна странка", "", "")
        tab._refresh_parties_view()

        assert tab._matrix_grid is not None, (
            "Adding a party must make the grid appear immediately, without "
            "requiring 'Save settings' first."
        )
    finally:
        tab.deleteLater()


def test_template_section_locked_and_collapsed_until_ready(tmp_path: Path) -> None:
    """Regression: the Allocation template section must read as visibly
    "not ready" (locked + collapsed) rather than open with just an
    explanatory placeholder inside — field report: "matrix box should
    remain gray/closed until all of its requirements are filled". Once
    a station and a party both exist, it must unlock (but not force
    itself open — matches the nacelnik section's established pattern
    of leaving expand/collapse to the operator)."""
    from PySide6.QtWidgets import QApplication

    from biracki_odbor import app_paths
    from biracki_odbor.config import oik as oik_mod
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    oik_mod.save(oik_mod.OikConstants(), app_paths.oik_constants_path())

    state = AppState()
    tab = ElectionSettingsTab(state)
    try:
        assert tab._template_section.is_locked() is True
        assert tab._template_section.is_expanded() is False

        state.oik.polling_stations = [PollingStation(bm_number=1, name="Школа А")]
        tab._append_party_row("СНС", "Српска напредна странка", "", "")
        tab._refresh_parties_view()

        assert tab._template_section.is_locked() is False
    finally:
        tab.deleteLater()
