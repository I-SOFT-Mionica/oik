"""First-run wizard: after finishing it, nothing should require opening
Поставке ИК -- municipality code, Vojvodina, case forms, commission name,
export folder and full polling-station names must all be in place."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from PySide6.QtWidgets import QMessageBox, QPushButton

from biracki_odbor.config import opstine as opstine_mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    warnings: list[str] = []
    opened: list[Path] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(
        "biracki_odbor.gui.dialogs.setup_wizard.os.startfile",
        lambda p: opened.append(Path(p)), raising=False,
    )
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.dialogs.setup_wizard import SetupWizard
    state = AppState()
    wiz = SetupWizard(state)
    return wiz, state, tmp_path, warnings, opened


def _pick(wiz, name: str) -> None:
    wiz._on_municipality_activated(wiz.cb_municipality.findText(name))


def _fill_template(path: Path, rows: list[tuple]) -> None:
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    wb.save(path)


def test_full_flow_saves_everything_a_decision_needs(env) -> None:
    wiz, state, tmp, warnings, opened = env
    _pick(wiz, "Мионица")
    wiz._ed_chairman.setText("Пера Перић")
    wiz._ed_email.setText("oik@mionica.rs")
    assert wiz._oik_page_valid()

    folder = tmp / "Izvoz"
    wiz._ed_folder.setText(str(folder))
    assert wiz._folder_page_valid()

    wiz._make_station_template()
    template = folder / "Бирачка места" / "bm.xlsx"
    assert opened == [template]
    _fill_template(template, [
        (1, "ОШ Милан Муњас", "Мионица, Војводе Мишића 2", None),
        (2, "Дом културе", "", None),
    ])
    wiz._import_stations_from(template)
    assert wiz._stations_page_valid()

    wiz._type_checks["parliamentary"].setChecked(True)
    wiz._save_all()
    assert warnings == []

    from biracki_odbor.gui.app_state import AppState
    fresh = AppState()
    mun = fresh.oik.municipality
    assert (mun.name, mun.sifra_opstine, mun.is_vojvodina) == ("Мионица", "70831", False)
    assert mun.name_genitive and mun.name_locative
    assert mun.full_committee_name == "Општинска изборна комисија у општини Мионица"
    assert fresh.oik.chairman.name == "Пера Перић"
    assert [s.full_name for s in fresh.oik.polling_stations] == [
        "ОШ Милан Муњас, Мионица, Војводе Мишића 2", "Дом културе",
    ]
    assert fresh.app_settings.default_files_dir == str(folder)
    assert fresh.app_settings.oik_email == "oik@mionica.rs"
    assert fresh.onboarding_complete


def test_vojvodina_derived_from_registry(env) -> None:
    wiz, *_ = env
    _pick(wiz, "Нови Сад - град")
    assert wiz._selected_entry().is_vojvodina
    assert "Vojvodina" in wiz.lbl_municipality_info.text() or "Војводин" in wiz.lbl_municipality_info.text()
    assert sum(e.is_vojvodina for e in opstine_mod.load_registry()) == 45


def test_free_text_municipality_is_not_accepted(env) -> None:
    wiz, _state, _tmp, warnings, _ = env
    wiz.cb_municipality.lineEdit().setText("Mionica")
    wiz._on_municipality_typed()
    wiz._ed_chairman.setText("Пера Перић")
    assert not wiz._oik_page_valid()
    assert warnings

    wiz.cb_municipality.lineEdit().setText("Мионица")
    wiz._on_municipality_typed()
    assert wiz._oik_page_valid()


def test_chairman_is_required(env) -> None:
    wiz, _state, _tmp, warnings, _ = env
    _pick(wiz, "Мионица")
    assert not wiz._oik_page_valid()
    assert warnings


def test_existing_template_is_opened_not_overwritten(env, monkeypatch) -> None:
    wiz, _state, tmp, _w, opened = env
    wiz._ed_folder.setText(str(tmp / "f"))
    assert wiz._folder_page_valid()
    wiz._make_station_template()
    template = opened[0]
    _fill_template(template, [(7, "Школа", "", None)])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    wiz._make_station_template()
    wiz._import_stations_from(template)
    assert list(wiz._stations) == [7]


def test_done_page_only_points_to_election_configuration(env) -> None:
    wiz, *_ = env
    from biracki_odbor.gui.dialogs.setup_wizard import _P_DONE
    texts = [b.text() for b in wiz._stack.widget(_P_DONE).findChildren(QPushButton)]
    assert not any("Settings" in t or "Поставке" in t for t in texts)
    assert any("Election configuration" in t or "Изборна" in t for t in texts)
