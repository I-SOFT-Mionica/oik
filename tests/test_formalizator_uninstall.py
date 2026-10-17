"""Tests for formalizator.installer.uninstall — the destructive half of
the setup tooling, kept free of Qt so it can be exercised headlessly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formalizator.core import starter_catalog
from formalizator.installer import scaffold, uninstall


@pytest.fixture(autouse=True)
def _no_real_registry_writes(monkeypatch):
    """Keep scaffolding out of the developer's actual registry.

    perform_scaffold registers an Add/Remove Programs entry via HKCU.
    Run from a test that points it at a pytest tmp_path, that leaves a
    real uninstall entry on the machine aimed at a folder which is then
    deleted -- and OIK's Formalizator tab, which probes exactly that key
    to decide whether Formalizator is installed, then believes it is.
    Found while building that tab, from a key a previous run had left
    behind.
    """
    from formalizator.installer import scaffold as _scaffold
    monkeypatch.setattr(_scaffold, "_register_in_windows_apps", lambda *_a, **_kw: None)
    from biracki_odbor.installer import scaffold as _oik_scaffold
    monkeypatch.setattr(_oik_scaffold, "_register_in_windows_apps", lambda *_a, **_kw: None)
    # The *removal* side is the more damaging half: perform_uninstall
    # deletes HKCU\...\Uninstall\Formalizator unconditionally, and the
    # key it deletes is the real one. On a developer machine that has
    # Formalizator genuinely installed, running the test suite silently
    # removed its Add/Remove Programs entry — observed, not theoretical.
    monkeypatch.setattr(uninstall, "unregister_from_windows_apps", lambda *_a, **_kw: None)


def _fake_starter_root(tmp_path: Path, monkeypatch) -> Path:
    """A synthetic `resources/starter/` — these tests need *something*
    seeded to verify it survives/is removed correctly, independent of
    whatever real forms happen to be bundled (there may be none at all
    between election cycles, by design)."""
    root = tmp_path / "fake_starter"
    root.mkdir()
    (root / "form.pdf").write_bytes(b"%PDF-1.4 fake")
    (root / "export.xlsx").write_bytes(b"fake xlsx")
    (root / "catalog.json").write_text(json.dumps([{
        "name": "Тест образац", "background_pdf_path": "form.pdf",
        "positions": [{"field_key": "full_name", "page_index": 0, "x": 1.0, "y": 1.0}],
    }]), encoding="utf-8")
    (root / "export_templates.json").write_text(json.dumps([{
        "name": "Тест образац — извоз", "source_file": "export.xlsx", "columns": [],
    }]), encoding="utf-8")
    monkeypatch.setattr(starter_catalog, "_starter_root", lambda: root)
    return root


@pytest.fixture
def install(tmp_path: Path, monkeypatch) -> Path:
    """A realistic install: both executables, the icon, the seeded
    starter forms, and a session database."""
    _fake_starter_root(tmp_path, monkeypatch)
    base = tmp_path / "Formalizator"
    app_exe = tmp_path / "src_app.exe"
    app_exe.write_bytes(b"MZ app")
    uninstaller_exe = tmp_path / "src_uninstaller.exe"
    uninstaller_exe.write_bytes(b"MZ uninstaller")

    scaffold.perform_scaffold(base, exe_source=app_exe, uninstaller_source=uninstaller_exe)
    (base / "formalizator.db").write_bytes(b"sqlite")
    return base


def test_program_files_are_removed(install: Path) -> None:
    uninstall.remove_program_files(install)

    assert not (install / scaffold.APP_EXE_NAME).exists()
    assert not (install / "icon.ico").exists()


def test_program_removal_leaves_operator_data_alone(install: Path) -> None:
    """Uninstalling the program must not quietly take a calibrated
    template with it — that is hand-tuned work that cannot be redone
    from anything left on disk."""
    uninstall.remove_program_files(install)

    assert (install / "templates" / "catalog.json").exists()
    assert (install / "export_templates.json").exists()
    assert (install / "formalizator.db").exists()


def test_preview_cleanup_removes_the_sessions_rendered_declarations(tmp_path, monkeypatch) -> None:
    """The app clears its own preview folder on exit, so the data does
    not sit in temp between runs waiting for an uninstall that may
    never happen."""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from formalizator.gui.fillout_screen import FilloutScreen

    screen = FilloutScreen()
    try:
        preview_dir = screen._preview_dir  # noqa: SLF001
        (preview_dir / "declaration_2308985774805.pdf").write_bytes(b"%PDF personal data")
        assert preview_dir.exists()

        screen.cleanup_previews()

        assert not preview_dir.exists()
    finally:
        screen.deleteLater()


def test_user_data_removal_clears_templates_and_database(install: Path) -> None:
    uninstall.remove_user_data(install)

    assert not (install / "templates").exists()
    assert not (install / "export_sources").exists()
    assert not (install / "export_templates.json").exists()
    assert not (install / "formalizator.db").exists()


def test_uninstall_removes_everything(install: Path) -> None:
    """No "keep my data" path exists on purpose: the app holds names,
    JMBGs and home addresses, so a decommissioned machine must not be
    left holding any of it."""
    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert result.removed_files
    assert result.base_removed is True
    assert not install.exists()


def test_uninstall_leaves_unknown_files_and_their_folder_behind(install: Path) -> None:
    """Anything the operator put in the folder themselves is not ours
    to delete, and its presence keeps the folder alive."""
    stray = install / "моје белешке.txt"
    stray.write_text("важно", encoding="utf-8")

    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert stray.exists()
    assert result.base_removed is False
    # ...but our own data is gone regardless.
    assert not (install / "templates").exists()
    assert not (install / "formalizator.db").exists()


def test_uninstall_is_safe_to_run_twice(install: Path, monkeypatch, tmp_path: Path) -> None:
    # Isolated temp dir: this asserts no errors, but perform_uninstall
    # sweeps the *real* system temp for preview folders, where an
    # unrelated leftover held open by another process (a PDF viewer,
    # an indexer) shows up as an error that has nothing to do with
    # what's being tested. Hit that twice for real before isolating it.
    isolated_temp = tmp_path / "systemp"
    isolated_temp.mkdir()
    monkeypatch.setattr(uninstall.tempfile, "gettempdir", lambda: str(isolated_temp))

    uninstall.perform_uninstall(install, remove_shortcut=False)

    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert result.removed_files == []
    assert result.errors == []


def test_uninstall_clears_temp_preview_folders(install: Path, monkeypatch, tmp_path: Path) -> None:
    """The worst leftovers: filled PDF declarations in the system temp
    directory, with the voter's JMBG in the file name."""
    fake_temp = tmp_path / "temp"
    fake_temp.mkdir()
    monkeypatch.setattr(uninstall.tempfile, "gettempdir", lambda: str(fake_temp))
    for name in ("formalizator_preview_abc", "celik_preview_xyz"):
        folder = fake_temp / name
        folder.mkdir()
        (folder / "declaration_2308985774805.pdf").write_bytes(b"%PDF personal data")
    unrelated = fake_temp / "something_else"
    unrelated.mkdir()

    uninstall.perform_uninstall(install, remove_shortcut=False)

    assert not (fake_temp / "formalizator_preview_abc").exists()
    assert not (fake_temp / "celik_preview_xyz").exists()  # pre-rename ones too
    assert unrelated.exists()  # nothing else in temp is ours to touch


