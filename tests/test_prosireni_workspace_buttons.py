"""Tests for ProsireniWorkspace button behaviour.

Verifies that buttons in the prošireni workflow dispatch to the correct
operations and do not silently swallow clicks:

  - Покрени (Phase 1): calls start_worker(parent, fn) with no extra positional
    args.  Passing callbacks as positional args to start_worker was the original
    bug — this test catches any regression.
  - Отвори фасциклу (Phase 1 / Phase 3): calls subprocess.Popen with explorer
    and the correct directory.
  - Отвори збирну табелу (Phase 2): does NOT call Popen when the master file
    is absent (defensive guard, not an open-on-missing-file call).
  - Пошаљи листама (Phase 1): opens SendToPartiesDialog with the prosireni
    subject token (not the stalni token).
  - btn_send state: hidden without email client; visible-but-disabled at startup.
"""

from __future__ import annotations

from pathlib import Path
import pytest


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(h))
    monkeypatch.setattr("biracki_odbor._release_info.GITHUB_REPO", "", raising=False)
    return h


def _minimal_state(home: Path):
    """AppState with one polling station and one entity — enough to pass preflight."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.config.election import ElectionConfig, ElectionInfo, ElectionDates
    from biracki_odbor.config.candidacies import CandidaciesRegistry, Entity

    oik = OikConstants(
        polling_stations=[PollingStation(bm_number=1, name="Тест БМ 1")]
    )
    entity = Entity(entity_id="sns", name="СНС", entity_type="party", level="local", submission_order=1)
    ec = ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(date_full="2. јуна 2024. године")
        ),
        candidacies=CandidaciesRegistry(entities=[entity]),
        election_uuid="test-uuid-prosireni",
    )
    state = AppState()
    state._oik = oik
    state._election = ec
    return state


# ── Phase 1 — Покрени ─────────────────────────────────────────────────────────


def test_phase1_pokrni_shows_error_when_no_entities(app, home) -> None:
    """Clicking Покрени with an empty registry shows a banner error without touching the worker."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = AppState()
    tab = ProsireniPhase1Tab(state)
    try:
        tab.btn_run.click()
        assert not tab.banner.isHidden(), "Banner must be visible when Покрени finds no state"
    finally:
        tab.deleteLater()


def test_phase1_pokrni_dispatches_start_worker_correctly(app, home, monkeypatch) -> None:
    """Clicking Покрени with valid state calls start_worker(parent, fn) — no callbacks as positional args.

    The original bug was: start_worker(self, _work, _done, _err) which passed _done and
    _err as positional arguments to _work instead of connecting them as signals.  Any
    recurrence of that pattern will produce extra_args != () here.
    """
    from unittest.mock import MagicMock

    calls: list[dict] = []
    fake_worker = MagicMock()
    fake_thread = MagicMock()

    def fake_start_worker(parent, fn, *args, **kwargs):
        calls.append({"fn": fn, "extra_args": args, "extra_kwargs": kwargs})
        return fake_worker, fake_thread

    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase1.start_worker",
        fake_start_worker,
    )
    monkeypatch.setattr(
        "biracki_odbor.validation.preflight.check_oik",
        lambda _: [],
    )

    state = _minimal_state(home)
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    tab = ProsireniPhase1Tab(state)
    try:
        tab.btn_run.click()
        assert len(calls) == 1, "start_worker was not called at all"
        extra = calls[0]["extra_args"]
        assert extra == (), (
            f"start_worker received extra positional args {extra!r} — "
            "callbacks must be connected as signals, not passed as fn arguments"
        )
    finally:
        tab.deleteLater()


# ── Phase 1 — Отвори фасциклу ────────────────────────────────────────────────


