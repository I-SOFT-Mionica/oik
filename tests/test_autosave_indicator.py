"""Tests for §6 — autosave indicator.

`AppState.last_save_at` + `saved` signal drive the status-bar
autosave label. These tests pin the state machine:

- Fresh AppState has `last_save_at == None` (status label stays blank).
- Every save_* path updates last_save_at AND emits `saved`.
- The relative-time formatter in MainWindow buckets sensibly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


def test_fresh_app_state_has_no_last_save(tmp_path: Path, monkeypatch) -> None:
    """No save has happened yet → indicator must stay blank.

    A fresh first-launch app on a clean HOME shouldn't claim
    "Аутосачувано пре 0 мин" — that would be a lie that erodes
    operator trust in the indicator.
    """
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    assert state.last_save_at is None


def test_save_oik_marks_saved_and_emits(tmp_path: Path, monkeypatch) -> None:
    """Every persisted save method updates last_save_at AND fires the
    `saved` signal so the status bar refreshes immediately."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    received: list[int] = []
    state.saved.connect(lambda: received.append(1))
    before = datetime.now()
    state.save_oik()
    after = datetime.now()
    assert state.last_save_at is not None
    assert before <= state.last_save_at <= after
    assert received == [1]


def test_save_election_updates_timestamp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    state.save_election()
    assert state.last_save_at is not None


def test_set_template_path_marks_saved(tmp_path: Path, monkeypatch) -> None:
    """`set_template_path` writes OIK directly (not via save_oik); it
    must still update last_save_at so the Шаблон workflow doesn't
    silently bypass the indicator."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    template = tmp_path / "fake.xlsx"
    template.write_bytes(b"PK\x03\x04")
    state.set_template_path(template)
    assert state.last_save_at is not None


def test_save_app_settings_marks_saved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    state.save_app_settings()
    assert state.last_save_at is not None


# ── Relative-time formatter (MainWindow._refresh_save_label) ────────


def _label_for(seconds_ago: int) -> str:
    """Run MainWindow._refresh_save_label against a contrived
    last_save_at and return the rendered status-bar text."""
    from PySide6.QtWidgets import QApplication
    from biracki_odbor import _release_info
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.main_window import MainWindow
    from biracki_odbor.gui.style import apply_global_style

    # Block updater from launching a network thread we'd then leak.
    with patch.object(_release_info, "GITHUB_REPO", ""):
        app = QApplication.instance() or QApplication([])
        apply_global_style(app)
        w = MainWindow()
        try:
            w.state._last_save_at = datetime.now() - timedelta(seconds=seconds_ago)
            w._refresh_save_label()
            return w._save_label.text()
        finally:
            w.deleteLater()


@pytest.mark.parametrize("secs,expected_substring", [
    (5, "just now"),     # < 60 s
    (90, "1 min"),       # 1-59 mins → "N min ago"
    (1800, "30 min"),    # 30 mins
    (3600, "1 h"),       # exactly 1 hour
    (7200, "2 h"),       # 2 hours
])
def test_relative_time_buckets(tmp_path: Path, monkeypatch, secs, expected_substring) -> None:
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    text = _label_for(secs)
    assert expected_substring in text, (
        f"Expected '{expected_substring}' in label '{text}' for {secs}s ago"
    )


def test_label_empty_when_no_save_yet(tmp_path: Path, monkeypatch) -> None:
    """Fresh launch with no save: status-bar label is blank."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    from biracki_odbor import _release_info
    from biracki_odbor.gui.main_window import MainWindow
    from biracki_odbor.gui.style import apply_global_style

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    app = QApplication.instance() or QApplication([])
    apply_global_style(app)
    w = MainWindow()
    try:
        # last_save_at starts as None; the constructor already called
        # _refresh_save_label once. Confirm the label is empty.
        assert w._save_label.text() == ""
    finally:
        w.deleteLater()
