"""Поставке ОИК → 3. Систем → Формат докумената: GUI load/save round-trip
for config.oik.DocumentFormat's header/footer distance. Same
OikConstants-backed, deferred-Save pattern as the other fields on this
tab (see test_nacelnik_full_name_field.py) — not the immediate-save
AppSettings pattern used for language/email.

Line spacing and title-block/body-paragraph spacing are edited on the
generation screens themselves (Phase 3, Измене), not here — see
test_phase3_tab_spacing.py and the Измене equivalent. This file also
covers that saving from HERE must not reset those fields back to
defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_tab():
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.config.oik import OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state._oik = OikConstants(  # noqa: SLF001 — test-only fixture path
        polling_stations=[PollingStation(bm_number=1, name="БМ 1")],
    )
    tab = OikSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    return tab, state


def test_defaults_shown_on_a_fresh_config() -> None:
    tab, _ = _make_tab()
    try:
        assert tab.sb_header_distance.value() == 1.0
        assert tab.sb_footer_distance.value() == 1.0
    finally:
        tab.deleteLater()


def test_loads_an_already_saved_non_default_value() -> None:
    from biracki_odbor.config.oik import DocumentFormat, OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    state = AppState()
    state._oik = OikConstants(  # noqa: SLF001
        polling_stations=[PollingStation(bm_number=1, name="БМ 1")],
        document_format=DocumentFormat(
            line_spacing="double", header_distance_cm=2.0, footer_distance_cm=1.5,
        ),
    )
    tab = OikSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    try:
        assert tab.sb_header_distance.value() == 2.0
        assert tab.sb_footer_distance.value() == 1.5
    finally:
        tab.deleteLater()


def test_editing_and_saving_round_trips_to_state() -> None:
    tab, state = _make_tab()
    try:
        tab.sb_header_distance.setValue(3.0)
        tab.sb_footer_distance.setValue(0.5)

        tab._save()  # noqa: SLF001

        assert state.oik.document_format.header_distance_cm == 3.0
        assert state.oik.document_format.footer_distance_cm == 0.5
    finally:
        tab.deleteLater()


def test_saving_from_this_tab_preserves_title_body_and_line_spacing() -> None:
    """Line spacing and title/body spacing live on the SAME DocumentFormat
    object but are edited on the generation screens, not here -- _save()
    must carry those fields forward instead of resetting them to defaults
    just because an operator happened to save from Поставке ОИК afterward."""
    from biracki_odbor.config.oik import DocumentFormat, OikConstants
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    state = AppState()
    state._oik = OikConstants(  # noqa: SLF001
        polling_stations=[PollingStation(bm_number=1, name="БМ 1")],
        document_format=DocumentFormat(line_spacing="double",
                                        title_before_pt=2.0, title_after_pt=1.0,
                                        body_before_pt=3.0, body_after_pt=9.0),
    )
    tab = OikSettingsTab(state)
    tab._load_from_state()  # noqa: SLF001
    try:
        tab.sb_header_distance.setValue(3.0)  # an unrelated edit on this tab
        tab._save()  # noqa: SLF001

        assert state.oik.document_format.line_spacing == "double"
        assert state.oik.document_format.title_before_pt == 2.0
        assert state.oik.document_format.title_after_pt == 1.0
        assert state.oik.document_format.body_before_pt == 3.0
        assert state.oik.document_format.body_after_pt == 9.0
    finally:
        tab.deleteLater()


def test_changing_a_field_marks_the_tab_dirty() -> None:
    tab, _ = _make_tab()
    try:
        assert tab.dirty is False
        tab.sb_header_distance.setValue(2.0)
        assert tab.dirty is True
    finally:
        tab.deleteLater()


def test_loading_does_not_spuriously_mark_dirty() -> None:
    """The initial _load_from_state() in _make_tab() must not itself
    flip dirty -- same _loading guard every other OikConstants-backed
    field on this tab already relies on."""
    tab, _ = _make_tab()
    try:
        assert tab.dirty is False
    finally:
        tab.deleteLater()
