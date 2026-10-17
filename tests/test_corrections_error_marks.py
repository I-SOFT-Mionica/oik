"""Tests for the Phase 2.5 «Сви чланови» error-marking + email column.

Background: after Phase 2 finishes, if the operator chose to import
despite errors, those errors used to be invisible once they switched
to the Corrections tab — they had to scroll back to Phase 2's error
table to see which rows were affected. Phase 2.5 now reads the latest
ValidationReport from AppState and tints rows whose JMBG matches an
error, with a tooltip listing the messages. The «Само грешке» toggle
collapses the table to just those rows for quick triage.

This file pins:
  - JMBG-keyed error index construction in `_MembersPanel.set_error_report`,
  - row tinting only applies to matching JMBGs,
  - the «Само грешке» filter excludes clean rows,
  - the new «Е-пошта» column renders Person.email.
"""

from __future__ import annotations

import pytest

from biracki_odbor.core.models import Issue, Person, ValidationReport


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Headless QApplication + isolated home so the panel can construct."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_persons() -> list[Person]:
    return [
        Person(bm_number=1, function="Председник", party="СНС",
               first_name="Ана", last_name="Анић", jmbg="0101990770010",
               email="ana@example.rs"),
        Person(bm_number=1, function="Члан 1", party="СПС",
               first_name="Бора", last_name="Борић", jmbg="0202988770011",
               email="bora@example.rs"),
        Person(bm_number=2, function="Председник", party="СНС",
               first_name="Цица", last_name="Цицић", jmbg="0303986770012",
               email=""),
    ]


def _make_report_with_jmbg_errors(*jmbgs: str) -> ValidationReport:
    return ValidationReport(issues=[
        Issue(
            code="JMBG_BAD_CHECKSUM",
            message_sr=f"ЈМБГ '{j}' не пролази MOD 11 проверу",
            severity="error",
            detail=j,
        )
        for j in jmbgs
    ])


def test_email_column_in_headers(app, tmp_path, monkeypatch) -> None:
    """The new Е-пошта column must be the 9th header. Catches accidental
    removal during column-resize edits."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import _MembersPanel, CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        assert "Email" in tab.members_panel.HEADERS
        assert tab.members_panel.HEADERS.index("Email") == 8
    finally:
        tab.deleteLater()


def test_set_error_report_builds_jmbg_index(app, tmp_path, monkeypatch) -> None:
    """set_error_report must extract JMBG-keyed errors and ignore issues
    whose detail isn't a 13-digit JMBG (filename / column-name etc)."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        report = ValidationReport(issues=[
            Issue(code="JMBG_BAD_CHECKSUM",
                  message_sr="ЈМБГ '0101990770010' не пролази MOD 11",
                  severity="error", detail="0101990770010"),
            # Non-JMBG detail — should be ignored by the index.
            Issue(code="NAME_NON_CYRILLIC", message_sr="...",
                  severity="error", detail="Petar"),
            # Warning — should be ignored even if detail is a JMBG.
            Issue(code="JMBG_DUPLICATE",
                  message_sr="...", severity="warning",
                  detail="0202988770011"),
        ])
        tab.members_panel.set_error_report(report)
        assert "0101990770010" in tab.members_panel._errors_by_jmbg
        assert "Petar" not in tab.members_panel._errors_by_jmbg
        # Warning was filtered out — index is errors only.
        assert "0202988770011" not in tab.members_panel._errors_by_jmbg
    finally:
        tab.deleteLater()


def test_set_error_report_none_clears_index(app, tmp_path, monkeypatch) -> None:
    """Passing None must wipe a previously-set index — needed so a fresh
    Phase 2 run with a clean roster (or a no-master state) doesn't leak
    stale marks from an earlier import."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        tab.members_panel.set_error_report(
            _make_report_with_jmbg_errors("0101990770010"),
        )
        assert tab.members_panel._errors_by_jmbg
        tab.members_panel.set_error_report(None)
        assert tab.members_panel._errors_by_jmbg == {}
    finally:
        tab.deleteLater()


def test_errors_only_filter_excludes_clean_rows(app, tmp_path, monkeypatch) -> None:
    """With «Само грешке» on, the visible row count must equal the number
    of persons whose JMBG appears in the error index."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        persons = _make_persons()
        tab.members_panel.set_persons(persons)
        tab.members_panel.set_error_report(
            _make_report_with_jmbg_errors("0202988770011"),  # only Бора
        )
        # Without the filter — every person visible.
        assert tab.members_panel.table.rowCount() == 3
        # Flip the toggle on, expect only the one error row.
        tab.members_panel.cb_errors_only.setChecked(True)
        assert tab.members_panel.table.rowCount() == 1
        # And it must be Бора, not Ана or Цица.
        assert tab.members_panel.table.item(0, 5).text() == "0202988770011"
    finally:
        tab.deleteLater()


def test_email_column_renders_person_email(app, tmp_path, monkeypatch) -> None:
    """The new column must surface Person.email in column index 8."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        persons = _make_persons()
        tab.members_panel.set_persons(persons)
        # Find the row with Ana — first column is BM number, easier to
        # locate by JMBG (column 5).
        emails = [
            tab.members_panel.table.item(r, 8).text()
            for r in range(tab.members_panel.table.rowCount())
        ]
        assert "ana@example.rs" in emails
        assert "bora@example.rs" in emails
        # Cica has no email — should render as "" (empty cell).
        assert "" in emails
    finally:
        tab.deleteLater()


def test_search_box_matches_email(app, tmp_path, monkeypatch) -> None:
    """Typing into the search box should also match against the new
    email column — otherwise the column would be a dead-end visually."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.corrections import CorrectionsTab
    state = AppState()
    tab = CorrectionsTab(state)
    try:
        tab.members_panel.set_persons(_make_persons())
        # Typing the unique substring "bora@" should narrow to one row.
        tab.members_panel.ed_search.setText("bora@")
        assert tab.members_panel.table.rowCount() == 1
        assert tab.members_panel.table.item(0, 8).text() == "bora@example.rs"
    finally:
        tab.deleteLater()


def test_app_state_phase2_report_round_trip(app, tmp_path, monkeypatch) -> None:
    """AppState.set_phase2_report must update the property AND emit
    the signal — Phase 2.5 connects to that signal to refresh marks."""
    monkeypatch.setattr(
        "biracki_odbor._release_info.GITHUB_REPO", "",
        raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    state = AppState()
    fired = []
    state.phase2_report_changed.connect(lambda: fired.append(True))
    assert state.last_phase2_report is None
    rep = _make_report_with_jmbg_errors("0101990770010")
    state.set_phase2_report(rep)
    assert state.last_phase2_report is rep
    assert fired == [True]
    # Clearing must also emit.
    state.set_phase2_report(None)
    assert state.last_phase2_report is None
    assert fired == [True, True]
