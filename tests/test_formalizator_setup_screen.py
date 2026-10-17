"""Tests for formalizator.gui.setup_screen — specifically the ordering
of universal ("once per session") custom fields."""

from __future__ import annotations

from pathlib import Path

import pytest

from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _template_with_universal_fields(fields_and_positions):
    """fields_and_positions: [(key, label, page_index, y)] — y in PDF
    points, where larger means higher up the page."""
    return CalibratedTemplate(
        name="t", background_pdf_path="",
        custom_fields=[
            CustomFieldDef(key=key, label=label, kind="universal")
            for key, label, _page, _y in fields_and_positions
        ],
        positions=[
            FieldPosition(field_key=key, page_index=page, x=100.0, y=y)
            for key, _label, page, y in fields_and_positions if y is not None
        ],
    )


def _universal_labels(screen) -> list[str]:
    return [
        screen.custom_universal_form.itemAt(row, screen.custom_universal_form.ItemRole.LabelRole).widget().text()
        for row in range(screen.custom_universal_form.rowCount())
    ]


def test_universal_fields_are_ordered_down_the_page_not_by_definition_order(app, tmp_path: Path) -> None:
    """Reported directly: "Листа" and "подносилац" showed up as table
    rows 8 and 9 (i.e. defined out of page order), and the setup
    screen showed them in that same defined order instead of following
    the actual document."""
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template_with_universal_fields([
            ("bottom", "Дно", 0, 100.0),
            ("top", "Врх", 0, 700.0),
            ("middle", "Средина", 0, 400.0),
        ])

        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert _universal_labels(screen) == ["Врх:", "Средина:", "Дно:"]
    finally:
        screen.deleteLater()


def test_universal_fields_on_a_later_page_come_after_earlier_pages(app, tmp_path: Path) -> None:
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template_with_universal_fields([
            ("p2_top", "Друга страна", 1, 700.0),
            ("p1_bottom", "Прва страна", 0, 100.0),
        ])

        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert _universal_labels(screen) == ["Прва страна:", "Друга страна:"]
    finally:
        screen.deleteLater()


def test_never_placed_universal_fields_keep_their_order_at_the_end(app, tmp_path: Path) -> None:
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = _template_with_universal_fields([
            ("unplaced_a", "Без А", 0, None),
            ("placed", "Постављено", 0, 500.0),
            ("unplaced_b", "Без Б", 0, None),
        ])

        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert _universal_labels(screen) == ["Постављено:", "Без А:", "Без Б:"]
    finally:
        screen.deleteLater()


def test_individual_custom_fields_stay_off_this_screen(app, tmp_path: Path) -> None:
    """Per-voter values are typed on the fill-out screen, so reordering
    must not accidentally pull them in here."""
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        template = CalibratedTemplate(
            name="t", background_pdf_path="",
            custom_fields=[
                CustomFieldDef(key="napomena", label="Напомена", kind="individual"),
                CustomFieldDef(key="overitelj", label="Оверитељ", kind="universal"),
            ],
            positions=[FieldPosition(field_key="napomena", page_index=0, x=1.0, y=700.0)],
        )

        screen._rebuild_custom_universal_fields(template)  # noqa: SLF001

        assert _universal_labels(screen) == ["Оверитељ:"]
    finally:
        screen.deleteLater()


def test_no_template_leaves_the_section_empty(app, tmp_path: Path) -> None:
    from formalizator.gui.setup_screen import SetupScreen

    screen = SetupScreen(tmp_path / "templates", tmp_path)
    try:
        screen._rebuild_custom_universal_fields(None)  # noqa: SLF001

        assert screen.custom_universal_form.rowCount() == 0
    finally:
        screen.deleteLater()


# ── Printer choice ───────────────────────────────────────────────────
#
# Reported from the field: on a domain-managed machine the default
# printer is set by Group Policy and reapplied, so changing it locally
# does not stick and the declarations kept going to the office printer.
# Naming the printer for the sitting is the only reliable answer.


def _setup_with_printers(app, tmp_path: Path, monkeypatch, names: list[str]):
    import formalizator.core.print_pdf as print_pdf
    from formalizator.gui.setup_screen import SetupScreen

    monkeypatch.setattr(print_pdf, "list_real_printers", lambda: names)
    return SetupScreen(tmp_path / "templates", tmp_path)


def _printer_items(screen) -> list[str]:
    return [screen.cb_printer.itemText(i) for i in range(screen.cb_printer.count())]


def test_the_printer_picker_lists_the_real_printers(app, tmp_path: Path, monkeypatch) -> None:
    screen = _setup_with_printers(app, tmp_path, monkeypatch, ["HP LaserJet 1020", "Canon MF3010"])
    try:
        assert "HP LaserJet 1020" in _printer_items(screen)
        assert "Canon MF3010" in _printer_items(screen)
    finally:
        screen.deleteLater()


def test_the_picker_defaults_to_following_windows(app, tmp_path: Path, monkeypatch) -> None:
    """Unchanged behaviour for anyone who never touches it: an empty
    choice means "follow the Windows default", with the virtual-printer
    rescue in core.print_pdf still applied on top."""
    screen = _setup_with_printers(app, tmp_path, monkeypatch, ["HP LaserJet 1020"])
    try:
        assert screen.cb_printer.currentData() == ""
    finally:
        screen.deleteLater()


def test_virtual_printers_are_not_offered(app, tmp_path: Path, monkeypatch) -> None:
    """Offering "Microsoft Print to PDF" here would be a one-click way
    to silently produce a file instead of a signed declaration — the
    exact failure this app has already been bitten by. list_real_printers
    filters them, and the picker must not reintroduce them."""
    screen = _setup_with_printers(
        app, tmp_path, monkeypatch, ["HP LaserJet 1020"],  # already filtered upstream
    )
    try:
        assert not any("Print to PDF" in item for item in _printer_items(screen))
    finally:
        screen.deleteLater()


def test_a_previously_chosen_printer_that_vanished_is_kept_and_flagged(
    app, tmp_path: Path, monkeypatch,
) -> None:
    """Silently reverting to the default would start printing somewhere
    else without saying so."""
    from formalizator.core.models import SessionInfo

    screen = _setup_with_printers(app, tmp_path, monkeypatch, ["HP LaserJet 1020"])
    try:
        screen.load_from_info(SessionInfo(template_name="t", printer_name="Odsutni Stampac"))

        assert screen.cb_printer.currentData() == "Odsutni Stampac"
        assert "недоступан" in screen.cb_printer.currentText()
    finally:
        screen.deleteLater()


def test_refreshing_keeps_the_current_choice(app, tmp_path: Path, monkeypatch) -> None:
    """Printers get plugged in mid-session; refreshing must not reset
    what the operator already selected."""
    screen = _setup_with_printers(app, tmp_path, monkeypatch, ["HP LaserJet 1020"])
    try:
        screen.cb_printer.setCurrentIndex(screen.cb_printer.findData("HP LaserJet 1020"))

        import formalizator.core.print_pdf as print_pdf
        monkeypatch.setattr(print_pdf, "list_real_printers", lambda: ["HP LaserJet 1020", "Canon MF3010"])
        screen._reload_printers()  # noqa: SLF001

        assert screen.cb_printer.currentData() == "HP LaserJet 1020"
        assert "Canon MF3010" in _printer_items(screen)
    finally:
        screen.deleteLater()
