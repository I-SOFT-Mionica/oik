"""Измене has the same bottom bar as Решења: decisions folder on the
left, Освежи провере + Покрени on the right."""

from __future__ import annotations

import pytest


@pytest.fixture
def panel(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.core.workflow import STALNI_SPEC
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.izmene import IzmenaPanel
    p = IzmenaPanel(STALNI_SPEC, AppState(), lambda jmbg: None)
    yield p
    p.deleteLater()


def _bar_buttons(panel):
    layout = panel.btn_generate.parentWidget().layout()
    bar = next(layout.itemAt(i).layout() for i in range(layout.count())
               if layout.itemAt(i).layout() is not None)
    return [bar.itemAt(i).widget() for i in range(bar.count()) if bar.itemAt(i).widget()]


def test_bar_matches_the_decisions_tab(panel) -> None:
    assert _bar_buttons(panel) == [panel.btn_open_out, panel.btn_refresh, panel.btn_generate]
    assert panel.btn_open_out.text() == "Open decisions folder…"
    assert panel.btn_refresh.text() == "Refresh checks"
    assert panel.btn_generate.text() == "Run"
    assert panel.btn_generate.objectName() == "PrimaryButton"


def test_refresh_rereads_changes_lock_state_and_preview(panel, monkeypatch) -> None:
    calls = []
    for name in ("_refresh_lock_state", "_refresh_changes_table", "_refresh_preview"):
        monkeypatch.setattr(panel, name, lambda n=name: calls.append(n))
    panel.btn_refresh.click()
    assert sorted(calls) == ["_refresh_changes_table", "_refresh_lock_state", "_refresh_preview"]

