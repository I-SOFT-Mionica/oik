"""Tests for formalizator.gui.fillout_screen — the per-voter data entry
screen shared by chip reads and manual typing."""

from __future__ import annotations

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(app):
    from formalizator.gui.fillout_screen import FilloutScreen
    s = FilloutScreen()
    yield s
    s.deleteLater()


def test_typing_a_jmbg_fills_in_the_date_of_birth(screen) -> None:
    """The first seven digits of a JMBG *are* the birth date, so a
    manual entry shouldn't have to type it a second time. The exact
    string matters too: a real card read of this JMBG stores
    "23.08.1985", and the same person must not export differently
    depending on how they were entered."""
    screen.ed_jmbg.setText("2308985774805")

    assert screen.ed_date_of_birth.text() == "23.08.1985"


def test_partial_jmbg_leaves_the_date_alone(screen) -> None:
    """Nothing should flicker into the date field while the operator is
    still mid-way through typing the number."""
    for partial in ("2", "23", "230898", "230898577003"):
        screen.ed_jmbg.setText(partial)
        assert screen.ed_date_of_birth.text() == ""


def test_impossible_date_in_a_jmbg_leaves_the_date_alone(screen) -> None:
    screen.ed_jmbg.setText("3202985770036")  # 32nd of February

    assert screen.ed_date_of_birth.text() == ""


def test_correcting_the_jmbg_updates_the_derived_date(screen) -> None:
    screen.ed_jmbg.setText("2308985774805")
    assert screen.ed_date_of_birth.text() == "23.08.1985"

    screen.ed_jmbg.setText("0101990710001")

    assert screen.ed_date_of_birth.text() == "01.01.1990"


def _template_with_custom_fields(fields_and_positions):
    """fields_and_positions: [(key, label, page_index, y)] — y in PDF
    points, where larger means higher up the page."""
    from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition

    return CalibratedTemplate(
        name="t", background_pdf_path="",
        custom_fields=[
            CustomFieldDef(key=key, label=label, kind="individual")
            for key, label, _page, _y in fields_and_positions
        ],
        positions=[
            FieldPosition(field_key=key, page_index=page, x=100.0, y=y)
            for key, _label, page, y in fields_and_positions if y is not None
        ],
    )


def _custom_labels(screen) -> list[str]:
    return [
        screen.custom_form.itemAt(row, screen.custom_form.ItemRole.LabelRole).widget().text()
        for row in range(screen.custom_form.rowCount())
    ]


def test_custom_fields_are_ordered_down_the_page_not_by_definition_order(screen) -> None:
    """Reported directly: fields belonging at the top of the document
    showed up as rows 8 and 11 in the typing form, so filling the page
    by hand meant jumping around it."""
    template = _template_with_custom_fields([
        ("bottom", "Дно", 0, 100.0),
        ("top", "Врх", 0, 700.0),
        ("middle", "Средина", 0, 400.0),
    ])

    screen.set_template(template)

    assert _custom_labels(screen) == ["Врх:", "Средина:", "Дно:"]


def test_custom_fields_on_a_later_page_come_after_earlier_pages(screen) -> None:
    template = _template_with_custom_fields([
        ("p2_top", "Друга страна", 1, 700.0),
        ("p1_bottom", "Прва страна", 0, 100.0),
    ])

    screen.set_template(template)

    assert _custom_labels(screen) == ["Прва страна:", "Друга страна:"]


def test_never_placed_custom_fields_keep_their_order_at_the_end(screen) -> None:
    """A field with no position can't be ordered by the page, so it
    shouldn't be able to jump ahead of one that can."""
    template = _template_with_custom_fields([
        ("unplaced_a", "Без А", 0, None),
        ("placed", "Постављено", 0, 500.0),
        ("unplaced_b", "Без Б", 0, None),
    ])

    screen.set_template(template)

    assert _custom_labels(screen) == ["Постављено:", "Без А:", "Без Б:"]


