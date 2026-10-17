"""Проширени must be reachable without electoral lists.

Проширени is genuinely independent of стални and of the РИК матрица — no
проширени code path reads Stalni_sastav.xlsx, template_path(),
read_template() or generation_log.stalni. The section used to be blocked
in the sidebar until a candidacy list existed, which presented the
operator with a dead button and a tooltip. The section now opens on
onboarding alone; "no lists yet" is stated inside the workspace, and the
phases themselves remain the hard gate.
"""

from __future__ import annotations

import inspect
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


def _make_state(tmp_path, *, with_lists: bool = False):
    from biracki_odbor.config.candidacies import Entity
    from biracki_odbor.gui.app_state import AppState
    from tests.test_phase1 import _make_oik
    from tests.test_phase3 import _make_election

    state = AppState()
    state._oik = _make_oik(2)  # noqa: SLF001
    state._election = _make_election()  # noqa: SLF001
    # _make_election() ships an empty registry, which is exactly the
    # state under test here — populate it only when asked.
    if with_lists:
        state.election.candidacies.entities = [
            Entity("lista-1", "Изборна листа 1", "party", "local", 1),
        ]
    return state


# ── Sidebar ──────────────────────────────────────────────────────────


def test_prosireni_is_enabled_on_onboarding_alone(app) -> None:
    from biracki_odbor.gui.sidebar import SECTION_PROSIRENI, Sidebar

    bar = Sidebar()
    try:
        bar.set_workflow_enabled(True)

        button = bar._items[SECTION_PROSIRENI]  # noqa: SLF001
        assert button.isEnabled()
        assert button.toolTip() == ""
    finally:
        bar.deleteLater()


def test_prosireni_matches_stalni_exactly(app) -> None:
    """The two workflow sections have the same entry requirement now —
    if they ever diverge again it should be a deliberate change."""
    from biracki_odbor.gui.sidebar import SECTION_PROSIRENI, SECTION_STALNI, Sidebar

    bar = Sidebar()
    try:
        for enabled in (True, False):
            bar.set_workflow_enabled(enabled)
            stalni = bar._items[SECTION_STALNI]  # noqa: SLF001
            prosireni = bar._items[SECTION_PROSIRENI]  # noqa: SLF001
            assert prosireni.isEnabled() == stalni.isEnabled() == enabled
            assert prosireni.toolTip() == stalni.toolTip()
    finally:
        bar.deleteLater()


def test_prosireni_is_still_blocked_before_onboarding(app) -> None:
    """Relaxing the lists requirement must not open the section on a
    half-configured install."""
    from biracki_odbor.gui.sidebar import SECTION_PROSIRENI, Sidebar

    bar = Sidebar()
    try:
        bar.set_workflow_enabled(False)

        button = bar._items[SECTION_PROSIRENI]  # noqa: SLF001
        assert not button.isEnabled()
        assert button.toolTip()  # explains why
    finally:
        bar.deleteLater()


def test_set_workflow_enabled_no_longer_takes_prosireni_ready() -> None:
    """Guards against the gate being quietly reintroduced."""
    from biracki_odbor.gui.sidebar import Sidebar

    params = inspect.signature(Sidebar.set_workflow_enabled).parameters
    assert "prosireni_ready" not in params


# ── Workspace notice ─────────────────────────────────────────────────


def _banner_text(banner) -> str:
    return banner._label.text()  # noqa: SLF001


