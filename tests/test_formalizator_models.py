"""Tests for formalizator.core.models — VoterEntry's derived fields."""

from __future__ import annotations

from formalizator.core.models import (
    CalibratedTemplate, CustomFieldDef, DOCUMENT_TYPES, FieldPosition,
    SessionInfo, VoterEntry, auto_box_size,
)


def test_full_name_joins_given_and_surname() -> None:
    e = VoterEntry(given_name="Марко", surname="Марковић")
    assert e.full_name == "Марко Марковић"


def test_jmbg_digits_splits_into_13_keys() -> None:
    e = VoterEntry(jmbg="0101990123456")
    digits = e.jmbg_digits
    assert len(digits) == 13
    assert digits["jmbg_1"] == "0"
    assert digits["jmbg_13"] == "6"


def test_jmbg_digits_short_jmbg_pads_with_empty() -> None:
    e = VoterEntry(jmbg="123")
    digits = e.jmbg_digits
    assert digits["jmbg_1"] == "1"
    assert digits["jmbg_3"] == "3"
    assert digits["jmbg_4"] == ""
    assert digits["jmbg_13"] == ""


def test_to_dict_includes_full_name_and_jmbg_digits() -> None:
    e = VoterEntry(given_name="Ана", surname="Анић", jmbg="1234567890123")
    d = e.to_dict()
    assert d["full_name"] == "Ана Анић"
    assert d["jmbg_1"] == "1"
    assert d["source"] == "manual"


def test_source_defaults_to_manual() -> None:
    assert VoterEntry().source == "manual"


def test_calibrated_template_holds_positions() -> None:
    pos = FieldPosition(field_key="full_name", page_index=0, x=100.0, y=200.0)
    tpl = CalibratedTemplate(name="test", background_pdf_path="x.pdf", positions=[pos])
    assert tpl.positions[0].field_key == "full_name"


def test_document_type_defaults_to_id_card() -> None:
    assert VoterEntry().document_type == DOCUMENT_TYPES[0] == "Лична карта"


def test_to_dict_includes_document_type() -> None:
    e = VoterEntry(document_type="Пасош")
    assert e.to_dict()["document_type"] == "Пасош"


def test_session_info_defaults_one_copy_no_template() -> None:
    info = SessionInfo()
    assert info.copies == 1
    assert info.template_name == ""


def test_session_info_custom_values_default_empty() -> None:
    assert SessionInfo().custom_values == {}


def test_voter_entry_custom_values_flatten_into_to_dict() -> None:
    e = VoterEntry(custom_values={"overitelj_ime": "Петар Петровић"})
    assert e.to_dict()["overitelj_ime"] == "Петар Петровић"


def test_calibrated_template_holds_custom_fields() -> None:
    cf = CustomFieldDef(key="overitelj_ime", label="Оверитељ — име и презиме", kind="universal")
    tpl = CalibratedTemplate(name="t", background_pdf_path="x.pdf", custom_fields=[cf])
    assert tpl.custom_fields[0].kind == "universal"


def test_custom_field_def_defaults_to_individual() -> None:
    assert CustomFieldDef(key="k", label="L").kind == "individual"


def test_full_residence_joins_city_and_address() -> None:
    e = VoterEntry(city="Мионица", full_address="Иве Андрића 15")
    assert e.full_residence == "Мионица, Иве Андрића 15"


def test_full_residence_omits_missing_parts() -> None:
    assert VoterEntry(city="Мионица").full_residence == "Мионица"
    assert VoterEntry().full_residence == ""


def test_full_document_info_joins_type_number_date_authority() -> None:
    e = VoterEntry(
        document_type="Пасош", document_reg_no="1234567",
        date_of_issue="01.01.2020.", issuing_authority="МУП Мионица",
    )
    assert e.full_document_info == "Пасош, 1234567, 01.01.2020., МУП Мионица"


def test_full_document_info_omits_missing_parts() -> None:
    e = VoterEntry(document_type="Лична карта")
    assert e.full_document_info == "Лична карта"


def test_to_dict_includes_composite_fields() -> None:
    e = VoterEntry(city="Мионица", full_address="Иве Андрића 15", document_reg_no="123")
    d = e.to_dict()
    assert d["full_residence"] == "Мионица, Иве Андрића 15"
    assert "full_document_info" in d


def test_field_position_style_and_alignment_defaults() -> None:
    pos = FieldPosition(field_key="full_name", page_index=0, x=1.0, y=2.0)
    assert pos.bold is False
    assert pos.italic is False
    assert pos.align == "center"


def test_field_position_style_and_alignment_are_settable() -> None:
    pos = FieldPosition(
        field_key="full_name", page_index=0, x=1.0, y=2.0,
        bold=True, italic=True, align="right",
    )
    assert pos.bold is True
    assert pos.italic is True
    assert pos.align == "right"


# ── auto_box_size ────────────────────────────────────────────────────
#
# Shared by two callers that must never compute two different answers
# for the same field: the calibration wizard sizes a field's on-screen
# preview box from this, and overlay_fill.fill_declaration reuses it as
# the shrink-to-fit ceiling for a field nobody explicitly measured a
# width for.


def test_auto_box_size_is_narrow_for_a_jmbg_digit() -> None:
    """A generic field's default box (roughly 10 characters wide) would
    grossly overstate a single JMBG digit cell's real width."""
    digit_w, _ = auto_box_size("jmbg_1", 10.0)
    name_w, _ = auto_box_size("full_name", 10.0)

    assert digit_w < name_w


def test_auto_box_size_scales_with_font_size() -> None:
    small_w, _ = auto_box_size("full_name", 8.0)
    large_w, _ = auto_box_size("full_name", 20.0)

    assert large_w > small_w