def test_universal_custom_fields_stay_off_this_screen(screen) -> None:
    """Session-fixed values are typed once on the setup screen, so
    reordering must not accidentally pull them in here."""
    from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition

    template = CalibratedTemplate(
        name="t", background_pdf_path="",
        custom_fields=[
            CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal"),
            CustomFieldDef(key="napomena", label="Напомена", kind="individual"),
        ],
        positions=[FieldPosition(field_key="overitelj", page_index=0, x=1.0, y=700.0)],
    )

    screen.set_template(template)

    assert _custom_labels(screen) == ["Напомена:"]


def test_a_card_read_keeps_the_chips_own_date(screen) -> None:
    """Setting the JMBG derives a date, but the chip's own value is
    authoritative and must win — the card is applied field by field
    with the JMBG first."""
    from formalizator.core.models import VoterEntry

    screen._apply_entry_to_fields(VoterEntry(  # noqa: SLF001
        given_name="СТЕВАН", surname="СТЕВИЋ",
        jmbg="2308985774805", date_of_birth="23.08.1985", source="card",
    ))

    assert screen.ed_date_of_birth.text() == "23.08.1985"


def test_a_print_failure_still_records_the_entry(screen, monkeypatch, tmp_path) -> None:
    """The bug that cost real field time: printing raised OSError (no
    app registered for the PDF "print" verb), which escaped the slot
    uncaught — so Штампај did nothing visible AND the entry was never
    emitted. The voter has already signed by then; their record must
    survive a printer problem."""
    import formalizator.gui.fillout_screen as mod
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    monkeypatch.setattr(
        mod, "print_pdf",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("No application is associated")),
    )
    monkeypatch.setattr(mod, "fill_declaration", lambda *a, **kw: None)
    warned = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: warned.append(a))

    recorded = []
    screen.entry_printed.connect(recorded.append)
    screen.set_template(CalibratedTemplate(
        name="t", background_pdf_path="",
        positions=[FieldPosition(field_key="full_name", page_index=0, x=1.0, y=1.0)],
    ))
    screen.ed_given_name.setText("Стеван")
    screen.ed_surname.setText("Стевић")
    screen.ed_jmbg.setText("2308985774805")

    screen._on_print()  # noqa: SLF001

    assert len(recorded) == 1, "entry must be recorded even when printing fails"
    assert recorded[0].surname == "Стевић"
    assert warned, "operator must be told printing failed"


def test_a_successful_print_records_the_entry_without_warning(screen, monkeypatch) -> None:
    import formalizator.gui.fillout_screen as mod
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    monkeypatch.setattr(mod, "print_pdf", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "fill_declaration", lambda *a, **kw: None)
    warned = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: warned.append(a))

    recorded = []
    screen.entry_printed.connect(recorded.append)
    screen.set_template(CalibratedTemplate(
        name="t", background_pdf_path="",
        positions=[FieldPosition(field_key="full_name", page_index=0, x=1.0, y=1.0)],
    ))
    screen.ed_given_name.setText("Ана")
    screen.ed_surname.setText("Анић")
    screen.ed_jmbg.setText("2308985774805")

    screen._on_print()  # noqa: SLF001

    assert len(recorded) == 1
    assert warned == []


# ── JMBG entry validation ────────────────────────────────────────────
#
# Reported from the field: the JMBG box accepted free text of any
# length. Worse than it sounds — `jmbg.normalize()` maps anything
# non-numeric to "", and the print-time check read `if entry.jmbg and
# ...`, so typed rubbish arrived as *empty* and was explicitly allowed
# through, printing a declaration and exporting an NPRS-4 row with a
# blank ЈМБГ column.


def _type(field, text: str) -> None:
    """Go through the validator the way a keyboard does.

    `setText()` bypasses QValidator entirely, so a test that used it
    would pass while the real field still accepted anything."""
    from PySide6.QtGui import QValidator

    validator = field.validator()
    field.clear()
    for ch in text:
        candidate = field.text() + ch
        state, fixed, _ = validator.validate(candidate, len(candidate))
        if state != QValidator.Invalid:
            field.setText(fixed if isinstance(fixed, str) else candidate)