def test_workspace_warns_when_no_lists_are_registered(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = _make_state(tmp_path)
    state.election.candidacies.entities = []
    ws = ProsireniWorkspace(state)
    try:
        text = _banner_text(ws.lists_banner)

        assert text, "an empty registry must be stated, not left silent"
        # It has to say where to go, not merely that something is wrong.
        assert "Candidates" in text
        # Warnings must not auto-hide — this one has to survive being read.
        assert ws.lists_banner.objectName() == "WarnBanner"
    finally:
        ws.deleteLater()


def test_the_warning_clears_once_a_list_is_added(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = _make_state(tmp_path)
    populated = _make_state(tmp_path, with_lists=True).election
    ws = ProsireniWorkspace(state)
    try:
        assert _banner_text(ws.lists_banner)

        state._election = populated  # noqa: SLF001
        state.election_changed.emit()

        assert _banner_text(ws.lists_banner) == ""
    finally:
        ws.deleteLater()


def test_no_warning_when_lists_already_exist(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = _make_state(tmp_path, with_lists=True)
    ws = ProsireniWorkspace(state)
    try:
        assert _banner_text(ws.lists_banner) == ""
    finally:
        ws.deleteLater()


def test_the_workspace_is_reachable_with_an_empty_registry(app, tmp_path) -> None:
    """The point of the change: tabs are usable, not disabled."""
    from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace

    state = _make_state(tmp_path)
    state.election.candidacies.entities = []
    ws = ProsireniWorkspace(state)
    try:
        assert ws.tabs.isTabEnabled(0)
        assert ws.tabs.isTabEnabled(1)
    finally:
        ws.deleteLater()


# ── The real gate still holds ────────────────────────────────────────


def test_phase1_still_refuses_to_run_without_lists(app, tmp_path) -> None:
    """Now that the sidebar lets the operator in, this preflight is the
    only thing standing between an empty registry and a bad run."""
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = _make_state(tmp_path)
    state.election.candidacies.entities = []
    tab = ProsireniPhase1Tab(state)
    try:
        message = tab._preflight_check()  # noqa: SLF001

        assert message is not None
        assert "Candidac" in message or "Кандидат" in message
    finally:
        tab.deleteLater()


# ── The РИК-decision save gate ───────────────────────────────────────
#
# Reported with screenshots: an electoral list was typed in, Save was
# refused, and the reason read "'rik_decision' (одлука РИК-а) је празно".
# Blocking is intended -- the РИК decision number and date are what start
# the election cycle. The message was the defect: it quoted an internal
# field name, named neither field to fill nor where, and gave no hint
# that it was also the reason the list would not save.


def _election_without_rik_decision():
    from tests.test_phase3 import _make_election

    ec = _make_election()
    ec.election.rik_decision = ""
    return ec


def test_a_missing_rik_decision_still_blocks_saving() -> None:
    """Deliberately still a hard gate, not a warning."""
    errs = _election_without_rik_decision().validate()

    assert len(errs) == 1


def test_the_message_names_both_fields_and_where_they_are() -> None:
    """The operator has to be able to act on it without guessing."""
    message = _election_without_rik_decision().validate()[0]

    assert "Број одлуке" in message
    assert "Датум одлуке" in message
    assert "Изборни циклус" in message


def test_the_message_does_not_quote_the_internal_field_name() -> None:
    """`rik_decision` is a Python attribute, not something the operator
    can find anywhere in the interface."""
    message = _election_without_rik_decision().validate()[0]

    assert "rik_decision" not in message


def test_the_message_explains_that_saving_is_what_is_blocked() -> None:
    """The surprising part in the field report was that an unrelated
    electoral list would not persist either — because the tab saves as
    one unit."""
    message = _election_without_rik_decision().validate()[0]

    assert "сачувати" in message or "сачува" in message


def test_a_complete_election_still_validates_clean() -> None:
    from tests.test_phase3 import _make_election

    assert _make_election().validate() == []


# ── "Отвори фасциклу" ────────────────────────────────────────────────
#
# Reported from the field: the button did nothing on Проширени tab 1.
# It was disabled until a successful Phase 1 — and проширени cannot run
# Phase 1 without a candidacy registry, so on a fresh cycle it was
# permanently dead with nothing on screen to explain why.


def test_the_open_folder_button_works_before_any_run(app, tmp_path) -> None:
    """state.files_dir() creates the folder on demand, so there is no
    run this action depends on."""
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    tab = ProsireniPhase1Tab(_make_state(tmp_path))
    try:
        assert tab.btn_open.isEnabled()
    finally:
        tab.deleteLater()


def test_the_stalni_open_folder_button_works_before_any_run(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab

    tab = Phase1Tab(_make_state(tmp_path))
    try:
        assert tab.btn_open.isEnabled()
    finally:
        tab.deleteLater()


def test_opening_the_folder_creates_and_targets_the_export_directory(
    app, tmp_path, monkeypatch,
) -> None:
    """The outcome that matters: a real, existing directory is handed to
    the file manager — not merely that Popen was called."""
    import biracki_odbor.gui.tabs.phase1 as mod
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = _make_state(tmp_path)
    state.app_settings.default_files_dir = str(tmp_path / "exports")
    opened: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda args, **kw: opened.append(args))

    tab = ProsireniPhase1Tab(state)
    try:
        tab.btn_open.click()

        assert len(opened) == 1
        target = Path(opened[0][1])
        assert target.is_dir(), f"{target} should have been created on demand"
        assert "проширени" in target.name
    finally:
        tab.deleteLater()


def test_the_two_workflows_open_different_folders(app, tmp_path) -> None:
    """Стални and проширени both produce per-list .xlsx files; mixing
    them in one folder would make it impossible to tell which cycle a
    file belongs to."""
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab, ProsireniPhase1Tab

    state = _make_state(tmp_path)
    stalni, prosireni = Phase1Tab(state), ProsireniPhase1Tab(state)
    try:
        assert stalni._export_purpose != prosireni._export_purpose  # noqa: SLF001
    finally:
        stalni.deleteLater()
        prosireni.deleteLater()


def test_opening_the_folder_says_where_it_opened(app, tmp_path, monkeypatch) -> None:
    """A file-manager window can open somewhere the operator cannot see
    it — behind a maximised app, or on a second display that is switched
    off. Without confirmation a working button is indistinguishable from
    a dead one, which is exactly how this was mis-reported as a bug."""
    import biracki_odbor.gui.tabs.phase1 as mod
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = _make_state(tmp_path)
    state.app_settings.default_files_dir = str(tmp_path / "exports")
    monkeypatch.setattr(mod.subprocess, "Popen", lambda args, **kw: None)

    tab = ProsireniPhase1Tab(state)
    try:
        tab.btn_open.click()

        shown = _banner_text(tab.banner)
        assert shown, "a successful open must still confirm itself"
        assert "проширени" in shown, shown  # the actual destination, not just 'done'
    finally:
        tab.deleteLater()


def test_a_failure_to_open_still_reveals_the_path(app, tmp_path, monkeypatch) -> None:
    """If the file manager cannot be launched the operator still needs to
    know where to look."""
    import biracki_odbor.gui.tabs.phase1 as mod
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = _make_state(tmp_path)
    state.app_settings.default_files_dir = str(tmp_path / "exports")

    def boom(*_a, **_kw):
        raise OSError("no file manager")

    monkeypatch.setattr(mod.subprocess, "Popen", boom)
    shown = []
    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **kw: shown.append(a))

    tab = ProsireniPhase1Tab(state)
    try:
        tab.btn_open.click()

        assert shown, "the path must be surfaced when the launch fails"
        assert "проширени" in " ".join(str(x) for x in shown[0])
    finally:
        tab.deleteLater()
