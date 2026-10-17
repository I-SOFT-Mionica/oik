"""Phase3Tab's "Reset to default" (образложење) button.

Regression: after the JSON-backed obrazlozenje refactor removed the
module-level `_SEED_PARAGRAPHS` literal (seed text now comes from
bundled JSON resources, picked per-workflow by filename), this button
still referenced that removed attribute — crashing with AttributeError
on every click, for both стални and прошиени, wiping the card list to
empty without repopulating it (the crash happened mid-loop, before any
new cards were appended or the file was saved).
"""

from __future__ import annotations

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


def _make_tab(app, spec):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    state = AppState()
    return Phase3Tab(state, spec=spec)


def test_reset_to_default_restores_stalni_paragraphs(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox
    from biracki_odbor.core.workflow import STALNI_SPEC

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    tab = _make_tab(app, STALNI_SPEC)
    try:
        tab._on_reset_to_seed()  # noqa: SLF001
        ids = [c.paragraph_id for c in tab._cards()]  # noqa: SLF001
        assert ids
        assert "sastav-stalnog-odbora" in ids
    finally:
        tab.deleteLater()


def test_reset_to_default_restores_prosireni_paragraphs_not_stalni(app, monkeypatch) -> None:
    """The bug: this always applied стални's seed regardless of which
    workflow the tab was for. Прошиени must get its OWN default text —
    distinct article citations, distinct paragraph ids."""
    from PySide6.QtWidgets import QMessageBox
    from biracki_odbor.core.workflow import PROSIRENI_SPEC

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    tab = _make_tab(app, PROSIRENI_SPEC)
    try:
        tab._on_reset_to_seed()  # noqa: SLF001
        ids = [c.paragraph_id for c in tab._cards()]  # noqa: SLF001
        assert ids
        assert "pravo-predlaganja-prosireni" in ids
        assert "sastav-stalnog-odbora" not in ids
    finally:
        tab.deleteLater()
