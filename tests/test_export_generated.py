"""Tests for `AppState.export_generated()` and the "never point the
operator into app-internal storage" pattern it backs — every feature
that generates take-away files copies them into the operator's own
`files_dir(purpose)` right after generation, and "Open folder…"
buttons point there instead of the internal `app_paths` directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


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


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    state.app_settings.default_files_dir = str(tmp_path / "export_base")
    return state


# ── AppState.export_generated ──────────────────────────────────────────


def test_export_generated_copies_files_into_purpose_folder(home, tmp_path) -> None:
    state = _make_state(tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "a.docx"
    f1.write_text("A")
    f2 = src_dir / "b.docx"
    f2.write_text("B")

    copied = state.export_generated("Решења", [f1, f2])

    dest_dir = Path(state.app_settings.default_files_dir) / "Решења"
    assert copied == [dest_dir / "a.docx", dest_dir / "b.docx"]
    assert (dest_dir / "a.docx").read_text() == "A"
    assert (dest_dir / "b.docx").read_text() == "B"


def test_export_generated_overwrites_same_named_file(home, tmp_path) -> None:
    state = _make_state(tmp_path)
    src = tmp_path / "src.docx"
    src.write_text("v1")
    state.export_generated("Решења", [src])
    src.write_text("v2")

    state.export_generated("Решења", [src])

    dest = Path(state.app_settings.default_files_dir) / "Решења" / "src.docx"
    assert dest.read_text() == "v2"


def test_export_generated_best_effort_on_copy_failure(home, tmp_path, monkeypatch) -> None:
    """A copy failure (e.g. destination locked by Excel) must be
    logged, not raised — must never mask the caller's own success."""
    state = _make_state(tmp_path)
    src = tmp_path / "src.docx"
    src.write_text("v1")

    def _boom(*a, **kw):
        raise OSError("locked")

    monkeypatch.setattr("biracki_odbor.gui.app_state.shutil.copy2", _boom)

    copied = state.export_generated("Решења", [src])  # must not raise
    assert copied == []


def test_export_generated_best_effort_when_destination_folder_unreachable(
    home, tmp_path, monkeypatch,
) -> None:
    """The other half of "best-effort" that the docstring promised but
    didn't deliver: `files_dir(purpose)`'s own `mkdir()` sits outside the
    try/except, so a `default_files_dir` that can't currently be reached
    (a dropped network share, an unplugged removable drive) raised
    straight out of this "never raises" function -- reported from the
    field with `default_files_dir` set to a UNC path.

    That matters beyond a failed copy: callers like phase1.py's
    `_restore_from_log()` call this and then, on the very next lines,
    enable the Пошаљи/Отвори buttons for the run that just finished. An
    uncaught raise here skipped those lines, leaving the button stuck at
    whatever its constructor set (disabled) -- see
    test_prosireni_workspace_buttons.py for the end-to-end regression.
    """
    state = _make_state(tmp_path)
    src = tmp_path / "src.docx"
    src.write_text("v1")

    def _boom(*a, **kw):
        raise OSError("[WinError 53] The network path was not found")

    monkeypatch.setattr("biracki_odbor.gui.app_state.Path.mkdir", _boom)

    copied = state.export_generated("Решења", [src])  # must not raise

    assert copied == []


def test_export_generated_default_falls_back_to_documents_when_unset(home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.gui.app_state import AppState
    fake_home = tmp_path / "os_home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    state = AppState()
    assert state.app_settings.default_files_dir == ""
    src = tmp_path / "src.docx"
    src.write_text("v1")

    state.export_generated("Решења", [src])

    assert (fake_home / "Documents" / "Решења" / "src.docx").read_text() == "v1"


# ── Feature wiring: buttons point at files_dir(purpose), not app_paths ──


def test_phase1_stalni_open_folder_uses_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab

    popen_calls: list[list] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase1.subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )
    state = _make_state(tmp_path)
    tab = Phase1Tab(state)
    try:
        tab._open_folder()  # noqa: SLF001
        assert popen_calls[0][0] == "explorer"
        assert popen_calls[0][1] == str(state.files_dir("Странке"))
    finally:
        tab.deleteLater()


