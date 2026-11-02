"""Алати → Коверте: one envelope per selected polling station, sized and
oriented for the chosen envelope type."""

from __future__ import annotations

import pytest
from docx import Document
from docx.oxml.ns import qn

from biracki_odbor.core import envelopes
from biracki_odbor.core.models import PollingStation

STATIONS = [
    PollingStation(1, "ОШ Мионица", "Карађорђева 1", "Основна школа „Мионица“"),
    PollingStation(2, "МЗ Горња Горевница", "Главна бб", ""),
    PollingStation(3, "Дом културе Струганик", "Струганик бб", "Дом културе Струганик"),
]
CTX = envelopes.EnvelopeContext("Мионица", "Општинска изборна комисија општине Мионица", "Избори 2026")


def _pages(doc) -> int:
    return 1 + sum(1 for br in doc.element.body.iter(qn("w:br")) if br.get(qn("w:type")) == "page")


def _text(doc) -> str:
    return "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)


@pytest.mark.parametrize("env_type,long_mm,short_mm", [
    (envelopes.ENV_C4_POCKET, 324, 229),
    (envelopes.ENV_B5_WHITE_SL, 250, 176),
    (envelopes.ENV_B6_BB_SL, 176, 125),
])
def test_each_envelope_type_prints_landscape_at_its_size(tmp_path, env_type, long_mm, short_mm) -> None:
    out = envelopes.generate_envelopes(
        STATIONS, envelopes.EnvelopeSettings(env_type), CTX, tmp_path / "k.docx",
    )
    sec = Document(out).sections[0]
    assert round(sec.page_width.mm) == long_mm and round(sec.page_height.mm) == short_mm
    assert sec._sectPr.find(qn("w:vAlign")).get(qn("w:val")) == "center"


def test_one_envelope_per_station_with_its_own_number_and_name(tmp_path) -> None:
    out = envelopes.generate_envelopes(
        STATIONS, envelopes.EnvelopeSettings(), CTX, tmp_path / "k.docx",
    )
    doc = Document(out)
    assert _pages(doc) == 3
    text = _text(doc)
    for n in (1, 2, 3):
        assert f"БИРАЧКО МЕСТО БР. {n}" in text
    assert "ИЗБОРНИ МАТЕРИЈАЛ" in text
    assert "Основна школа „Мионица“" in text      # full name when set
    assert "МЗ Горња Горевница" in text            # short name otherwise


def test_placeholders_and_commission_fields(tmp_path) -> None:
    from biracki_odbor.core.observers import BLOCK_STATIC_TEXT, LegitimacijaBlock
    layout = [
        LegitimacijaBlock(envelopes.ENV_COMMISSION, col_span=6, alignment="left"),
        LegitimacijaBlock(envelopes.ENV_BM_ADDRESS, col_span=6, alignment="right"),
        LegitimacijaBlock(BLOCK_STATIC_TEXT, "БМ [bm] — [bm_name], [municipality]"),
    ]
    out = envelopes.generate_envelopes(
        STATIONS[:1], envelopes.EnvelopeSettings(envelopes.ENV_B5_WHITE_SL, layout), CTX,
        tmp_path / "k.docx",
    )
    text = _text(Document(out))
    assert "Општинска изборна комисија општине Мионица" in text
    assert "Карађорђева 1" in text
    assert "БМ 1 — Основна школа „Мионица“, Мионица" in text


def test_settings_round_trip_and_unknown_type_falls_back() -> None:
    s = envelopes.EnvelopeSettings(envelopes.ENV_B6_BB_SL)
    assert envelopes.EnvelopeSettings.from_dict(s.to_dict()).envelope_type == envelopes.ENV_B6_BB_SL
    assert envelopes.EnvelopeSettings.from_dict({"envelope_type": "nope"}).envelope_type == envelopes.ENV_C4_POCKET
    assert envelopes.EnvelopeSettings.from_dict({}).layout  # default layout


def test_no_stations_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        envelopes.generate_envelopes([], envelopes.EnvelopeSettings(), CTX, tmp_path / "k.docx")


# ── the Алати page ────────────────────────────────────────────────

@pytest.fixture
def page(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("biracki_odbor.gui.tabs.koverte_page.subprocess.Popen", lambda *a, **k: None)
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.koverte_page import KovertePage
    state = AppState()
    state.app_settings.default_files_dir = str(tmp_path / "export")
    state.oik.polling_stations = list(STATIONS)
    p = KovertePage(state)
    yield p
    p.deleteLater()


def test_page_prints_only_the_ticked_stations_into_the_export_folder(page) -> None:
    from PySide6.QtCore import Qt
    assert page.list_bm.count() == 3
    assert len(page.selected_stations()) == 3, "all ticked by default"
    page.list_bm.item(1).setCheckState(Qt.CheckState.Unchecked)
    page._type_combo.setCurrentIndex(page._type_combo.findData(envelopes.ENV_B5_WHITE_SL))
    page.btn_generate.click()

    exported = page.state.files_dir("Коверте") / envelopes.output_filename(envelopes.ENV_B5_WHITE_SL)
    doc = Document(exported)
    assert _pages(doc) == 2
    text = _text(doc)
    assert "БИРАЧКО МЕСТО БР. 1" in text and "БИРАЧКО МЕСТО БР. 3" in text
    assert "БИРАЧКО МЕСТО БР. 2" not in text
    assert round(doc.sections[0].page_width.mm) == 250


def test_page_remembers_type_and_layout(page) -> None:
    page._type_combo.setCurrentIndex(page._type_combo.findData(envelopes.ENV_B6_BB_SL))
    page._block_type_combo.setCurrentIndex(page._block_type_combo.findData(envelopes.ENV_BM_ADDRESS))
    page._add_block()
    saved = page.state.app_settings.koverte
    assert saved.envelope_type == envelopes.ENV_B6_BB_SL
    assert saved.layout[-1].block_type == envelopes.ENV_BM_ADDRESS
