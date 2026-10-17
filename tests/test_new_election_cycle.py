"""Regression test: 'New election cycle' must reset election-cycle-specific
settings, not just clear output files and bump the UUID.

Before this fix, `_on_new_cycle` only deleted output files and reassigned
`election_uuid` — the Изборни циклус tab's own settings (dates, party list
+ quotas + contacts, candidacies, RIK provision, nacelnik text) and the
lock password all silently carried over from the previous cycle, which is
exactly what "new cycle" is supposed to prevent (field report: "Novi
izborni ciklus after backup doesnt reset data in izborni ciklus tab").

OIK/municipality identity (config/oik.py, minus the lock password) is NOT
election-cycle data and must survive untouched.
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


def test_new_cycle_resets_election_settings_and_password(tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.config.oik import DEFAULT_LOCK_PASSWORD
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    state = AppState()
    old_uuid = "old-cycle-uuid"
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "Посланичке групе СРПСКА НАПРЕДНА СТРАНКА"},
        election_uuid=old_uuid,
    )
    original_municipality_name = state.oik.municipality.name
    state.oik.lock_password = "custom-password-from-old-cycle"
    state.oik.nacelnik_full_name = "начелника Општинске управе"
    state.save_oik()

    # Stub the confirmation dialog (Yes) and the backup flow (skip real I/O).
    # _on_new_cycle imports run_backup_flow locally at call time, so
    # patching the source module is what actually takes effect.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    import biracki_odbor.gui.dialogs.backup_flow as backup_flow_mod
    monkeypatch.setattr(backup_flow_mod, "run_backup_flow", lambda parent: "backup ok")

    tab = ElectionSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001 — populate widgets from state

    tab._on_new_cycle()  # noqa: SLF001 — the button's handler

    # Election settings: blank slate, fresh UUID.
    ec = state.election
    assert ec.election_uuid != old_uuid
    assert ec.election_uuid != ""
    assert ec.election.dates.date_full == ""
    assert ec.election.types == []
    assert ec.party_full_names == {}

    # Lock password reset to the shared default.
    assert state.oik.lock_password == DEFAULT_LOCK_PASSWORD

    # OIK/municipality identity untouched — including the chief's name,
    # which lives on OikConstants precisely so it survives this reset.
    assert state.oik.municipality.name == original_municipality_name
    assert state.oik.nacelnik_full_name == "начелника Општинске управе"

    # The tab's own form must reflect the reset immediately, not just the
    # underlying state — otherwise the operator sees stale values until
    # they navigate away and back.
    assert tab.ed_password.text() == DEFAULT_LOCK_PASSWORD


def test_new_cycle_clears_matrix_template_allocations(tmp_path: Path, monkeypatch) -> None:
    """Regression: the seed matrix template (Stalni_sastav.xlsx) is NOT
    output data — it's not touched by the output-file cleanup — but its
    allocations are just as election-cycle-specific as everything else.
    Left alone, re-adding a party abbreviation from the old cycle would
    resurface its old allocations as "stale" (red) entries in the matrix
    grid (field report: "the matrix shows the old election cycle data as
    red")."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from biracki_odbor import app_paths
    from biracki_odbor.config.oik import DEFAULT_LOCK_PASSWORD
    from biracki_odbor.core.models import Allocation, PollingStation
    from biracki_odbor.core.template import build_blank_template, read_template
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    stations = [PollingStation(bm_number=1, name="Школа А")]
    template_path = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
    build_blank_template(
        template_path, stations=stations,
        allocations=[Allocation(bm_number=1, function="Председник", party="СНС")],
    )

    state = AppState()
    state.oik.polling_stations = stations
    state.oik.template_path = str(template_path)
    state.save_oik()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    import biracki_odbor.gui.dialogs.backup_flow as backup_flow_mod
    monkeypatch.setattr(backup_flow_mod, "run_backup_flow", lambda parent: "backup ok")

    tab = ElectionSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    tab._on_new_cycle()  # noqa: SLF001

    tpl_data, _report = read_template(template_path)
    assert tpl_data.allocations == [], (
        "Old allocations must be wiped from the seed template, or they'd "
        "resurface as stale/red entries once a matching party is re-added."
    )
    assert len(tpl_data.polling_stations_from_template) == 1, (
        "The template's polling-station scaffolding (OIK-owned, unrelated "
        "to the election cycle) should survive the reset."
    )


def test_new_cycle_clears_stale_nacelnik_export(tmp_path: Path, monkeypatch) -> None:
    """Regression: the chief's takeover template (nacelnik_sablion.xlsx,
    listing that cycle's empty slots) was not cleared by 'New election
    cycle' — the old cycle's slot list would silently carry into the new
    one (field report: "old nacelnik exported table was not
    removed/cleared")."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from biracki_odbor import app_paths
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.nacelnik_xlsx import export_nacelnik_template
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    nacelnik_path = app_paths.master_dir() / "nacelnik_sablion.xlsx"
    export_nacelnik_template(
        [Person(bm_number=1, function="Председник", party="СНС")],
        {}, nacelnik_path,
    )
    assert nacelnik_path.exists()

    state = AppState()
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "Посланичке групе СРПСКА НАПРЕДНА СТРАНКА"},
    )

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    import biracki_odbor.gui.dialogs.backup_flow as backup_flow_mod
    monkeypatch.setattr(backup_flow_mod, "run_backup_flow", lambda parent: "backup ok")

    tab = ElectionSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    tab._on_new_cycle()  # noqa: SLF001

    assert not nacelnik_path.exists(), (
        "The chief's takeover template must be cleared on a new cycle, "
        "not silently carried into the next one."
    )
