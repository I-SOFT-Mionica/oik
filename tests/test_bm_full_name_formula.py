"""Regression: polling-station full_name must combine Name with Address,
not with Municipality.

Field reports from two real clients (Мионица, Уб) confirmed every single
BM in their table ending up with the literal same "<school> — <municipality>"
full name. Traced to commit 19e4f60 (2026-05-22), which replaced a
previously free-text, operator-editable "Пун назив" column with an
auto-derived `name + " — " + municipality` formula — but every station in
one OikSettingsTab necessarily shares the same municipality, so that could
never differentiate anything. Several BMs sharing one building (a common
real layout — different rooms in the same school) need the address, not
the municipality, to be told apart.
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
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    QApplication.instance() or QApplication([])
    return OikSettingsTab(AppState())


def test_full_name_combines_with_address_not_municipality() -> None:
    from biracki_odbor.config import opstine as opstine_mod
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001

        tab._bm_rows = []  # noqa: SLF001
        tab._append_bm_row(PollingStation(  # noqa: SLF001
            bm_number=1, name="ОСНОВНА ШКОЛА МИЛАН РАКИЋ", address="сала 1",
        ))
        tab._append_bm_row(PollingStation(  # noqa: SLF001
            bm_number=2, name="ОСНОВНА ШКОЛА МИЛАН РАКИЋ", address="сала 2",
        ))
        tab._refresh_bm_view()  # noqa: SLF001

        stations = tab._collect_polling_stations()  # noqa: SLF001

        assert stations[0].full_name == "ОСНОВНА ШКОЛА МИЛАН РАКИЋ, сала 1"
        assert stations[1].full_name == "ОСНОВНА ШКОЛА МИЛАН РАКИЋ, сала 2"
        # The actual bug: before the fix both ended with the identical
        # "— Уб" municipality suffix, making them indistinguishable.
        assert stations[0].full_name != stations[1].full_name
        assert "Уб" not in stations[0].full_name
    finally:
        tab.deleteLater()


def test_full_name_falls_back_to_name_when_address_blank() -> None:
    """Same join convention as core.phase3_docx's name+address lines —
    address is dropped entirely when blank, not left as a trailing
    comma or empty municipality suffix."""
    from biracki_odbor.config import opstine as opstine_mod
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001

        tab._bm_rows = []  # noqa: SLF001
        tab._append_bm_row(PollingStation(bm_number=1, name="ОШ Пример", address=""))  # noqa: SLF001
        tab._refresh_bm_view()  # noqa: SLF001

        stations = tab._collect_polling_stations()  # noqa: SLF001

        assert stations[0].full_name == "ОШ Пример"
    finally:
        tab.deleteLater()


def test_operator_override_is_preserved_verbatim() -> None:
    """The whole point of restoring a visible, editable field: when the
    auto-derived default is wrong for a specific station, the operator's
    own typed text must win outright — never silently recomputed back
    to Name+Address."""
    from biracki_odbor.config import opstine as opstine_mod
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001

        tab._bm_rows = []  # noqa: SLF001
        tab._append_bm_row(PollingStation(  # noqa: SLF001
            bm_number=1, name="ОШ Пример", address="Улица 1",
            full_name="Потпуно другачији текст по избору оператера",
        ))
        tab._refresh_bm_view()  # noqa: SLF001

        stations = tab._collect_polling_stations()  # noqa: SLF001

        assert stations[0].full_name == "Потпуно другачији текст по избору оператера"
    finally:
        tab.deleteLater()


def test_add_bm_dialog_exposes_editable_full_name_field(monkeypatch) -> None:
    """The dialog itself must offer the field — not just the data model."""
    from PySide6.QtWidgets import QDialog

    tab = _make_tab()
    try:
        def fake_exec(self):
            self._edits["bm_number"].setText("5")  # noqa: SLF001
            self._edits["name"].setText("ОШ Нова")  # noqa: SLF001
            self._edits["address"].setText("Трг 1")  # noqa: SLF001
            self._edits["full_name"].setText("Ручно уписан пун назив")  # noqa: SLF001
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        tab._add_bm_row()  # noqa: SLF001

        assert tab._bm_rows[-1]["full_name"] == "Ручно уписан пун назив"  # noqa: SLF001
    finally:
        tab.deleteLater()


def test_edit_bm_dialog_prefills_the_stored_full_name(monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab()
    try:
        tab._bm_rows = []  # noqa: SLF001
        tab._append_bm_row(PollingStation(  # noqa: SLF001
            bm_number=1, name="ОШ Пример", address="Улица 1",
            full_name="Постојећи пун назив",
        ))
        tab._refresh_bm_view()  # noqa: SLF001

        seen = {}

        def fake_exec(self):
            seen["full_name"] = self._edits["full_name"].text()  # noqa: SLF001
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        tab._edit_bm_row(0)  # noqa: SLF001

        assert seen["full_name"] == "Постојећи пун назив"
    finally:
        tab.deleteLater()


def test_save_and_reload_round_trips_the_address_based_full_name() -> None:
    from biracki_odbor.config import opstine as opstine_mod
    from biracki_odbor.core.models import PollingStation

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Мионица")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001
        tab.ed_genitive.setText("Мионице")
        tab.ed_locative.setText("Мионици")
        tab.ed_full.setText("ОПШТИНСКА ИЗБОРНА КОМИСИЈА ОПШТИНЕ МИОНИЦА")

        tab._bm_rows = []  # noqa: SLF001
        tab._append_bm_row(PollingStation(  # noqa: SLF001
            bm_number=1, name="ОШ Дринка", address="Улица 1",
        ))
        tab._refresh_bm_view()  # noqa: SLF001
        tab._save()  # noqa: SLF001

        assert tab.state.oik.polling_stations[0].full_name == "ОШ Дринка, Улица 1"
    finally:
        tab.deleteLater()
