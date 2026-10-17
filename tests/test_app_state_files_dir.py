"""Tests for AppState.files_dir() — the default export/import folder helper."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(h))
    return h


def _make_state():
    from biracki_odbor.gui.app_state import AppState
    return AppState()


def test_files_dir_defaults_to_documents_when_unset(home, monkeypatch) -> None:
    fake_home = Path(str(home)) / "os_home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    state = _make_state()
    assert state.app_settings.default_files_dir == ""

    result = state.files_dir("Групе")

    assert result == fake_home / "Documents" / "Групе"
    assert result.is_dir()


def test_files_dir_uses_configured_base(home) -> None:
    state = _make_state()
    base = Path(str(home)) / "custom_base"
    state.app_settings.default_files_dir = str(base)

    result = state.files_dir("Расподела")

    assert result == base / "Расподела"
    assert result.is_dir()


def test_files_dir_creates_distinct_subfolders_per_purpose(home) -> None:
    state = _make_state()
    base = Path(str(home)) / "custom_base"
    state.app_settings.default_files_dir = str(base)

    groups = state.files_dir("Групе")
    lists = state.files_dir("Листе")

    assert groups != lists
    assert groups.parent == lists.parent == base


def test_files_dir_falls_back_to_documents_when_configured_base_is_unreachable(
    home, monkeypatch,
) -> None:
    """Over 40 call sites across the GUI treat this as a function that
    always returns a real directory -- Qt file dialogs pass it straight
    through as their default path. It used to raise instead, the moment
    a configured network share was unreachable (reported from the
    field), and since every one of those 40+ call sites is invoked from
    a `clicked` slot with no exception handling of its own, that raise
    was invisible each time: Qt swallows it and the operator just saw
    nothing happen for whichever button they pressed."""
    fake_home = Path(str(home)) / "os_home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    state = _make_state()
    state.app_settings.default_files_dir = r"Z:\not_a_mapped_drive\export"

    result = state.files_dir("Групе")  # must not raise

    assert result == fake_home / "Documents" / "Групе"
    assert result.is_dir()


def test_files_dir_logs_the_fallback(home, monkeypatch, caplog) -> None:
    """Silent is the wrong failure mode here -- a file landing in
    Documents instead of the configured share, unremarked, is its own
    kind of confusing. The warning is what makes it traceable from
    app.log."""
    import logging

    fake_home = Path(str(home)) / "os_home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    state = _make_state()
    state.app_settings.default_files_dir = r"Z:\not_a_mapped_drive\export"

    with caplog.at_level(logging.WARNING):
        state.files_dir("Групе")

    assert any("files_dir" in r.message for r in caplog.records)


def test_files_dir_still_raises_when_even_documents_is_unreachable(home, monkeypatch) -> None:
    """The fallback has to bottom out somewhere -- if Documents itself
    can't be created either, that's a genuinely different, worse problem
    than "the configured share is down", and swallowing it too would
    just mean every single file operation in the app silently does
    nothing with no path left to investigate."""
    state = _make_state()  # constructed before mkdir is patched
    assert state.app_settings.default_files_dir == ""

    def _boom(self, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", _boom)

    with pytest.raises(OSError):
        state.files_dir("Групе")
