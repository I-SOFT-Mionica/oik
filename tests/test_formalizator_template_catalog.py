"""Tests for formalizator.core.template_catalog."""

from __future__ import annotations

from pathlib import Path

from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition
from formalizator.core.template_catalog import (
    find_by_name, load_catalog, remove_template, save_template,
)


def _template(name: str = "NPRS-3") -> CalibratedTemplate:
    return CalibratedTemplate(
        name=name, background_pdf_path="bg.pdf",
        positions=[FieldPosition(field_key="full_name", page_index=0, x=1.0, y=2.0)],
        form_id="NPRS-3", year="2026", municipality="Мионица",
    )


def test_load_catalog_empty_when_no_index(tmp_path: Path) -> None:
    assert load_catalog(tmp_path) == []


def test_save_and_load_round_trips(tmp_path: Path) -> None:
    save_template(tmp_path, _template())
    loaded = load_catalog(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].name == "NPRS-3"
    assert loaded[0].positions[0].field_key == "full_name"
    assert loaded[0].municipality == "Мионица"


def test_save_replaces_existing_entry_with_same_name(tmp_path: Path) -> None:
    save_template(tmp_path, _template())
    updated = _template()
    updated.municipality = "Уб"
    save_template(tmp_path, updated)

    loaded = load_catalog(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].municipality == "Уб"


def test_find_by_name(tmp_path: Path) -> None:
    save_template(tmp_path, _template("A"))
    save_template(tmp_path, _template("B"))

    assert find_by_name(tmp_path, "B").name == "B"
    assert find_by_name(tmp_path, "missing") is None


def test_remove_template(tmp_path: Path) -> None:
    save_template(tmp_path, _template("A"))
    save_template(tmp_path, _template("B"))

    remove_template(tmp_path, "A")

    names = {t.name for t in load_catalog(tmp_path)}
    assert names == {"B"}


def test_custom_fields_round_trip(tmp_path: Path) -> None:
    tpl = _template()
    tpl.custom_fields = [
        CustomFieldDef(key="overitelj_ime", label="Оверитељ — име и презиме", kind="universal"),
    ]
    save_template(tmp_path, tpl)

    loaded = find_by_name(tmp_path, "NPRS-3")
    assert loaded.custom_fields[0].key == "overitelj_ime"
    assert loaded.custom_fields[0].kind == "universal"
