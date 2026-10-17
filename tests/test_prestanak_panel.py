"""Tests for gui.tabs.prestanak_panel.PrestanakPanel.

Fields-only widget — generation (and the "Отвори фасциклу" confirm
flow) now happens through IzmenaPanel's shared Генериши button, tested
in test_izmene.py. This file only covers the widget's own contract:
construction, collect_spec()/missing_fields(), and load_draft().
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


def _make_panel(app):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.prestanak_panel import PrestanakPanel
    state = AppState()
    state.oik.municipality.name = "Мионица"
    return PrestanakPanel(state)


def _fill_required(panel) -> None:
    panel.ed_person_name.setText("Петар Петровић")
    panel.ed_ceasing_broj.setText("013-5-30-9/2026")
    panel.ed_existing_broj.setText("013-5-30-1/2026")
    panel.ed_document_broj.setText("Број: 013-5-30-15/2026")


def test_panel_constructs_cleanly(app, home) -> None:
    panel = _make_panel(app)
    try:
        assert panel.ed_person_name.text() == ""
    finally:
        panel.deleteLater()


def test_ceasing_sastav_defaults_to_prosireni_but_can_switch_to_stalni(app, home) -> None:
    """Default matches the common case (RIK's own template only shows
    прошиени lapsing), but must be switchable — confirmed possible for
    this cycle specifically (стали and прошиени deadlines coincide)."""
    panel = _make_panel(app)
    try:
        assert panel.cb_ceasing_sastav.currentData() == "prosireni"
        idx = panel.cb_ceasing_sastav.findData("stalni")
        assert idx >= 0
        panel.cb_ceasing_sastav.setCurrentIndex(idx)
        assert panel.cb_ceasing_sastav.currentData() == "stalni"
    finally:
        panel.deleteLater()


def test_collect_spec_returns_none_when_required_fields_missing(app, home) -> None:
    panel = _make_panel(app)
    try:
        assert panel.collect_spec() is None
        assert panel.missing_fields()  # non-empty, names what's missing
    finally:
        panel.deleteLater()


def test_collect_spec_builds_a_real_spec_once_filled(app, home) -> None:
    panel = _make_panel(app)
    try:
        _fill_required(panel)
        spec = panel.collect_spec()
        assert spec is not None
        assert spec.person_name == "Петар Петровић"
        assert spec.municipality == "Мионица"
        assert panel.missing_fields() == []
    finally:
        panel.deleteLater()


def test_collect_spec_includes_existing_municipality(app, home) -> None:
    """Field bug: PrestanakSpec used to have no way to record the
    EXISTING seat's own municipality at all — the generated document
    silently printed THIS OIK's municipality for both seats, even
    though the whole scenario is that they're normally different."""
    panel = _make_panel(app)
    try:
        _fill_required(panel)
        panel.ed_existing_municipality.setText("Ваљево")
        spec = panel.collect_spec()
        assert spec is not None
        assert spec.existing_municipality == "Ваљево"
    finally:
        panel.deleteLater()


def test_load_draft_prefills_known_facts(app, home) -> None:
    """A row selected from the чл. 14(1)(8)-flagged table pre-fills
    whatever THIS OIK's own log actually captured — name, this BM, and
    the other BM/municipality the operator typed into Corrections'
    Напомена dialog. Everything else (which seat ceases, both decisions'
    broj/date) is still the operator's call."""
    panel = _make_panel(app)
    try:
        panel.load_draft({
            "bm": 3, "function": "Заменик члана 2",
            "person_name": "Ана Анић",
            "other_bm": 7, "other_municipality": "Ваљево",
        })
        assert panel.ed_person_name.text() == "Ана Анић"
        assert panel.sb_ceasing_bm.value() == 3
        assert panel.cb_ceasing_role.currentData() == "заменика члана"
        assert panel.sb_existing_bm.value() == 7
        assert panel.ed_existing_municipality.text() == "Ваљево"
    finally:
        panel.deleteLater()


def test_load_draft_maps_plain_member_function_to_clana_role(app, home) -> None:
    panel = _make_panel(app)
    try:
        panel.load_draft({
            "bm": 1, "function": "Председник", "person_name": "Јован Јовановић",
            "other_bm": None, "other_municipality": "",
        })
        assert panel.cb_ceasing_role.currentData() == "члана"
    finally:
        panel.deleteLater()


def test_load_draft_prefills_other_decision_number(app, home) -> None:
    """The other municipality's decision number, when Corrections
    captured it, pre-fills the existing seat's broj — the one piece
    besides BM/municipality that Corrections can realistically know."""
    panel = _make_panel(app)
    try:
        panel.load_draft({
            "bm": 3, "function": "Члан 1", "person_name": "Ана Анић",
            "other_bm": 7, "other_municipality": "Ваљево",
            "other_decision_broj": "013-9-1-4/2026",
        })
        assert panel.ed_existing_broj.text() == "013-9-1-4/2026"
    finally:
        panel.deleteLater()


def test_ceasing_decision_number_and_date_auto_derive_from_election_config(app, home) -> None:
    """THIS OIK's own original decision for the lapsing seat is NOT
    something the operator should have to look up or retype — it's the
    same broj/date Phase 3 already printed for that BM, recomputed the
    identical way (format_broj + bm_offset), not stored separately."""
    from biracki_odbor.config.election import DocumentInfo, ElectionDates
    from biracki_odbor.core.phase3_docx import format_broj
    from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
    from tests.test_phase1 import _make_oik

    panel = _make_panel(app)
    try:
        panel.state._oik = _make_oik(5)  # noqa: SLF001
        panel.state.election.document = DocumentInfo(number_prefix="013-5-30")
        panel.state.election.election.dates = ElectionDates(
            session_date="6. децембра 2026. године",
            subbroj_start="1",
            session_date_prosireni="9. децембра 2026. године",
            subbroj_start_prosireni="1",
        )
        panel.sb_ceasing_bm.setValue(4)  # 4th station -> offset 3

        expected_broj = format_broj(
            panel.state.election, 4, 3, PROSIRENI_SPEC,
        ).removeprefix("Број: ")
        assert panel.ed_ceasing_broj.text() == expected_broj
        assert panel.dt_ceasing_date.date().toString("yyyy-MM-dd") == "2026-12-09"

        # Switching composition re-derives against the other spec too.
        idx = panel.cb_ceasing_sastav.findData("stalni")
        panel.cb_ceasing_sastav.setCurrentIndex(idx)
        expected_broj_stalni = format_broj(
            panel.state.election, 4, 3, STALNI_SPEC,
        ).removeprefix("Број: ")
        assert panel.ed_ceasing_broj.text() == expected_broj_stalni
    finally:
        panel.deleteLater()
