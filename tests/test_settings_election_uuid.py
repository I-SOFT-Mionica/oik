"""Regression tests for the v0.4.0 election_uuid regeneration bug.

In v0.4.0 every save of Election Settings constructed a fresh
ElectionConfig without forwarding the existing `election_uuid`. The save
helper then lazy-generated a new UUID on every save — which invalidated
the popunjeni cache and Phase 1 file markers across sessions.

These tests pin the fixed behavior: `_build_election()` must preserve
whatever UUID the on-disk config already carried.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    """Sandbox BIRACKI_ODBOR_HOME so the test doesn't touch real configs."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    # Disable the in-app updater so the smoke construction doesn't spawn
    # a network-bound QThread that outlives the test.
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def test_build_election_preserves_existing_uuid(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    state = AppState()
    # Seed a known UUID — the bug regenerated this on every save.
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(date_full="17. децембар 2026. године"),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "A"},
        election_uuid="known-uuid-do-not-regenerate",
    )

    tab = ElectionSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001 — populate widgets from state

    rebuilt = tab._build_election()  # noqa: SLF001 — the path the Save button hits

    assert rebuilt.election_uuid == "known-uuid-do-not-regenerate", (
        "Election Settings save must NOT blank/regenerate the UUID — "
        "doing so invalidates popunjeni cache + Phase 1 markers across sessions."
    )


def test_build_election_preserves_prosireni_session_fields(tmp_path: Path) -> None:
    """Field report: every Election Settings save silently wiped prosireni's
    own session_date/session_number, even though the sibling field
    subbroj_start_prosireni two lines below was correctly preserved --
    an oversight, not an intentional per-field decision (Phase 3's
    prosireni tab is the only UI that ever writes these two fields)."""
    from PySide6.QtWidgets import QApplication

    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    state = AppState()
    state._election = ElectionConfig(  # noqa: SLF001 — test-only fixture path
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date_prosireni="20. децембра 2026. године",
                session_number_prosireni="3",
            ),
            types=["parliamentary"],
            rik_decision="Одлуком РИК-а",
        ),
        document=DocumentInfo(number_prefix="013-5-30", legal_basis="L"),
        party_full_names={"СНС": "A"},
    )

    tab = ElectionSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001

    rebuilt = tab._build_election()  # noqa: SLF001 — the path the Save button hits

    assert rebuilt.election.dates.session_date_prosireni == "20. децембра 2026. године"
    assert rebuilt.election.dates.session_number_prosireni == "3"


def test_election_save_does_not_regenerate_existing_uuid(tmp_path: Path) -> None:
    """Belt-and-suspenders: even if some other code path forgets to pass
    election_uuid, the save helper itself must preserve an existing one
    rather than blanking and re-generating it."""
    from biracki_odbor.config import election as election_mod
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    ec = ElectionConfig(
        election=ElectionInfo(dates=ElectionDates(date_full="x"), types=["parliamentary"]),
        document=DocumentInfo(),
        election_uuid="seeded-uuid",
    )
    election_mod.save(ec, tmp_path / "ec.json")
    assert ec.election_uuid == "seeded-uuid", (
        "save() must not touch a non-empty election_uuid"
    )
    # And a subsequent load reads it back unchanged.
    loaded = election_mod.load(tmp_path / "ec.json")
    assert loaded.election_uuid == "seeded-uuid"
