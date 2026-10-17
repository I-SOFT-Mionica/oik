"""Regression tests: CorrectionsTab / IzmenaPanel column headers and
labels must say "List" for prosireni, not "Party" -- Person.party holds
a party abbreviation under stalni but a canonical entity_id (a "list")
under prosireni (see core/prosireni_allocation.py). Reusing "Party"
wording unconditionally made prosireni screens look like they were
showing stalni data instead of being properly decoupled.
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


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    from tests.test_phase1 import _make_oik
    from tests.test_phase3 import _make_election

    state = AppState()
    state._oik = _make_oik(2)  # noqa: SLF001
    state._election = _make_election()  # noqa: SLF001
    return state


def _header_labels(table) -> list[str]:
    return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]


def test_members_panel_says_party_for_stalni(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = _make_state(tmp_path)
    tab = CorrectionsTab(state)
    try:
        assert "Party" in _header_labels(tab.members_panel.table)
        assert "List" not in _header_labels(tab.members_panel.table)
    finally:
        tab.deleteLater()


def test_members_panel_says_list_for_prosireni(app, tmp_path) -> None:
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = _make_state(tmp_path)
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        assert "List" in _header_labels(tab.members_panel.table)
        assert "Party" not in _header_labels(tab.members_panel.table)
    finally:
        tab.deleteLater()


def test_summary_panel_says_party_for_stalni(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = _make_state(tmp_path)
    tab = CorrectionsTab(state)
    try:
        assert _header_labels(tab.summary_panel.party_table)[0] == "Party"
    finally:
        tab.deleteLater()


def test_summary_panel_says_list_for_prosireni(app, tmp_path) -> None:
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = _make_state(tmp_path)
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        assert _header_labels(tab.summary_panel.party_table)[0] == "List"
    finally:
        tab.deleteLater()


def test_person_edit_dialog_context_label_prosireni(app) -> None:
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        from PySide6.QtWidgets import QLabel
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        assert any("list ent1" in t for t in labels)
        assert not any("party ent1" in t for t in labels)
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_context_label_stalni(app) -> None:
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    person = Person(bm_number=1, function="Председник", party="СНС")
    dlg = _PersonEditDialog(person, mode="edit", spec=None)
    try:
        from PySide6.QtWidgets import QLabel
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        assert any("party СНС" in t for t in labels)
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_rejects_invalid_jmbg(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1234567890123")  # 13 digits, fails MOD 11
        dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_accepts_valid_jmbg(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1503975774819")  # MOD 11 valid (from core/demo_data.py)
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_rejects_letters_in_phone(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1503975774819")
        dlg.ed_telefon.setText("064-abc-1234")
        dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_accepts_phone_with_plus_and_digits(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1503975774819")
        dlg.ed_telefon.setText("+381641234567")
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_rejects_malformed_email(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1503975774819")
        dlg.ed_email.setText("not-an-email")
        dlg._on_accept()
        assert dlg.result() != QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_person_edit_dialog_accepts_empty_phone_and_email(app, monkeypatch) -> None:
    """Phone and email are optional -- blank must not block accept."""
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.core.models import Person
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    person = Person(bm_number=1, function="Члан [1]", party="ent1")
    dlg = _PersonEditDialog(person, mode="edit", spec=PROSIRENI_SPEC)
    try:
        dlg.ed_note.setCurrentText("test note")
        dlg.ed_jmbg.setText("1503975774819")
        dlg._on_accept()
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_izmena_panel_says_list_for_prosireni(app, tmp_path) -> None:
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.izmene import IzmenaPanel
    state = _make_state(tmp_path)
    panel = IzmenaPanel(PROSIRENI_SPEC, state, lambda jmbg: None)
    try:
        assert "List" in _header_labels(panel.table_replacement)
        assert "Party" not in _header_labels(panel.table_replacement)
    finally:
        panel.deleteLater()


def test_izmena_panel_says_party_for_stalni(app, tmp_path) -> None:
    from biracki_odbor.core.workflow import STALNI_SPEC
    from biracki_odbor.gui.tabs.izmene import IzmenaPanel
    state = _make_state(tmp_path)
    panel = IzmenaPanel(STALNI_SPEC, state, lambda jmbg: None)
    try:
        assert "Party" in _header_labels(panel.table_replacement)
        assert "List" not in _header_labels(panel.table_replacement)
    finally:
        panel.deleteLater()


def _correction_event(bm, function, *, before_first, before_last, after_first, after_last):
    from biracki_odbor.core.corrections import AuditEvent
    from biracki_odbor.core.models import Person
    before = Person(
        bm_number=bm, function=function, party="ent1",
        first_name=before_first, last_name=before_last,
    ).to_dict()
    after = Person(
        bm_number=bm, function=function, party="ent1",
        first_name=after_first, last_name=after_last,
    ).to_dict()
    return AuditEvent(
        timestamp="2026-08-01T10:00:00+02:00", operator="test", event_type="edit_member",
        slot_bm=bm, slot_function=function, before=before, after=after,
    )


def test_auto_generate_izmene_uses_prosireni_own_session_date(app, tmp_path) -> None:
    """Field report class: an auto-generated prosireni Решење о изменама
    must cite prosireni's own session_date_prosireni as the original
    decision date, not stalni's session_date -- прошиpени decisions are
    adopted at a separate OIK session with its own date/number."""
    from docx import Document
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = _make_state(tmp_path)
    state.election.election.dates.session_date = "1. јануара 2020. године"
    state.election.election.dates.session_date_prosireni = "20. децембра 2026. године"
    tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
    try:
        ev = _correction_event(
            1, "Члан [1]",
            before_first="Никола", before_last="Марковић",
            after_first="Славко", after_last="Максимовић",
        )
        paths = tab._auto_generate_izmene("prosireni", [ev])  # noqa: SLF001
        assert paths, "expected at least one generated izmena document"
        doc = Document(paths[0])
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "20. децембра 2026. године" in all_text
        assert "1. јануара 2020. године" not in all_text
    finally:
        tab.deleteLater()