def test_letters_never_reach_the_jmbg_field(screen) -> None:
    _type(screen.ed_jmbg, "abcdef")

    assert screen.ed_jmbg.text() == ""


def test_letters_mixed_with_digits_are_filtered_at_the_keystroke(screen) -> None:
    _type(screen.ed_jmbg, "23o08985a774805")

    assert screen.ed_jmbg.text() == "2308985774805"


def test_the_jmbg_field_stops_at_thirteen_digits(screen) -> None:
    _type(screen.ed_jmbg, "23089857748059999")

    assert screen.ed_jmbg.text() == "2308985774805"


def test_a_complete_but_wrong_jmbg_is_marked_invalid(screen) -> None:
    screen.ed_jmbg.setText("2308985770037")  # last digit breaks MOD 11

    assert screen.ed_jmbg.property("invalid") is True


def test_a_valid_jmbg_is_not_marked_invalid(screen) -> None:
    screen.ed_jmbg.setText("2308985774805")

    assert screen.ed_jmbg.property("invalid") is False


def test_a_half_typed_jmbg_is_not_nagged_about(screen) -> None:
    """Marking a field red while the operator is still typing trains
    them to ignore the red."""
    for partial in ("2", "2308", "230898577003"):
        screen.ed_jmbg.setText(partial)
        assert screen.ed_jmbg.property("invalid") is False, partial


def test_clearing_the_field_clears_the_invalid_mark(screen) -> None:
    screen.ed_jmbg.setText("2308985770037")
    assert screen.ed_jmbg.property("invalid") is True

    screen.ed_jmbg.setText("")

    assert screen.ed_jmbg.property("invalid") is False


def _armed_screen(screen, monkeypatch):
    """A screen with a template set and printing stubbed, ready for
    _on_print to be driven directly."""
    import formalizator.gui.fillout_screen as mod
    from formalizator.core.models import CalibratedTemplate, FieldPosition

    monkeypatch.setattr(mod, "print_pdf", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "fill_declaration", lambda *a, **kw: None)
    warned = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **kw: warned.append(a))
    recorded = []
    screen.entry_printed.connect(recorded.append)
    screen.set_template(CalibratedTemplate(
        name="t", background_pdf_path="",
        positions=[FieldPosition(field_key="full_name", page_index=0, x=1.0, y=1.0)],
    ))
    screen.ed_given_name.setText("Ана")
    screen.ed_surname.setText("Анић")
    return warned, recorded


def test_printing_is_refused_without_a_jmbg(screen, monkeypatch) -> None:
    """The exact escape route: an empty JMBG passed the old check, so a
    declaration printed and an NPRS-4 row was recorded with a blank
    ЈМБГ column — discovered only when the sheets are merged by hand in
    Belgrade."""
    warned, recorded = _armed_screen(screen, monkeypatch)

    screen._on_print()  # noqa: SLF001

    assert recorded == [], "an entry with no JMBG must not be recorded"
    assert warned, "the operator must be told why nothing printed"


def test_printing_is_refused_when_the_jmbg_fails_mod_11(screen, monkeypatch) -> None:
    warned, recorded = _armed_screen(screen, monkeypatch)
    screen.ed_jmbg.setText("2308985770037")

    screen._on_print()  # noqa: SLF001

    assert recorded == []
    assert warned


def test_a_refused_jmbg_is_marked_and_focused(screen, monkeypatch) -> None:
    """Refusing without showing which field is wrong just moves the
    confusion somewhere else."""
    _armed_screen(screen, monkeypatch)

    screen._on_print()  # noqa: SLF001

    assert screen.ed_jmbg.property("invalid") is True


def test_a_valid_jmbg_still_prints_and_records(screen, monkeypatch) -> None:
    """The gate must not become the new way printing silently fails."""
    warned, recorded = _armed_screen(screen, monkeypatch)
    screen.ed_jmbg.setText("2308985774805")

    screen._on_print()  # noqa: SLF001

    assert len(recorded) == 1
    assert warned == []
