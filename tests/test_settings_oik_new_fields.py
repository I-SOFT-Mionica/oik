"""§21: municipality website + chief's e-mail fields in OikSettingsTab."""

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
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    tab = OikSettingsTab(state)
    return tab


def test_website_and_nacelnik_email_save_and_reload() -> None:
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Мионица")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001
        tab.ed_genitive.setText("Мионице")
        tab.ed_locative.setText("Мионици")
        tab.ed_full.setText("ОПШТИНСКА ИЗБОРНА КОМИСИЈА ОПШТИНЕ МИОНИЦА")
        tab.ed_website.setText("mionica.rs")
        tab.ed_nacelnik_email.setText("nacelnik@mionica.rs")

        # nacelnik_email persists via editingFinished (like oik_email),
        # independent of the main Save button — exercised for real by
        # the second test below; simulate it here too.
        tab._on_nacelnik_email_changed()  # noqa: SLF001
        tab._save()  # noqa: SLF001

        assert tab.state.oik.municipality.website == "mionica.rs"
        assert tab.state.app_settings.nacelnik_email == "nacelnik@mionica.rs"

        # Fresh tab against the just-saved state reloads both fields.
        tab2 = tab.__class__(tab.state)
        try:
            assert tab2.ed_website.text() == "mionica.rs"
            assert tab2.ed_nacelnik_email.text() == "nacelnik@mionica.rs"
        finally:
            tab2.deleteLater()
    finally:
        tab.deleteLater()


def test_municipality_picker_selection_reveals_code() -> None:
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001
        assert tab.cb_name.currentText() == "Уб"
        assert tab.lbl_sifra.text() == entry.sifra
    finally:
        tab.deleteLater()


def test_municipality_picker_reverts_unmatched_typed_text() -> None:
    """Typing something that doesn't match any registry entry, then
    blurring the field, must revert to the last accepted selection —
    Назив can never hold an unvalidated string."""
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001

        tab.cb_name.lineEdit().setText("Овоопштинанепостоји")
        tab._on_name_edit_finished()  # noqa: SLF001 — simulates editingFinished

        assert tab.cb_name.currentText() == "Уб"
        assert tab.lbl_sifra.text() == entry.sifra
    finally:
        tab.deleteLater()


def test_municipality_picker_accepts_typed_exact_match() -> None:
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Мионица")
        assert entry is not None
        tab.cb_name.lineEdit().setText("Мионица")
        tab._on_name_edit_finished()  # noqa: SLF001

        assert tab.cb_name.currentText() == "Мионица"
        assert tab.lbl_sifra.text() == entry.sifra
    finally:
        tab.deleteLater()


def test_sifra_opstine_saves_and_reloads() -> None:
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        entry = opstine_mod.find_by_name("Уб")
        assert entry is not None
        tab._set_municipality_selection(entry.sifra)  # noqa: SLF001
        tab.ed_genitive.setText("Уба")
        tab.ed_locative.setText("Убу")
        tab.ed_full.setText("ОПШТИНСКА ИЗБОРНА КОМИСИЈА ОПШТИНЕ УБ")
        tab._save()  # noqa: SLF001

        assert tab.state.oik.municipality.sifra_opstine == entry.sifra

        tab2 = tab.__class__(tab.state)
        try:
            assert tab2.cb_name.currentText() == "Уб"
            assert tab2.lbl_sifra.text() == entry.sifra
        finally:
            tab2.deleteLater()
    finally:
        tab.deleteLater()


def test_legacy_name_without_sifra_resolves_on_load() -> None:
    """Migration path: a config saved before sifra_opstine existed had
    only a free-text name. On load, resolve it against the registry by
    exact match so upgrading doesn't blank out an already-configured
    municipality."""
    tab = _make_tab()
    try:
        tab.state.oik.municipality.name = "Уб"
        tab.state.oik.municipality.sifra_opstine = ""
        tab._load_from_state()  # noqa: SLF001

        assert tab.cb_name.currentText() == "Уб"
        assert tab.lbl_sifra.text() == "71218"
    finally:
        tab.deleteLater()


def test_picking_municipality_autofills_declension() -> None:
    """Field report: switching Уб → Мионица via the picker left the old
    Уб-declined genitive/locative text behind. Picking a NEW municipality
    (via activated) must refresh both fields to a fresh guess."""
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        ub = opstine_mod.find_by_name("Уб")
        mionica = opstine_mod.find_by_name("Мионица")
        assert ub is not None and mionica is not None

        tab._set_municipality_selection(ub.sifra)  # noqa: SLF001
        tab.ed_genitive.setText("Уба")
        tab.ed_locative.setText("Убу")

        idx = tab.cb_name.findData(mionica.sifra)
        tab._on_name_activated(idx)  # noqa: SLF001 — simulates picking from the dropdown

        assert tab.cb_name.currentText() == "Мионица"
        assert tab.ed_genitive.text() == "Мионице"
        assert tab.ed_locative.text() == "Мионици"
    finally:
        tab.deleteLater()


def test_reselecting_same_municipality_does_not_clobber_hand_edited_declension() -> None:
    """Re-picking the SAME municipality (e.g. re-confirming on a re-run
    of _load_from_state, or an accidental re-click) must not overwrite a
    genitive/locative the operator already hand-corrected — only an
    actual change to a different municipality should refresh them."""
    from biracki_odbor.config import opstine as opstine_mod

    tab = _make_tab()
    try:
        ub = opstine_mod.find_by_name("Уб")
        assert ub is not None
        tab._set_municipality_selection(ub.sifra)  # noqa: SLF001
        tab.ed_genitive.setText("Ручно исправљено")

        idx = tab.cb_name.findData(ub.sifra)
        tab._on_name_activated(idx)  # noqa: SLF001 — picks the SAME entry again

        assert tab.ed_genitive.text() == "Ручно исправљено"
    finally:
        tab.deleteLater()


def test_legacy_name_not_in_registry_leaves_picker_blank() -> None:
    tab = _make_tab()
    try:
        tab.state.oik.municipality.name = "Непостојеће Место"
        tab.state.oik.municipality.sifra_opstine = ""
        tab._load_from_state()  # noqa: SLF001

        assert tab.cb_name.currentText() == ""
        assert tab.lbl_sifra.text() == ""
    finally:
        tab.deleteLater()


def test_nacelnik_email_editing_finished_persists_without_full_save() -> None:
    """Mirrors oik_email's existing behavior: editingFinished alone saves
    AppSettings immediately, no need to click the main Save button."""
    tab = _make_tab()
    try:
        tab.ed_nacelnik_email.setText("chief@example.rs")
        tab._on_nacelnik_email_changed()  # noqa: SLF001 — simulates editingFinished

        tab2 = tab.__class__(tab.state)
        try:
            assert tab2.ed_nacelnik_email.text() == "chief@example.rs"
        finally:
            tab2.deleteLater()
    finally:
        tab.deleteLater()
