"""§21: the nacelnik (municipal chief) is a silent system constant, not a
row in the "Странке" (parliamentary groups) table on the Election Settings
tab. Its display name itself lives on OikConstants (OIK Settings tab), not
ElectionConfig — the chief doesn't change between election cycles, so
"New election cycle" must not reset it (see settings_election.py's
_on_new_cycle and OikSettingsTab).
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


def _make_election_tab():
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.config.election import (
        DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    )
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
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
    tab._load_from_state()  # noqa: SLF001
    return tab


def test_default_never_appears_as_a_parties_table_row() -> None:
    tab = _make_election_tab()
    try:
        abbrevs = [r["abbrev"] for r in tab._parties_rows]
        assert "_default" not in abbrevs
        assert abbrevs == ["СНС"]
    finally:
        tab.deleteLater()


def test_nacelnik_full_name_field_lives_on_oik_settings_and_round_trips() -> None:
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state._oik = OikConstants(  # noqa: SLF001 — test-only fixture path
        polling_stations=[PollingStation(bm_number=1, name="БМ 1")],
        nacelnik_full_name="начелника Општинске управе",
    )
    tab = OikSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    try:
        assert tab.ed_nacelnik_full_name.text() == "начелника Општинске управе"

        tab.ed_nacelnik_full_name.setText("нови текст")
        tab._save()  # noqa: SLF001
        assert state.oik.nacelnik_full_name == "нови текст"
    finally:
        tab.deleteLater()


def test_legacy_election_config_nacelnik_name_migrates_to_oik(tmp_path: Path) -> None:
    """Cross-file, one-time migration: an old election_config.json that
    still has a plain nacelnik_full_name field (or, older still,
    party_full_names["_default"]) must have that value pulled forward
    into oik_constants.json on the very next app launch, since
    ElectionConfig no longer parses either location at all."""
    import json

    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState

    app_paths.election_config_path().parent.mkdir(parents=True, exist_ok=True)
    app_paths.election_config_path().write_text(json.dumps({
        "election": {"date_full": "17. децембар 2026. године",
                     "types": ["parliamentary"], "rik_decision": "X"},
        "document": {"number_prefix": "013-5-30", "legal_basis": "L"},
        "party_full_names": {"СНС": "A"},
        "nacelnik_full_name": "начелника Општинске управе (legacy)",
        "election_uuid": "legacy-migration-uuid",
    }, ensure_ascii=False), encoding="utf-8")

    state = AppState()
    assert state.oik.nacelnik_full_name == "начелника Општинске управе (legacy)"

    # Persisted immediately — a second launch must not depend on the
    # (now-ignored) election_config.json field surviving.
    from biracki_odbor.config import oik as oik_mod
    reloaded_oik = oik_mod.load(app_paths.oik_constants_path())
    assert reloaded_oik.nacelnik_full_name == "начелника Општинске управе (legacy)"


def test_legacy_default_party_entry_migrates_to_oik(tmp_path: Path) -> None:
    """Even older configs stored the chief's name as
    party_full_names["_default"] (pre-nacelnik_full_name-field). That
    must migrate too, all the way to OikConstants."""
    import json

    from biracki_odbor import app_paths
    from biracki_odbor.gui.app_state import AppState

    app_paths.election_config_path().parent.mkdir(parents=True, exist_ok=True)
    app_paths.election_config_path().write_text(json.dumps({
        "election": {"date_full": "17. децембар 2023. године",
                     "types": ["parliamentary"], "rik_decision": "X"},
        "document": {"number_prefix": "013-5-30", "legal_basis": "L"},
        "party_full_names": {"СНС": "A", "_default": "врло стар текст"},
        "election_uuid": "very-old-uuid",
    }, ensure_ascii=False), encoding="utf-8")

    state = AppState()
    assert state.oik.nacelnik_full_name == "врло стар текст"
    assert "_default" not in state.election.party_full_names


def test_nacelnik_proposal_name_appends_municipality() -> None:
    """Regression: the operator types just the role ("начелника Општинске
    управе") — the municipality name must be appended automatically so
    решења/измене don't read a generic, town-less proposal line (field
    report: 'resenje should have "на предлог начелника Општинске управе
    општине Уб" or insert municipality name')."""
    from biracki_odbor.config.oik import Municipality, OikConstants

    oik = OikConstants(
        municipality=Municipality(name="Уб"),
        nacelnik_full_name="начелника Општинске управе",
    )
    assert oik.nacelnik_proposal_name == "начелника Општинске управе општине Уб"


def test_nacelnik_proposal_name_falls_back_to_default_role_when_blank() -> None:
    """The chief's office/title is a fixed legal fact (Закон о локалној
    самоуправи), the same in every municipality — not per-OIK config the
    operator has to remember to fill in. A blank field (old config saved
    before this default existed, or cleared by mistake) must still
    produce a correct decision line, not a blank one (field report:
    "why would I need to fill out the text Начелник, when its the
    function that exist in every municipality...")."""
    from biracki_odbor.config.oik import DEFAULT_NACELNIK_ROLE, Municipality, OikConstants

    oik = OikConstants(municipality=Municipality(name="Уб"), nacelnik_full_name="")
    assert oik.nacelnik_proposal_name == f"{DEFAULT_NACELNIK_ROLE} општине Уб"


def test_oik_constants_defaults_nacelnik_role_on_fresh_config() -> None:
    from biracki_odbor.config.oik import DEFAULT_NACELNIK_ROLE, OikConstants

    assert OikConstants().nacelnik_full_name == DEFAULT_NACELNIK_ROLE


def test_nacelnik_proposal_name_without_municipality_configured() -> None:
    from biracki_odbor.config.oik import OikConstants

    oik = OikConstants(nacelnik_full_name="начелника Општинске управе")
    assert oik.nacelnik_proposal_name == "начелника Општинске управе"
