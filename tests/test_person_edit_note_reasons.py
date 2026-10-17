"""Tests for _PersonEditDialog's Note field: an editable combo box with
preset reasons (чл. 14(1)(8) double appointment, personal-data
correction, death, incapacity) plus free-typed text — and, specific to
the чл. 14(1)(8) reason, two extra fields (BM + municipality of the
OTHER appointment) that get folded into the final note text, since
that reason doesn't explain anything without saying where the person
is now also serving.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_dialog(app):
    from biracki_odbor.core.models import Person
    from biracki_odbor.gui.tabs.corrections import _PersonEditDialog

    person = Person(
        bm_number=1, function="Члан [1]", party="ent1",
        first_name="Петар", last_name="Петровић",
        jmbg="1605991774818", telefon="0641234567", email="",
    )
    return _PersonEditDialog(person, mode="edit", spec=None)


def test_note_combo_offers_presets_and_blank_default(app) -> None:
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CHOICES

    dlg = _make_dialog(app)
    try:
        assert dlg.ed_note.isEditable()
        items = [dlg.ed_note.itemText(i) for i in range(dlg.ed_note.count())]
        assert items[0] == ""
        for reason in NOTE_REASON_CHOICES:
            assert reason in items
        assert dlg.ed_note.currentText() == ""
    finally:
        dlg.deleteLater()


def test_note_combo_accepts_free_typed_text(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText("Сопствени разлог оператера")
        assert dlg.note() == "Сопствени разлог оператера"
    finally:
        dlg.deleteLater()


def test_other_appointment_fields_hidden_by_default(app) -> None:
    dlg = _make_dialog(app)
    try:
        assert not dlg.ed_other_bm.isVisible()
        assert not dlg.ed_other_mun.isVisible()
    finally:
        dlg.deleteLater()


def test_selecting_cl_14_1_8_reveals_other_appointment_fields(app) -> None:
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    dlg = _make_dialog(app)
    dlg.show()  # isVisible() needs a real top-level show; isVisibleTo would also work
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        assert dlg.ed_other_bm.isVisibleTo(dlg)
        assert dlg.ed_other_mun.isVisibleTo(dlg)

        dlg.ed_note.setCurrentText("Смрт")
        assert not dlg.ed_other_bm.isVisibleTo(dlg)
        assert not dlg.ed_other_mun.isVisibleTo(dlg)
    finally:
        dlg.deleteLater()


def test_cl_14_1_8_without_other_appointment_is_rejected(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: warned.append(True))

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        # BM/municipality left blank.
        dlg._on_accept()  # noqa: SLF001
        assert dlg.result() != QDialog.DialogCode.Accepted
        assert warned
    finally:
        dlg.deleteLater()


def test_cl_14_1_8_note_folds_in_bm_and_municipality(app) -> None:
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        dlg.ed_other_bm.setText("5")
        dlg.ed_other_mun.setText("Ваљево")

        text = dlg.note()

        assert text.startswith(NOTE_REASON_CL_14_1_8)
        assert "5" in text
        assert "Ваљево" in text
    finally:
        dlg.deleteLater()


def test_cl_14_1_8_other_bm_and_municipality_as_real_values(app) -> None:
    """Alongside note()'s free-text sentence, other_bm()/other_municipality()
    expose the same facts as real values — these are what get attached
    to the AuditEvent so the Измене tab's Престанак track can detect and
    pre-fill from the log without parsing note()'s sentence back apart."""
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        dlg.ed_other_bm.setText("5")
        dlg.ed_other_mun.setText("Ваљево")

        assert dlg.other_bm() == 5
        assert dlg.other_municipality() == "Ваљево"
    finally:
        dlg.deleteLater()


def test_cl_14_1_8_other_decision_broj_as_real_value(app) -> None:
    """Optional alongside BM/municipality — the operator may not have
    the other municipality's decision number on hand yet when first
    flagging the person, so it's not required to accept the dialog."""
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        dlg.ed_other_bm.setText("5")
        dlg.ed_other_mun.setText("Ваљево")
        dlg.ed_other_broj.setText("013-9-1-4/2026")

        assert dlg.other_decision_broj() == "013-9-1-4/2026"
    finally:
        dlg.deleteLater()


def test_other_bm_is_none_for_non_cl_14_1_8_reasons(app) -> None:
    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText("Смрт")
        dlg.ed_other_bm.setText("5")  # stale/irrelevant leftover value
        dlg.ed_other_mun.setText("Ваљево")

        assert dlg.other_bm() is None
        assert dlg.other_municipality() == ""
    finally:
        dlg.deleteLater()


def test_cl_14_1_8_with_other_appointment_is_accepted(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox
    from biracki_odbor.gui.tabs.corrections import NOTE_REASON_CL_14_1_8

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: pytest.fail("must not warn"))

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText(NOTE_REASON_CL_14_1_8)
        dlg.ed_other_bm.setText("5")
        dlg.ed_other_mun.setText("Ваљево")
        dlg._on_accept()  # noqa: SLF001
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()


def test_non_14_1_8_reason_does_not_require_other_appointment(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: pytest.fail("must not warn"))

    dlg = _make_dialog(app)
    try:
        dlg.ed_note.setCurrentText("Смрт")
        dlg._on_accept()  # noqa: SLF001
        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg.note() == "Смрт"
    finally:
        dlg.deleteLater()