def test_izmene_open_folder_uses_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.core.workflow import STALNI_SPEC
    from biracki_odbor.gui.tabs.izmene import IzmenaPanel

    popen_calls: list[list] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.izmene.subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )
    state = _make_state(tmp_path)
    panel = IzmenaPanel(STALNI_SPEC, state, lambda jmbg: None)
    try:
        panel._open_folder()  # noqa: SLF001
        assert popen_calls[0][0] == "explorer"
        assert popen_calls[0][1] == str(state.files_dir("Измене"))
    finally:
        panel.deleteLater()


def test_phase3_open_folder_uses_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    popen_calls: list[list] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase3.subprocess.Popen",
        lambda cmd, **kw: popen_calls.append(list(cmd)),
    )
    state = _make_state(tmp_path)
    tab = Phase3Tab(state)
    try:
        tab._open_folder()  # noqa: SLF001
        assert popen_calls[0][0] == "explorer"
        assert popen_calls[0][1] == str(state.files_dir("Решења"))
    finally:
        tab.deleteLater()


def test_settings_oik_open_logs_uses_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    state = _make_state(tmp_path)
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    log_dir = app_paths.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "app.log").write_text("log line")

    startfile_calls: list[str] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.settings_oik.os.startfile",
        lambda p: startfile_calls.append(p), raising=False,
    )
    monkeypatch.setattr("biracki_odbor.gui.tabs.settings_oik.os.name", "nt")

    tab = OikSettingsTab(state)
    try:
        tab._open_logs()  # noqa: SLF001

        expected_dir = state.files_dir("Логови")
        assert startfile_calls == [str(expected_dir)]
        assert (expected_dir / "app.log").read_text() == "log line"
    finally:
        tab.deleteLater()


def test_corrections_audit_export_copies_and_opens_export_folder(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = _make_state(tmp_path)
    tab = CorrectionsTab(state)
    try:
        tab._persons = [Person(
            bm_number=1, function="Председник", party="СНС",
            first_name="Ана", last_name="Анић", jmbg="1605991774818",
        )]

        startfile_calls: list[str] = []
        monkeypatch.setattr(
            "os.startfile", lambda p: startfile_calls.append(p), raising=False,
        )
        monkeypatch.setattr("os.name", "nt")
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            "biracki_odbor.gui.tabs.corrections.QMessageBox.question",
            lambda *a, **kw: QMessageBox.Yes,
        )

        tab._on_generate_audit()  # noqa: SLF001

        export_dir = state.files_dir("Ревизија")
        assert startfile_calls == [str(export_dir)]
        assert any(export_dir.iterdir()), "audit documents must be copied into the export folder"
    finally:
        tab.deleteLater()


def test_phase2_popunjeni_open_folder_button_removed(app, home, tmp_path) -> None:
    """The intake-folder button was removed outright — there's nothing
    to export from popunjeni/, and adding files is file-picker driven."""
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    state = _make_state(tmp_path)
    tab = Phase2Tab(state)
    try:
        assert not hasattr(tab, "btn_open_popunjeni")
    finally:
        tab.deleteLater()


# ── Feature wiring: import dialogs open at files_dir(purpose) ────────


def test_phase2_import_dialog_opens_at_export_path(app, home, tmp_path, monkeypatch) -> None:
    """Regression: 'Прими' used to default to Path.home() instead of the
    configured folder (field report: "uvezi fajlove should default to
    what was set as default folder")."""
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.phase2.QFileDialog.getOpenFileNames",
        lambda *a, **kw: dialog_calls.append(a) or ([], ""),
    )
    state = _make_state(tmp_path)
    tab = Phase2Tab(state)
    try:
        tab._on_import()  # noqa: SLF001
        assert dialog_calls, "dialog was not opened"
        assert dialog_calls[0][2] == str(state.files_dir("Странке"))
    finally:
        tab.deleteLater()


