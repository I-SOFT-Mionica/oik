"""Regression test: the candidacies "Name" (full list name) field must
use SingleLineEdit(multiline=True) — a real multi-paragraph text box
(vertical scroll only, no horizontal scroll), not a plain QLineEdit and
not the wrap-only mode used for party full names.

Field report: an operator pasted a real coalition list's full name —
319 characters, copied verbatim from its official multi-line layout,
carrying an embedded newline — into a plain QLineEdit and it crashed
Excel file generation entirely (see tests/test_safe_filename.py). The
first fix attempt used SingleLineEdit(wrap=True) (party full names'
widget), which visually wraps but still collapses real newlines to
spaces — wrong for this field specifically: an election list's line
breaks can be meaningful content the operator is deliberately
preserving, not incidental whitespace. multiline=True keeps Enter and
pasted newlines working normally while still confining the box to
vertical-only scrolling.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_tab(app):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab
    apply_global_style(app)
    state = AppState()
    return ElectionSettingsTab(state)


def test_entity_dialog_name_field_is_single_line_edit_in_multiline_mode(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QLineEdit
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    tab = _make_tab(app)
    captured: dict = {}

    def fake_exec(self):
        name_widgets = self.findChildren(SingleLineEdit)
        captured["single_line_edits"] = name_widgets
        captured["plain_line_edits"] = self.findChildren(QLineEdit)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    tab._entity_dialog(  # noqa: SLF001
        "New list", initial={"level": "parliamentary"},
    )

    assert len(captured["single_line_edits"]) == 1, (
        "expected exactly one SingleLineEdit (the Name field) in the entity dialog"
    )
    ed = captured["single_line_edits"][0]
    assert ed._multiline is True  # noqa: SLF001
    from PySide6.QtCore import Qt
    assert ed.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert ed.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_entity_dialog_name_field_preserves_pasted_newlines(app, monkeypatch) -> None:
    """The corrected behaviour: a pasted multi-line list name keeps its
    embedded line breaks — unlike party full names, this field's
    newlines are meaningful and must survive verbatim into Решења."""
    from PySide6.QtWidgets import QDialog
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit
    from PySide6.QtCore import QMimeData

    pasted = "СРБИЈА ПРОТИВ НАСИЉА\nМИРОСЛАВ МИКИ АЛЕКСИЋ"

    def fake_exec(self):
        ed = self.findChildren(SingleLineEdit)[0]
        mime = QMimeData()
        mime.setText(pasted)
        ed.insertFromMimeData(mime)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    tab = _make_tab(app)
    values = tab._entity_dialog(  # noqa: SLF001
        "New list", initial={"level": "parliamentary"},
    )

    assert values is not None
    assert values["name"] == pasted


def test_entity_dialog_name_field_enter_key_inserts_real_newline(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    def fake_exec(self):
        ed = self.findChildren(SingleLineEdit)[0]
        ed.setPlainText("line one")
        cursor = ed.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        ed.setTextCursor(cursor)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Return, Qt.NoModifier)
        ed.keyPressEvent(event)
        ed.insertPlainText("line two")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    tab = _make_tab(app)
    values = tab._entity_dialog(  # noqa: SLF001
        "New list", initial={"level": "parliamentary"},
    )

    assert values is not None
    assert values["name"] == "line one\nline two"