def test_phase1_open_folder_calls_explorer_with_export_path(app, home, monkeypatch) -> None:
    """Отвори фасциклу opens the user's own export folder (files_dir),
    never the app's internal stranka_fajlovi_prosireni directory —
    operators should never be pointed into app-internal storage."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    popen_calls: list[list] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase1.subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )

    state = AppState()
    tab = ProsireniPhase1Tab(state)
    try:
        tab._open_folder()
        assert len(popen_calls) == 1, "subprocess.Popen was not called"
        assert popen_calls[0][0] == "explorer"
        expected = str(state.files_dir("Странке (проширени)"))
        assert popen_calls[0][1] == expected
        assert "stranka_fajlovi_prosireni" not in popen_calls[0][1]
    finally:
        tab.deleteLater()


# ── Phase 1 — Пошаљи листама ─────────────────────────────────────────────────


def test_phase1_send_button_hidden_without_email_client(app, home, monkeypatch) -> None:
    """btn_send is hidden when no email backend is available."""
    monkeypatch.setattr(
        "biracki_odbor.integrations.email_client.any_available",
        lambda: False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = AppState()
    tab = ProsireniPhase1Tab(state)
    try:
        assert not tab.btn_send.isVisible(), "btn_send should be hidden when no email client"
    finally:
        tab.deleteLater()


def test_phase1_send_button_visible_but_disabled_at_startup(app, home, monkeypatch) -> None:
    """btn_send is visible but disabled before a successful Покрени run."""
    monkeypatch.setattr(
        "biracki_odbor.integrations.email_client.any_available",
        lambda: True,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = AppState()
    tab = ProsireniPhase1Tab(state)
    try:
        assert not tab.btn_send.isHidden(), "btn_send should not be hidden when email client is present"
        assert not tab.btn_send.isEnabled(), (
            "btn_send must be disabled before Покрени has run successfully"
        )
    finally:
        tab.deleteLater()


def test_phase1_send_opens_dialog_with_prosireni_subject_token(app, home, monkeypatch) -> None:
    """Пошаљи листама opens SendToPartiesDialog with the prosireni subject token, not the stalni one."""
    from PySide6.QtWidgets import QDialog
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    dialog_kwargs: list[dict] = []

    class FakeSendDialog:
        def __init__(self, **kwargs):
            dialog_kwargs.append(kwargs)

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(
        "biracki_odbor.gui.dialogs.send_to_parties_dialog.SendToPartiesDialog",
        FakeSendDialog,
    )

    state = _minimal_state(home)
    tab = ProsireniPhase1Tab(state)
    try:
        tab._last_files_written = [Path(home) / "fake_СНС.xlsx"]
        tab._on_send()

        assert len(dialog_kwargs) == 1, "SendToPartiesDialog was not opened"
        token: str = dialog_kwargs[0].get("subject_token", "")
        assert "PROSIRENI" in token.upper(), (
            f"Expected prosireni subject token (containing PROSIRENI), got: {token!r}"
        )
        assert token != "", "Subject token must not be empty"
    finally:
        tab.deleteLater()


# ── Phase 2 — Увези фајлове ──────────────────────────────────────────────────


def _stub_cache(monkeypatch) -> None:
    """Stub out popunjeni_cache load/save/CacheEntry so tests don't touch real files."""
    from biracki_odbor.core import popunjeni_cache
    stub = popunjeni_cache.CacheData(election_uuid="test-uuid-prosireni")
    fake_entry = popunjeni_cache.CacheEntry(mtime_ns=0, size=0)
    monkeypatch.setattr("biracki_odbor.core.popunjeni_cache.load", lambda **kw: stub)
    monkeypatch.setattr("biracki_odbor.core.popunjeni_cache.save", lambda data: None)
    monkeypatch.setattr("biracki_odbor.core.popunjeni_cache.CacheEntry.from_parsed",
                        lambda *a, **kw: fake_entry)
    monkeypatch.setattr("biracki_odbor.core.popunjeni_io.parse_for_cache",
                        lambda path: ([], []))


def test_phase2_import_files_passes_correct_args_to_import_file(app, home, monkeypatch) -> None:
    """_import_files must call import_file(src: Path, election: ElectionConfig, dir: Path).

    The original bug passed (str(popunjeni_dir), ..., election_uuid=...) which caused
    a TypeError at runtime. This test catches any recurrence of that mistake.
    """
    from pathlib import Path
    from biracki_odbor.core.popunjeni_io import ImportOutcome
    from biracki_odbor.config.election import ElectionConfig
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    import_calls: list[tuple] = []
    fake_outcome = ImportOutcome(
        source=Path("fake.xlsx"), canonical_path=Path("p/fake.xlsx"),
        party="СНС", status="imported", received_time_iso="2026-01-01T00:00:00Z",
    )

    _stub_cache(monkeypatch)
    monkeypatch.setattr(
        "biracki_odbor.core.popunjeni_io.import_file",
        lambda src, election, popunjeni_dir, **kw: import_calls.append((src, election, popunjeni_dir)) or fake_outcome,
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        lambda *a, **kw: (["C:/fake/sns.xlsx"], "Excel (*.xlsx)"),
    )

    state = _minimal_state(home)
    tab = _ProsireniPhase2Tab(state)
    try:
        tab._import_files()

        assert len(import_calls) == 1, "import_file was not called"
        src_arg, election_arg, dir_arg = import_calls[0]

        assert isinstance(src_arg, Path), f"1st arg must be Path, got {type(src_arg)}"
        assert isinstance(election_arg, ElectionConfig), (
            f"2nd arg must be ElectionConfig, got {type(election_arg)}: {election_arg!r}\n"
            "(was popunjeni_dir passed as election?)"
        )
        assert isinstance(dir_arg, Path), f"3rd arg must be Path, got {type(dir_arg)}"
        assert "popunjeni" in str(dir_arg).lower()

        assert not tab.banner.isHidden(), "Success banner must be visible"
    finally:
        tab.deleteLater()


