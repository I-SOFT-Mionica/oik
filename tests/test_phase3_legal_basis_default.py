"""Phase 3's legal-basis field had no default at all — the operator had
to type the whole "На основу..." citation from scratch every election
cycle. Added a pre-fill (same "saved or default" pattern izmene.py's
_DEFAULT_LEGAL_BASIS already uses), matching the 2026-cycle citation
confirmed against the official RIK-distributed forms under
biracki_odbor/new forms/.
"""

from __future__ import annotations

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


def test_stalni_legal_basis_prefills_the_2026_citation(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    from biracki_odbor.core.workflow import STALNI_SPEC

    state = AppState()
    tab = Phase3Tab(state, spec=STALNI_SPEC)
    try:
        text = tab.ed_legal.toPlainText()
        assert "14/22 и 47/26" in text
        assert "члана 35." in text
        # Initial appointment, not a change -- must NOT cite член 41 or
        # the Упутство (those govern changing an already-appointed
        # member, see izmene.py's own, separate default).
        assert "41" not in text
        assert "Упутств" not in text
    finally:
        tab.deleteLater()


def test_prosireni_legal_basis_prefills_the_2026_citation(app, home) -> None:
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    from biracki_odbor.core.workflow import PROSIRENI_SPEC

    state = AppState()
    tab = Phase3Tab(state, spec=PROSIRENI_SPEC)
    try:
        text = tab.ed_legal.toPlainText()
        assert "14/22 и 47/26" in text
        assert "члана 39. став 1." in text
    finally:
        tab.deleteLater()


def test_legal_basis_default_never_overrides_an_already_saved_value(app, home) -> None:
    """The pre-fill is a default for an EMPTY field, never a value
    forced over whatever the operator already typed and saved."""
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    from biracki_odbor.core.workflow import STALNI_SPEC

    state = AppState()
    state.election.document.legal_basis = "Ручно унет сопствени текст."
    tab = Phase3Tab(state, spec=STALNI_SPEC)
    try:
        assert tab.ed_legal.toPlainText() == "Ручно унет сопствени текст."
    finally:
        tab.deleteLater()