def test_prosireni_import_dialog_opens_at_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor.gui.tabs.prosireni_workspace import _ProsireniPhase2Tab

    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileNames",
        lambda *a, **kw: dialog_calls.append(a) or ([], ""),
    )
    state = _make_state(tmp_path)
    tab = _ProsireniPhase2Tab(state)
    try:
        tab._import_files()  # noqa: SLF001
        assert dialog_calls, "dialog was not opened"
        assert dialog_calls[0][2] == str(state.files_dir("Странке (проширени)"))
    finally:
        tab.deleteLater()


def test_nacelnik_import_dialog_opens_at_export_path(app, home, tmp_path, monkeypatch) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.master_io import write_master
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab

    state = _make_state(tmp_path)
    master_path = app_paths.master_path()
    master_path.parent.mkdir(parents=True, exist_ok=True)
    write_master(
        [Person(bm_number=1, function="Председник", party="СНС")],
        OikConstants(), master_path,
    )

    dialog_calls: list[tuple] = []
    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.corrections.QFileDialog.getOpenFileName",
        lambda *a, **kw: dialog_calls.append(a) or ("", ""),
    )
    tab = CorrectionsTab(state)
    try:
        assert tab.corrections is not None, "sanity: master.xlsx must have loaded"
        tab.members_panel._on_nacelnik_import()  # noqa: SLF001
        assert dialog_calls, "dialog was not opened"
        assert dialog_calls[0][2] == str(state.files_dir("Начелник"))
    finally:
        tab.deleteLater()


# ── Feature wiring: generation triggers auto-export ──────────────────


def test_posmatraci_on_master_done_exports_file(app, home, tmp_path) -> None:
    from biracki_odbor.gui.tabs.posmatraci_workspace import _DocumentiTab

    state = _make_state(tmp_path)
    tab = _DocumentiTab(state)
    try:
        out = tmp_path / "generated" / "master_posmatraci.xlsx"
        out.parent.mkdir(parents=True)
        out.write_text("content")

        tab._on_master_done(out)  # noqa: SLF001

        dest = Path(state.app_settings.default_files_dir) / "Посматрачи документи" / "master_posmatraci.xlsx"
        assert dest.read_text() == "content"
    finally:
        tab.deleteLater()


def test_posmatraci_on_bm_done_exports_files(app, home, tmp_path) -> None:
    from biracki_odbor.gui.tabs.posmatraci_workspace import _DocumentiTab

    state = _make_state(tmp_path)
    tab = _DocumentiTab(state)
    try:
        gen_dir = tmp_path / "generated"
        gen_dir.mkdir()
        f1 = gen_dir / "BM_01.docx"
        f1.write_text("x")
        f2 = gen_dir / "BM_02.docx"
        f2.write_text("y")

        tab._on_bm_done([f1, f2])  # noqa: SLF001

        dest_dir = Path(state.app_settings.default_files_dir) / "Посматрачи документи"
        assert (dest_dir / "BM_01.docx").read_text() == "x"
        assert (dest_dir / "BM_02.docx").read_text() == "y"
    finally:
        tab.deleteLater()


def test_posmatraci_on_leg_done_exports_file(app, home, tmp_path) -> None:
    from biracki_odbor.gui.tabs.posmatraci_workspace import _DocumentiTab

    state = _make_state(tmp_path)
    tab = _DocumentiTab(state)
    try:
        out = tmp_path / "generated" / "legitimacije.docx"
        out.parent.mkdir(parents=True)
        out.write_text("cards")

        tab._on_leg_done(out)  # noqa: SLF001

        dest = Path(state.app_settings.default_files_dir) / "Посматрачи документи" / "legitimacije.docx"
        assert dest.read_text() == "cards"
    finally:
        tab.deleteLater()