def test_phase2_import_files_shows_warning_on_rejection(app, home, monkeypatch) -> None:
    """_import_files shows a warning banner when import_file rejects a file."""
    from pathlib import Path
    from biracki_odbor.core.popunjeni_io import ImportOutcome
    from biracki_odbor.core.models import Issue
    from biracki_odbor.validation.reports import Codes
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    rejected_outcome = ImportOutcome(
        source=Path("bad.xlsx"), canonical_path=None,
        party="", status="rejected_identity",
        issue=Issue(
            code=Codes.NO_MARKER,
            message_sr="Фајл не садржи ознаку изборног циклуса.",
            severity="error", file="bad.xlsx",
        ),
    )
    _stub_cache(monkeypatch)
    monkeypatch.setattr(
        "biracki_odbor.core.popunjeni_io.import_file",
        lambda *a, **kw: rejected_outcome,
    )
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        lambda *a, **kw: (["C:/fake/bad.xlsx"], "Excel (*.xlsx)"),
    )
    # QMessageBox.warning is modal and blocks the event loop — stub it out so
    # the test doesn't require a human to click OK.
    dialog_calls: list[str] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.prosireni_workspace.QMessageBox.warning",
        lambda *a, **kw: dialog_calls.append("warning"),
    )

    state = _minimal_state(home)
    tab = _ProsireniPhase2Tab(state)
    try:
        tab._import_files()
        assert not tab.banner.isHidden(), "Warning banner must be visible on rejection"
        assert dialog_calls == ["warning"], "QMessageBox.warning must have been shown"
    finally:
        tab.deleteLater()


# ── Phase 2 — Import end-to-end intent test ──────────────────────────────────


def test_phase2_import_files_end_to_end(app, home, monkeypatch) -> None:
    """Importing a real Phase 1 file via the file picker makes it visible to Phase 2.

    This is the intent test: not "does import_file receive correct arg types"
    but "does clicking Import and picking a file actually result in the person
    appearing in the Phase 2 master output?"

    Flow: Phase1 generate → _import_files GUI button → aggregate_party_files → master contains person.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.core.phase1_generate import generate_entity_files
    from biracki_odbor.core.phase2_aggregate import aggregate_party_files
    from biracki_odbor.core.master_io import read_master
    from biracki_odbor.config.candidacies import CandidaciesRegistry, Entity
    from biracki_odbor.config.election import ElectionConfig, ElectionInfo, ElectionDates
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.core.prosireni_allocation import build_prosireni_allocation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    election_uuid = "e2e-test-uuid-42"
    oik = OikConstants(polling_stations=[PollingStation(bm_number=1, name="БМ 1")])
    entity = Entity(entity_id="sns", name="СНС", entity_type="party", level="local", submission_order=1)
    registry = CandidaciesRegistry(entities=[entity])
    election = ElectionConfig(
        election=ElectionInfo(dates=ElectionDates(date_full="2. јуна 2026. године")),
        candidacies=registry,
        election_uuid=election_uuid,
        party_full_names={"СНС": "Странка X"},
    )

    # Phase 1: generate the entity xlsx into stranke_prosireni/
    stranke_dir = app_paths.stranke_dir_for(PROSIRENI_SPEC)
    result1 = generate_entity_files(
        registry=registry,
        bm_numbers=[1],
        output_dir=stranke_dir,
        oik=oik,
        progress=lambda *a: None,
        election=election,
    )
    assert result1.files_written, "Phase 1 must produce at least one file"
    phase1_file = result1.files_written[0]

    # Simulate the operator clicking "Увези фајлове" and picking that file.
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        lambda *a, **kw: ([str(phase1_file)], "Excel (*.xlsx)"),
    )
    # Guard: if the import is rejected a QMessageBox would block the suite.
    # Stub it out and assert it was never called — a call means the import
    # failed, which is itself a test failure.
    dialog_calls: list[str] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.prosireni_workspace.QMessageBox.warning",
        lambda *a, **kw: dialog_calls.append("warning"),
    )

    state = AppState()
    state._oik = oik
    state._election = election
    tab = _ProsireniPhase2Tab(state)
    try:
        tab._import_files()

        # Phase 2: aggregate — should pick up the imported file from the cache.
        popunjeni_dir = app_paths.popunjeni_dir_for(PROSIRENI_SPEC)
        master_out = app_paths.master_path_for(PROSIRENI_SPEC)
        allocs = build_prosireni_allocation(registry, [1])
        result2 = aggregate_party_files(
            input_dir=popunjeni_dir,
            template_path=None,
            output_path=master_out,
            oik=oik,
            election=election,
            spec=PROSIRENI_SPEC,
            allocations_override=allocs,
        )
        assert not dialog_calls, (
            f"Import was rejected (QMessageBox shown: {dialog_calls}). "
            "Check that generate_entity_files writes the election UUID marker."
        )
        assert result2.files_processed > 0, (
            "Phase 2 processed 0 files — the imported file was not found in the cache. "
            "This means _import_files did not update popunjeni_cache."
        )
        persons = read_master(master_out, spec=PROSIRENI_SPEC)
        assert persons, "Master is empty — the imported data did not reach the output."
    finally:
        tab.deleteLater()


# ── Phase 2 — Отвори збирну табелу ───────────────────────────────────────────


def test_phase2_open_master_does_nothing_when_file_absent(app, home, monkeypatch) -> None:
    """Отвори збирну табелу does not call os.startfile when the master file doesn't exist."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    startfile_calls: list = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.prosireni_workspace.os.startfile",
        lambda *a, **kw: startfile_calls.append(a), raising=False,
    )

    state = AppState()
    tab = _ProsireniPhase2Tab(state)
    try:
        tab._open_master()
        assert startfile_calls == [], "os.startfile must not be called when the master file is absent"
    finally:
        tab.deleteLater()


