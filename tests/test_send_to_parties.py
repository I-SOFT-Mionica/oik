"""Tests for §4 — Outlook draft per party.

The actual COM dispatch is impossible to cover headlessly (needs a
real Outlook profile); these tests pin the headless logic:

- DraftSpec construction
- Dialog filters out un-checked rows and rows missing email
- Subject + body templating with {party} / {full_name}
- create_drafts raises OutlookUnavailable on non-Windows / no-pywin32
- Phase 1 button is hidden when Outlook isn't available
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from biracki_odbor.integrations import outlook as outlook_mod


def test_draft_spec_construction(tmp_path: Path) -> None:
    f = tmp_path / "СНС.xlsx"
    f.write_bytes(b"x")
    spec = outlook_mod.DraftSpec(
        to="kontakt@sns.rs", subject="Тема", body="Тело",
        attachment=f,
    )
    assert spec.to == "kontakt@sns.rs"
    assert spec.attachment == f


def test_create_drafts_raises_when_unavailable() -> None:
    if outlook_mod.OUTLOOK_AVAILABLE:
        pytest.skip("Outlook available on this machine — nothing to assert.")
    with pytest.raises(outlook_mod.OutlookUnavailable):
        outlook_mod.create_drafts([])


def _qapp():
    return QApplication.instance() or QApplication([])


def test_dialog_skips_unchecked_and_no_email(tmp_path: Path) -> None:
    """Operator clicks OK with some rows unchecked or missing email;
    those rows must NOT produce DraftSpec entries.

    This is the safety net against accidentally creating an empty-to:
    draft (Outlook lets you, but it's pointless) or sending a file to
    the wrong party because the row that's checked has the wrong file.
    """
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
    _qapp()

    files = []
    for name in ("СНС.xlsx", "СПС.xlsx", "ДС.xlsx"):
        f = tmp_path / name
        f.write_bytes(b"x")
        files.append(f)

    dlg = SendToPartiesDialog(
        files=files,
        party_full_names={
            "СНС": "Посланичка група A",
            "СПС": "Посланичка група B",
            "ДС":  "Посланичка група C",
        },
        party_emails={"СНС": "a@example.com", "СПС": "b@example.com"},
    )
    # Row 0 (СНС) is checked-by-default because email exists; uncheck.
    dlg.table.item(0, 0).setCheckState(Qt.Unchecked)
    # Row 2 (ДС) has no email; the dialog defaults it unchecked, but
    # even if forced-checked, it must be skipped.
    dlg.table.item(2, 0).setCheckState(Qt.Checked)

    drafts = dlg.prepared_drafts()
    assert len(drafts) == 1
    assert drafts[0].to == "b@example.com"
    assert drafts[0].attachment.name == "СПС.xlsx"


def test_dialog_subject_body_templating(tmp_path: Path) -> None:
    """{party} and {full_name} placeholders are substituted per-row."""
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
    _qapp()

    f = tmp_path / "СНС.xlsx"
    f.write_bytes(b"x")

    dlg = SendToPartiesDialog(
        files=[f],
        party_full_names={"СНС": "Посланичка група A"},
        party_emails={"СНС": "a@example.com"},
    )
    dlg.ed_subject.setText("Hello {party} ({full_name})")
    dlg.ed_body.setPlainText("Dear {full_name},\nplease fill the file.")
    drafts = dlg.prepared_drafts()
    assert len(drafts) == 1
    assert drafts[0].subject == "Hello СНС (Посланичка група A)"
    assert drafts[0].body == "Dear Посланичка група A,\nplease fill the file."


def test_dialog_defaults_say_stalni_by_default(tmp_path: Path) -> None:
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
    _qapp()
    f = tmp_path / "СНС.xlsx"
    f.write_bytes(b"x")
    dlg = SendToPartiesDialog(files=[f], party_full_names={}, party_emails={})
    assert "сталном саставу" in dlg.ed_body.toPlainText()
    assert "проширеном" not in dlg.ed_body.toPlainText()
    assert dlg.ed_subject.text().startswith("Стални састав")


def test_dialog_defaults_say_prosireni_for_prosireni_workflow(tmp_path: Path) -> None:
    """Field report class: 'Send to lists' for the прошиpени workflow
    prepared a draft whose default text claimed the attached file was
    for stalni ('...чланова бирачког одбора у сталном саставу...') even
    though it's shared with prosireni via the same dialog/BasePhase1Tab
    flow -- workflow_slug must select the matching boilerplate."""
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
    _qapp()
    f = tmp_path / "ent1.xlsx"
    f.write_bytes(b"x")
    dlg = SendToPartiesDialog(
        files=[f], party_full_names={}, party_emails={}, workflow_slug="prosireni",
    )
    assert "проширеном саставу" in dlg.ed_body.toPlainText()
    assert "сталном саставу" not in dlg.ed_body.toPlainText()
    assert dlg.ed_subject.text().startswith("Проширени састав")


def test_dialog_title_and_column_say_liste_for_prosireni(tmp_path: Path) -> None:
    """The window title and the 2nd table column both said "Странка"
    (Party) even when the rows were actually прошиени lists — fixed
    alongside the address-book mismatch below, since both are the same
    underlying "terminology must match the workflow" requirement."""
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
    _qapp()
    f = tmp_path / "ent1.xlsx"
    f.write_bytes(b"x")

    stalni_dlg = SendToPartiesDialog(files=[f], party_full_names={}, party_emails={})
    assert stalni_dlg.windowTitle() == "Пошаљи странкама"
    assert stalni_dlg.HEADERS[1] == "Странка"

    prosireni_dlg = SendToPartiesDialog(
        files=[f], party_full_names={}, party_emails={}, workflow_slug="prosireni",
    )
    assert prosireni_dlg.windowTitle() == "Пошаљи листама"
    assert prosireni_dlg.HEADERS[1] == "Листа"


def test_prosireni_send_recipients_use_entity_registry_not_party_contacts(
    tmp_path: Path, monkeypatch,
) -> None:
    """Field report: прошиени's Send dialog never had a pre-filled email
    for any list, forcing a fresh manual entry every time. Root cause —
    ProsireniPhase1Tab inherited BasePhase1Tab._on_send unchanged, which
    always read ElectionConfig.party_full_names/party_contacts (стални's
    RIK-party address book, keyed by abbreviation). Прошиени's generated
    files are named by entity_id (`generate_entity_files`), which almost
    never matches a RIK abbreviation, so every row fell back to a blank,
    unmatched entry. `_send_recipients()` must instead build from
    candidacies.entities, keyed by entity_id, with each entity's own
    saved email/name — never from party_full_names/party_contacts."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.config.candidacies import CandidaciesRegistry, Entity
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab
    _qapp()
    app = QApplication.instance()
    apply_global_style(app)

    state = AppState()
    state.election.candidacies = CandidaciesRegistry(entities=[
        Entity(
            entity_id="moja-lista-local", name="Моја листа", entity_type="party",
            level="local", submission_order=1, email="lista@example.rs",
        ),
        Entity(
            entity_id="druga-lista-local", name="Друга листа", entity_type="party",
            level="local", submission_order=2, email="",
        ),
    ])
    # A RIK party contact that must NEVER leak into the прошиени address
    # book, even though nothing here references it by name — the whole
    # point is that _send_recipients() doesn't go near party_contacts
    # at all for this workflow.
    from biracki_odbor.config.election import PartyContact
    state.election.party_full_names = {"СНС": "Нека странка"}
    state.election.party_contacts = {"СНС": PartyContact(email="party@example.com")}

    tab = ProsireniPhase1Tab(state)
    try:
        full_names, emails = tab._send_recipients()  # noqa: SLF001
        assert full_names == {
            "moja-lista-local": "Моја листа",
            "druga-lista-local": "Друга листа",
        }
        assert emails == {"moja-lista-local": "lista@example.rs"}
        assert "СНС" not in full_names
        assert "party@example.com" not in emails.values()
    finally:
        tab.deleteLater()


def test_stalni_send_recipients_unchanged(tmp_path: Path, monkeypatch) -> None:
    """The default (стални) path must keep reading party_full_names/
    party_contacts exactly as before — this pins that refactoring
    _on_send into an overridable _send_recipients() didn't change
    стални's own behavior."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.config.election import PartyContact
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.style import apply_global_style
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab
    _qapp()
    app = QApplication.instance()
    apply_global_style(app)

    state = AppState()
    state.election.party_full_names = {"СНС": "Нека странка"}
    state.election.party_contacts = {"СНС": PartyContact(email="party@example.com")}

    tab = Phase1Tab(state)
    try:
        full_names, emails = tab._send_recipients()  # noqa: SLF001
        assert full_names == {"СНС": "Нека странка"}
        assert emails == {"СНС": "party@example.com"}
    finally:
        tab.deleteLater()


def test_phase1_send_button_hidden_when_outlook_unavailable(
    tmp_path: Path, monkeypatch,
) -> None:
    """When OUTLOOK_AVAILABLE is False, the Phase 1 send-to-parties
    button must not render — matches the integration's contract that
    non-Windows installs degrade gracefully instead of erroring on
    every click."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor import _release_info
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab
    from biracki_odbor.gui.style import apply_global_style

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    app = _qapp()
    apply_global_style(app)
    state = AppState()
    tab = Phase1Tab(state)
    try:
        if outlook_mod.OUTLOOK_AVAILABLE:
            # On Windows with Outlook, button visible; disabled until
            # Phase 1 runs.
            assert not tab.btn_send.isEnabled()
        else:
            assert tab.btn_send.isHidden()
    finally:
        tab.deleteLater()