def test_uninstall_also_clears_the_working_directory_elsewhere(
    install: Path, monkeypatch, tmp_path: Path,
) -> None:
    """Installing to a custom folder still leaves the session database
    under the home working directory — that has to go too."""
    fake_home = tmp_path / "home"
    (fake_home / "Formalizator" / "templates").mkdir(parents=True)
    (fake_home / "Formalizator" / "formalizator.db").write_bytes(b"sqlite")
    monkeypatch.setattr(uninstall.Path, "home", staticmethod(lambda: fake_home))

    uninstall.perform_uninstall(install, remove_shortcut=False)

    assert not (fake_home / "Formalizator" / "formalizator.db").exists()


def test_uninstall_also_clears_the_pre_rename_working_directory(
    install: Path, monkeypatch, tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    (fake_home / "Celik").mkdir(parents=True)
    (fake_home / "Celik" / "formalizator.db").write_bytes(b"sqlite")
    monkeypatch.setattr(uninstall.Path, "home", staticmethod(lambda: fake_home))

    uninstall.perform_uninstall(install, remove_shortcut=False)

    assert not (fake_home / "Celik" / "formalizator.db").exists()


def _pretend_frozen_uninstaller(monkeypatch, install: Path) -> Path:
    """Stand in for the packaged uninstaller running out of the install
    folder — the only situation in which the self-deletion path is
    reached, and the one the unit tests otherwise never enter because
    from source `sys.executable` is the interpreter."""
    exe = install / scaffold.UNINSTALLER_EXE_NAME
    monkeypatch.setattr(uninstall.sys, "frozen", True, raising=False)
    monkeypatch.setattr(uninstall.sys, "executable", str(exe))
    return exe


def _isolate_temp(monkeypatch, tmp_path: Path) -> Path:
    """perform_uninstall sweeps the *real* system temp for preview
    folders, where an unrelated leftover held open by another process
    shows up as an error that has nothing to do with the test."""
    isolated = tmp_path / "systemp"
    isolated.mkdir(exist_ok=True)
    monkeypatch.setattr(uninstall.tempfile, "gettempdir", lambda: str(isolated))
    return isolated


def test_the_running_uninstaller_is_not_reported_as_a_failure(
    install: Path, monkeypatch, tmp_path: Path,
) -> None:
    """Windows holds an open handle on a running image, so the
    uninstaller cannot delete itself from inside itself. Surfacing that
    as an error is what made a clean uninstall look broken to the
    operator."""
    _isolate_temp(monkeypatch, tmp_path)
    exe = _pretend_frozen_uninstaller(monkeypatch, install)
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda *a, **k: None)

    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert result.errors == []
    assert exe.exists()  # still there — deletion is deferred, not skipped
    assert not (install / "formalizator.db").exists()  # everything else is gone


