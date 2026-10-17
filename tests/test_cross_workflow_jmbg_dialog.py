"""TODO §23: a manual correction that would put one JMBG in both
compositions gets a clear message and stays open, instead of a raw
database error on save."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from biracki_odbor.core.models import Person
from biracki_odbor.gui.tabs.corrections import _PersonEditDialog
from tests.test_jmbg import VALID_SAMPLES

JMBG = VALID_SAMPLES[0]
OTHER = VALID_SAMPLES[1]


def _dialog(other_jmbg: str):
    me = Person(bm_number=3, function="Члан 1", party="СНС", first_name="Ана", last_name="Ив",
                jmbg=OTHER)
    them = Person(bm_number=7, function="Члан [2]", party="ДС", first_name="Петар", last_name="Петровић",
                  jmbg=other_jmbg)
    dlg = _PersonEditDialog(me, mode="edit", spec=None, other_workflow=[them])
    dlg.ed_note.setEditText("Исправка грешке у уносу")
    return dlg


def test_clash_with_other_composition_is_explained_and_dialog_stays_open(monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    dlg = _dialog(other_jmbg=JMBG)
    dlg.ed_jmbg.setText(JMBG)
    dlg._on_accept()  # noqa: SLF001
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert len(shown) == 1 and "Петар Петровић" in shown[0] and "7" in shown[0]


def test_free_jmbg_saves_normally(monkeypatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    dlg = _dialog(other_jmbg=JMBG)
    dlg.ed_jmbg.setText(OTHER)
    dlg._on_accept()  # noqa: SLF001
    assert shown == []
    assert dlg.result() == QDialog.DialogCode.Accepted
