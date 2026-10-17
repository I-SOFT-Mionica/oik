"""Tests for CustomFieldDef.default_value — pre-filling a custom
field's edit box instead of starting every session/voter blank."""

from __future__ import annotations

from pathlib import Path

import pytest

from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _template(fields: list[CustomFieldDef]) -> CalibratedTemplate:
    return CalibratedTemplate(
        name="t", background_pdf_path="",
        custom_fields=fields,
        positions=[FieldPosition(field_key=cf.key, page_index=0, x=1.0, y=1.0) for cf in fields],
    )


# ── SetupScreen: universal ("once per session") fields ──────────────


def test_universal_field_prefills_its_default(app, tmp_path: Path) -> None:
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template([
            CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal", default_value="Наташа Пауновић"),
        ])
        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert screen._custom_universal_edits["overitelj"].text() == "Наташа Пауновић"  # noqa: SLF001
    finally:
        screen.deleteLater()


def test_universal_field_with_no_default_stays_blank(app, tmp_path: Path) -> None:
    """No behaviour change for fields that never set one."""
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template([CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal")])
        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert screen._custom_universal_edits["overitelj"].text() == ""  # noqa: SLF001
    finally:
        screen.deleteLater()


def test_resuming_a_session_overrides_the_default_with_the_saved_value(app, tmp_path: Path) -> None:
    """A default is a starting point, not a sticky override — a
    resumed session's actual saved value must win."""
    from formalizator.core.models import SessionInfo
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template([
            CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal", default_value="Наташа Пауновић"),
        ])
        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        screen.load_from_info(SessionInfo(custom_values={"overitelj": "Јован Јовановић"}))

        assert screen._custom_universal_edits["overitelj"].text() == "Јован Јовановић"  # noqa: SLF001
    finally:
        screen.deleteLater()


# ── FilloutScreen: individual ("once per voter") fields ──────────────


def test_individual_field_prefills_its_default(app) -> None:
    from formalizator.gui.fillout_screen import FilloutScreen

    screen = FilloutScreen()
    try:
        template = _template([
            CustomFieldDef(key="napomena", label="Напомена", kind="individual", default_value="Нема"),
        ])
        screen.set_template(template)

        assert screen._custom_edits["napomena"].text() == "Нема"  # noqa: SLF001
    finally:
        screen.deleteLater()


def test_clearing_after_print_reapplies_the_default_not_blank(app) -> None:
    """The whole point: a default has to survive every voter in the
    session, not just the first one — _clear_fields() ran a plain
    .clear() on every custom field, which would wipe it after voter 1."""
    from formalizator.gui.fillout_screen import FilloutScreen

    screen = FilloutScreen()
    try:
        template = _template([
            CustomFieldDef(key="napomena", label="Напомена", kind="individual", default_value="Нема"),
        ])
        screen.set_template(template)
        screen._custom_edits["napomena"].setText("нешто друго за овог бирача")  # noqa: SLF001

        screen._clear_fields()  # noqa: SLF001

        assert screen._custom_edits["napomena"].text() == "Нема"  # noqa: SLF001
    finally:
        screen.deleteLater()


def test_individual_field_with_no_default_still_clears_to_blank(app) -> None:
    from formalizator.gui.fillout_screen import FilloutScreen

    screen = FilloutScreen()
    try:
        template = _template([CustomFieldDef(key="napomena", label="Напомена", kind="individual")])
        screen.set_template(template)
        screen._custom_edits["napomena"].setText("typed value")  # noqa: SLF001

        screen._clear_fields()  # noqa: SLF001

        assert screen._custom_edits["napomena"].text() == ""  # noqa: SLF001
    finally:
        screen.deleteLater()


# ── Persistence ────────────────────────────────────────────────────


def test_default_value_round_trips_through_the_template_catalog(tmp_path: Path) -> None:
    from formalizator.core import template_catalog

    template = _template([
        CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal", default_value="Наташа Пауновић"),
    ])
    template_catalog.save_template(tmp_path, template)

    loaded = template_catalog.find_by_name(tmp_path, "t")

    assert loaded.custom_fields[0].default_value == "Наташа Пауновић"


def test_default_value_absent_in_older_saved_catalogs_reads_as_blank(tmp_path: Path) -> None:
    """A catalog saved before this field existed has no such key at
    all — must not crash, must default to today's blank behaviour."""
    import json

    (tmp_path / "catalog.json").write_text(json.dumps([{
        "name": "t", "background_pdf_path": "", "positions": [],
        "custom_fields": [{"key": "overitelj", "label": "Оверитељ", "kind": "universal"}],
    }]), encoding="utf-8")

    from formalizator.core import template_catalog
    loaded = template_catalog.find_by_name(tmp_path, "t")

    assert loaded.custom_fields[0].default_value == ""