def test_the_uninstaller_schedules_its_own_removal_and_the_folder(install: Path, monkeypatch) -> None:
    exe = _pretend_frozen_uninstaller(monkeypatch, install)
    spawned = []
    monkeypatch.setattr(
        uninstall.subprocess, "Popen",
        lambda args, **kwargs: spawned.append((args, kwargs)),
    )

    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert result.self_delete_scheduled is True
    (args, kwargs), = spawned
    command = args[-1]
    assert str(exe) in command
    assert str(install.resolve()) in command
    # `rmdir` without /s: a folder still holding the operator's own
    # files survives, matching remove_base_if_empty's own rule.
    assert "/s" not in command
    # A process whose CWD is inside the folder would block its removal.
    assert Path(kwargs["cwd"]) != install


def test_nothing_is_scheduled_when_running_from_source(install: Path, monkeypatch) -> None:
    """From source there is no running .exe inside the install folder,
    so the normal path must stay exactly as it was."""
    monkeypatch.setattr(uninstall.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))

    result = uninstall.perform_uninstall(install, remove_shortcut=False)

    assert result.self_delete_scheduled is False
    assert result.base_removed is True


def test_describe_install_counts_calibrated_templates(install: Path) -> None:
    info = uninstall.describe_install(install)

    assert info["exists"] is True
    assert info["has_data"] is True
    assert info["templates"] >= 1  # the bundled starter form


def test_describe_install_on_a_missing_folder(tmp_path: Path) -> None:
    info = uninstall.describe_install(tmp_path / "nope")

    assert info["exists"] is False
    assert info["has_data"] is False
    assert info["templates"] == 0


def test_installer_registers_in_windows_apps_only_with_an_uninstaller(tmp_path: Path) -> None:
    """An Uninstall entry whose button does nothing is worse than no
    entry, so registration waits until the uninstaller is in place."""
    app_exe = tmp_path / "app.exe"
    app_exe.write_bytes(b"MZ")
    base = tmp_path / "no_uninstaller"

    scaffold.perform_scaffold(base, exe_source=app_exe)

    assert not (base / scaffold.UNINSTALLER_EXE_NAME).exists()


def test_uninstalling_does_not_touch_the_real_registry(install: Path, monkeypatch) -> None:
    """A guard on the test suite itself, not on the app.

    perform_uninstall deletes the HKCU uninstall key, and that is the
    real key — there is no tmp_path equivalent for the registry.
    Running the suite on a machine with Formalizator actually installed
    therefore wiped its Add/Remove Programs entry. The autouse fixture
    above stubs it; if that stub is ever removed this fails rather than
    quietly eating someone's uninstall entry again.
    """
    called = []
    monkeypatch.setattr(uninstall, "unregister_from_windows_apps", lambda: called.append(True))

    uninstall.perform_uninstall(install, remove_shortcut=False)

    assert called == [True], "perform_uninstall must still unregister in production"
