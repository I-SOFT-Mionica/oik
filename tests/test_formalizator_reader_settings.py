"""Formalizator's settings store and the ID-card reader choices it holds:
which Čelik API DLL (MUP ships new ones for newer card chips) and which
smart-card reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formalizator.core import settings as fz_settings
from formalizator.reader import eid_reader

ROOT = Path(__file__).resolve().parent.parent
BUNDLED_DLL = ROOT / "formalizator" / "resources" / "CelikApi.dll"


# ── settings store ────────────────────────────────────────────────

def test_settings_round_trip(tmp_path) -> None:
    s = fz_settings.FormalizatorSettings(celik_dll_path="C:/MUP/CelikApi.dll", card_reader_name="R 1")
    fz_settings.save(s, tmp_path)
    back = fz_settings.load(tmp_path)
    assert back.celik_dll_path == "C:/MUP/CelikApi.dll" and back.card_reader_name == "R 1"
    assert not list(tmp_path.glob("*.tmp")), "atomic write leaves no temp file"


def test_keys_from_a_newer_version_survive_a_save(tmp_path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps({"future_feature": {"x": 1}, "celik_dll_path": "a.dll"}), encoding="utf-8")
    s = fz_settings.load(tmp_path)
    s.card_reader_name = "R"
    fz_settings.save(s, tmp_path)
    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["future_feature"] == {"x": 1}
    assert data["celik_dll_path"] == "a.dll" and data["card_reader_name"] == "R"


@pytest.mark.parametrize("content", ["{broken", "[]", ""])
def test_unreadable_settings_fall_back_to_defaults(tmp_path, content) -> None:
    (tmp_path / "settings.json").write_text(content, encoding="utf-8")
    assert fz_settings.load(tmp_path) == fz_settings.FormalizatorSettings()


# ── reader module ─────────────────────────────────────────────────

@pytest.mark.skipif(not BUNDLED_DLL.exists(), reason="bundled DLL not present")
def test_bundled_dll_version_is_readable() -> None:
    assert eid_reader.dll_version(BUNDLED_DLL).startswith("1.")


def test_a_non_dll_has_no_version(tmp_path) -> None:
    f = tmp_path / "CelikApi.dll"
    f.write_text("not a dll")
    assert eid_reader.dll_version(f) == ""


def test_chosen_reader_name_goes_to_the_dll() -> None:
    r = object.__new__(eid_reader.SerbianIDReader)
    r._reader_name = "OMNIKEY CardMan 3x21 0"
    assert r.get_reader_name() == b"OMNIKEY CardMan 3x21 0"
    r._reader_name = ""
    assert r.get_reader_name() == b"", "empty = DLL's first reader, as before"


def test_list_readers_never_raises() -> None:
    assert isinstance(eid_reader.list_readers(), list)


# ── fill-out screen uses the stored choices ───────────────────────

@pytest.fixture
def fillout(monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from formalizator.gui.fillout_screen import FilloutScreen
    s = FilloutScreen()
    yield s
    s.deleteLater()


def test_card_read_uses_the_configured_dll_and_reader(fillout, monkeypatch) -> None:
    fz_settings.save(fz_settings.FormalizatorSettings("D:/MUP/CelikApi.dll", "Reader B"))
    seen = {}

    class FakeReader:
        def __init__(self, dll_path=None, reader_name=""):
            seen.update(dll_path=dll_path, reader_name=reader_name)

        def startup(self):
            pass

        def read_card(self):
            raise eid_reader.EidReaderError(-1, "test")

    monkeypatch.setattr("formalizator.gui.fillout_screen.SerbianIDReader", FakeReader)
    monkeypatch.setattr("formalizator.gui.fillout_screen.QMessageBox.warning", lambda *a, **k: None)
    fillout._on_read_card()
    assert seen == {"dll_path": "D:/MUP/CelikApi.dll", "reader_name": "Reader B"}


def test_missing_dll_explains_instead_of_crashing(fillout, monkeypatch) -> None:
    fz_settings.save(fz_settings.FormalizatorSettings("Z:/nowhere/CelikApi.dll"))
    shown = []
    monkeypatch.setattr("formalizator.gui.fillout_screen.QMessageBox.critical",
                        lambda _p, title, text: shown.append((title, text)))
    fillout._on_read_card()  # real lookup: the configured file doesn't exist
    assert shown and "CelikApi.dll" in shown[0][1]
    assert fillout._reader is None, "a later attempt retries the lookup"


# ── setup screen box ──────────────────────────────────────────────

@pytest.fixture
def setup_screen(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(eid_reader, "list_readers", lambda: ["Reader A", "Reader B"])
    from formalizator.gui.setup_screen import SetupScreen
    s = SetupScreen(tmp_path / "templates", tmp_path)
    yield s
    s.deleteLater()


@pytest.mark.skipif(not BUNDLED_DLL.exists(), reason="bundled DLL not present")
def test_picking_a_newer_dll_is_saved_and_shown_with_its_version(setup_screen, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("formalizator.gui.setup_screen.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(BUNDLED_DLL), ""))
    setup_screen.btn_pick_dll.click()
    assert fz_settings.load().celik_dll_path == str(BUNDLED_DLL)
    assert "верзија 1." in setup_screen.lbl_dll.text()
    assert setup_screen.btn_default_dll.isEnabled()
    setup_screen.btn_default_dll.click()
    assert fz_settings.load().celik_dll_path == ""


def test_picking_a_non_dll_is_refused(setup_screen, monkeypatch, tmp_path) -> None:
    junk = tmp_path / "notes.dll"
    junk.write_text("nope")
    warned = []
    monkeypatch.setattr("formalizator.gui.setup_screen.QFileDialog.getOpenFileName",
                        lambda *a, **k: (str(junk), ""))
    monkeypatch.setattr("formalizator.gui.setup_screen.QMessageBox.warning",
                        lambda *a, **k: warned.append(1))
    setup_screen.btn_pick_dll.click()
    assert warned and fz_settings.load().celik_dll_path == ""


def test_reader_choice_is_listed_and_saved(setup_screen) -> None:
    items = [setup_screen.cb_reader.itemText(i) for i in range(setup_screen.cb_reader.count())]
    assert items == ["Први доступни читач", "Reader A", "Reader B"]
    setup_screen.cb_reader.setCurrentIndex(2)
    assert fz_settings.load().card_reader_name == "Reader B"


def test_remembered_reader_that_is_unplugged_stays_selectable(tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    fz_settings.save(fz_settings.FormalizatorSettings(card_reader_name="Old reader"))
    monkeypatch.setattr(eid_reader, "list_readers", lambda: ["Reader A"])
    from formalizator.gui.setup_screen import SetupScreen
    s = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        assert s.cb_reader.currentData() == "Old reader"
        assert "није прикључен" in s.cb_reader.currentText()
    finally:
        s.deleteLater()