def test_phase2_open_master_opens_file_when_present(app, home, monkeypatch) -> None:
    """Отвори збирну табелу opens the exported copy via os.startfile (no
    shell involved) when it exists."""
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    startfile_calls: list = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.prosireni_workspace.os.startfile",
        lambda *a, **kw: startfile_calls.append(a), raising=False,
    )

    state = AppState()
    tab = _ProsireniPhase2Tab(state)
    try:
        # _open_master() opens the exported .xlsx by its legacy per-workflow
        # name (PROSIRENI_SPEC.paths.master_filename), not master_path_for()'s
        # name -- that now points at the shared committee.db.
        name = PROSIRENI_SPEC.paths.master_filename
        exported = state.files_dir("Извештаји") / name
        exported.parent.mkdir(parents=True, exist_ok=True)
        exported.write_bytes(b"fake xlsx bytes")

        tab._open_master()

        assert len(startfile_calls) == 1
        assert startfile_calls[0] == (str(exported),)
    finally:
        tab.deleteLater()


# ── Phase 3 — Отвори фасциклу решења ────────────────────────────────────────


def test_phase3_open_folder_calls_explorer_with_export_path(app, home, monkeypatch) -> None:
    """Отвори фасциклу решења opens the user's own export folder, never
    the app's internal resenja_prosireni directory."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    from biracki_odbor.core.workflow import PROSIRENI_SPEC

    popen_calls: list[list] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase3.subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )

    state = AppState()
    tab = Phase3Tab(state, spec=PROSIRENI_SPEC)
    try:
        tab._open_folder()
        assert len(popen_calls) == 1, "subprocess.Popen was not called"
        assert popen_calls[0][0] == "explorer"
        expected = str(state.files_dir("Решења (проширени)"))
        assert popen_calls[0][1] == expected
        assert "resenja_prosireni" not in popen_calls[0][1]
    finally:
        tab.deleteLater()


# ── Phase 1 — re-export guard on unrelated generation_log_changed ────────────


def test_unrelated_phase_completion_does_not_reexport_phase1_files(app, home) -> None:
    """Field report: dropping a filled-in file directly into the exported
    Странке (проширени) folder, then running Phase 2, appeared to "reset"
    it back to blank. Root cause: generation_log_changed fires for EVERY
    workflow/phase (not just this tab's own Phase 1), and _restore_from_log
    (connected to that signal) used to unconditionally re-export whatever
    sits in the app's internal template folder over the operator's export
    folder every time -- including when a totally unrelated phase (Phase 2,
    Phase 3, even the OTHER workflow's Phase 1) completes and touches the
    generation log. This pins the fix: re-export only happens when THIS
    tab's own phase1_last timestamp actually changes."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC

    state = _minimal_state(home)
    # Simulate Phase 1 having already run once (matches app-restart /
    # normal post-generation state) with one real file in the internal
    # template folder, so _restore_from_log finds something to export.
    state.generation_log.record_phase("prosireni", "phase1")
    state.save_generation_log()
    stranke_dir = app_paths.stranke_dir_for(PROSIRENI_SPEC)
    stranke_dir.mkdir(parents=True, exist_ok=True)
    (stranke_dir / "ent1.xlsx").write_bytes(b"fake xlsx")

    export_calls: list[str] = []

    tab = ProsireniPhase1Tab(state)
    try:
        # Construction's own _restore_from_log() call already exported once
        # (startup restore) -- monkeypatch AFTER construction so we isolate
        # exactly the "unrelated phase completes" scenario from here on.
        import types
        tab.state.export_generated = types.MethodType(
            lambda self, purpose, paths: export_calls.append(purpose), tab.state,
        )

        # An unrelated phase (stalni's Phase 2, say) finishes and touches
        # the SAME shared generation log -- this tab's own phase1_last is
        # untouched by this.
        state.generation_log.record_phase("stalni", "phase2")
        state.save_generation_log()

        assert export_calls == [], (
            "an unrelated phase completing must not re-export this tab's "
            "already-exported Phase 1 files"
        )

        # Sanity: a REAL Phase 1 re-run (phase1_last actually changes)
        # must still export. Set the field directly rather than calling
        # record_phase() again -- it quantizes to whole seconds, so two
        # calls within the same fast test run risk landing on the same
        # timestamp and masking exactly the distinction this test exists
        # to prove.
        state.generation_log.workflow("prosireni").phase1_last = "2099-01-01T00:00:00+00:00"
        state.save_generation_log()
        assert export_calls == ["Странке (проширени)"]
    finally:
        tab.deleteLater()


# ── Phase 1 — restart with an unreachable export folder ──────────────


def test_send_and_open_buttons_still_enable_when_export_folder_is_unreachable(
    app, home, monkeypatch,
) -> None:
    """Field report: after restarting the app, "Пошаљи листама" was
    greyed out even though Phase 1 had completed successfully in a
    previous session.

    Root cause: `default_files_dir` was set to a network share
    (`\\\\host\\...`). On every fresh launch, `_restore_from_log()`
    re-exports the already-generated files into that folder (see the
    re-export guard test above for why that's conditional on
    `phase1_last` having moved) -- and `AppState.export_generated()`
    used to let an unreachable destination raise straight out of it,
    despite its own docstring promising "logged, not raised". That
    raise happened *before* the very next lines enable btn_open/btn_send
    for this run, in `_restore_from_log()`, called directly from
    `BasePhase1Tab.__init__` -- so a temporarily-unreachable network
    share at exactly the wrong moment (right as the app starts, before
    a VPN/share reconnects after sleep) left both buttons stuck at
    their constructor default of disabled, with nothing on screen to
    explain why.
    """
    monkeypatch.setattr(
        "biracki_odbor.integrations.email_client.any_available", lambda: True,
    )
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab

    state = _minimal_state(home)
    # An export folder that cannot be reached -- stands in for a dropped
    # network share without needing a real one.
    state.app_settings.default_files_dir = r"Z:\not_a_mapped_drive\export"

    # Simulate "Phase 1 already completed in a previous session": a real
    # file sits in the app's internal folder, and phase1_last is already
    # recorded in the generation log -- exactly what a fresh process sees
    # on restart, before this tab has ever been constructed once.
    state.generation_log.record_phase("prosireni", "phase1")
    state.save_generation_log()
    stranke_dir = app_paths.stranke_dir_for(PROSIRENI_SPEC)
    stranke_dir.mkdir(parents=True, exist_ok=True)
    (stranke_dir / "sns.xlsx").write_bytes(b"fake xlsx")

    # This construction is what a restart does -- BasePhase1Tab.__init__
    # calls _restore_from_log() directly, which is where the old bug hit.
    tab = ProsireniPhase1Tab(state)
    try:
        assert tab.btn_open.isEnabled(), (
            "Отвори фасциклу must not be disabled by an unreachable export folder"
        )
        # isHidden(), not isVisible(): the tab is never shown in this
        # test, and isVisible() requires the whole ancestor chain to be
        # on screen -- isHidden() reflects the widget's own explicit
        # flag, which is what setVisible() in __init__ actually set.
        assert not tab.btn_send.isHidden()
        assert tab.btn_send.isEnabled(), (
            "Пошаљи листама must still enable for a completed run even when "
            "the operator's export folder cannot currently be reached"
        )
    finally:
        tab.deleteLater()
