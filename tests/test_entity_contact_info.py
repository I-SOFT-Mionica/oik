"""Прошиени lists ("листе") didn't have persistent contact info — traced
to two gaps: the `Entity` model had no email/phone fields at all, and
even after adding them, ProsireniPhase1Tab's Send flow (`_on_send`,
inherited unchanged from BasePhase1Tab) read ElectionConfig.
party_full_names/party_contacts (стали RIK-party contacts, keyed by
abbreviation) instead — a prošireni entity_id almost never matches a RIK
abbreviation, so the Send dialog always showed blank, unmatched rows.

This file covers the GUI-level part: the entity add/edit dialog exposes
Email/Phone fields and they round-trip through `_entity_dialog` and
`_collect_candidacies` into a real `Entity`. The data-model round-trip
itself (`Entity.to_dict`/`from_dict`) is covered in test_candidacies.py;
the Send-flow address-book fix is covered in test_send_to_parties.py.
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


def test_entity_dialog_exposes_email_and_phone_fields(app, monkeypatch) -> None:
    """QLineEdit children appear in the order the dialog adds them:
    ed_id, ed_order, ed_email, ed_phone — SingleLineEdit (ed_name) and
    the two QComboBoxes aren't QLineEdit, so they're excluded here."""
    from PySide6.QtWidgets import QDialog, QLineEdit

    tab = _make_tab(app)

    def fake_exec(self):
        line_edits = self.findChildren(QLineEdit)
        assert len(line_edits) == 4, "expected ed_id, ed_order, ed_email, ed_phone"
        _ed_id, _ed_order, ed_email, ed_phone = line_edits
        ed_email.setText("lista@example.rs")
        ed_phone.setText("060-123")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    values = tab._entity_dialog(  # noqa: SLF001
        "New list", initial={"level": "parliamentary", "entity_id": "ent1"},
    )

    assert values is not None
    assert values["email"] == "lista@example.rs"
    assert values["phone"] == "060123"  # separators removed (core.phone)


def test_entity_dialog_prefills_existing_email_and_phone(app, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog

    tab = _make_tab(app)

    def fake_exec(self):
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    values = tab._entity_dialog(  # noqa: SLF001
        "Edit list", initial={
            "entity_id": "ent1", "level": "local",
            "email": "old@example.rs", "phone": "060-1",
        },
    )

    assert values is not None
    assert values["email"] == "old@example.rs"
    assert values["phone"] == "0601"


def test_collect_candidacies_carries_email_phone_into_entity(app) -> None:
    """The full round-trip: a dict row (as produced by _entity_dialog,
    or loaded from an existing config) must end up on the real Entity
    object that Phase 1 / Send actually reads."""
    tab = _make_tab(app)
    tab._entity_rows = [{  # noqa: SLF001
        "entity_id": "moja-lista-local", "name": "Моја листа",
        "entity_type": "party", "level": "local", "submission_order": 1,
        "linked_to_entity_id": "", "email": "lista@example.rs", "phone": "060-123",
    }]

    registry = tab._collect_candidacies()  # noqa: SLF001

    assert len(registry.entities) == 1
    e = registry.entities[0]
    assert e.email == "lista@example.rs"
    assert e.phone == "060-123"


def test_entities_table_shows_email_column(app) -> None:
    tab = _make_tab(app)
    assert "Email" in [
        tab.entities_table.table.horizontalHeaderItem(i).text()
        for i in range(tab.entities_table.table.columnCount())
    ]
