"""Guided tour (TODO §33): each step reveals its control, leaves a
click-through hole over it while blocking the rest of the window, and
advances when the app reports the step done."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import _release_info
    from biracki_odbor.gui.main_window import MainWindow
    from biracki_odbor.gui.style import apply_global_style
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    monkeypatch.setattr(MainWindow, "_open_setup_wizard", lambda self: None)
    apply_global_style(QApplication.instance())
    w = MainWindow()
    w.state.app_settings.disable_tab_gating = True
    w._refresh_tab_states()
    w.resize(1400, 900)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def _assert_spotlit(w, target) -> None:
    ov = w._tour.overlay
    QApplication.processEvents()
    centre = target.mapTo(w, target.rect().center())
    assert target.isVisible()
    assert ov.hole.contains(centre)
    assert not ov.mask().contains(centre)          # clicks reach the target
    assert ov.mask().contains(QPoint(3, 3))         # ...and nothing else


def test_first_step_spotlights_rik_import_and_advances(window) -> None:
    from biracki_odbor.core.models import PollingStation
    w = window
    w.start_tour()
    assert w.stack.currentWidget() is w.izborna_page
    _assert_spotlit(w, w.izborna_page.btn_import_rik)

    w.state.oik.polling_stations = [PollingStation(1, "Школа")]
    w.state.template_changed.emit()
    QTest.qWait(450)
    assert w._tour.i == 1
    assert w.stack.currentWidget() is w.tabs
    phase1 = w.tabs.currentWidget()
    assert type(phase1).__name__ == "Phase1Tab"
    _assert_spotlit(w, phase1.btn_run)


def test_look_only_step_reveals_nested_tab_and_uses_next(window) -> None:
    w = window
    w.start_tour()
    tour = w._tour
    conflicts = next(i for i, s in enumerate(tour.steps) if s.target() is w.corrections_tab.conflicts_panel)
    tour.i = conflicts - 1
    tour._advance()
    assert w.tabs.currentWidget() is w.corrections_tab
    assert w.corrections_tab.inner.currentWidget() is w.corrections_tab.conflicts_panel
    assert tour.overlay.btn_next.isVisibleTo(tour.overlay)
    tour.overlay.next_requested.emit()
    assert tour.i == conflicts + 1


def test_end_tour_removes_the_overlay(window) -> None:
    w = window
    w.start_tour()
    overlay = w._tour.overlay
    overlay.skip_requested.emit()
    QApplication.processEvents()
    assert not overlay.isVisible()
    assert w._tour is None
