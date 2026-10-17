"""Regression test: ErrorTable.clear() must not wipe its header labels.

Field report: prosireni's Phase 2 tab called the inherited
QTableWidget.clear() before each run to blank the table while the
worker ran. QTableWidget.clear() also removes header labels (documented
Qt behaviour) -- nothing ever restored them, so after the first run the
table permanently showed Qt's default numeric "1 2 3 4 5" column
headers instead of "Озбиљност / Фајл / Ред / Колона / Слот / Порука".
"""

from __future__ import annotations

import pytest

from biracki_odbor.core.models import Issue, ValidationReport


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


_EXPECTED_HEADERS = ["Озбиљност", "Фајл", "Ред", "Колона / Слот", "Порука"]


def _header_labels(table) -> list[str]:
    return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]


def test_headers_set_at_construction(app) -> None:
    from biracki_odbor.gui.widgets.error_table import ErrorTable
    table = ErrorTable()
    assert _header_labels(table) == _EXPECTED_HEADERS


def test_clear_preserves_headers(app) -> None:
    from biracki_odbor.gui.widgets.error_table import ErrorTable
    table = ErrorTable()
    table.set_report(ValidationReport(issues=[
        Issue(code="X", message_sr="test", severity="info", file="a.xlsx"),
    ]))
    assert table.rowCount() == 1

    table.clear()

    assert table.rowCount() == 0
    assert _header_labels(table) == _EXPECTED_HEADERS


def test_set_report_after_clear_still_shows_correct_headers(app) -> None:
    """The exact prosireni bug scenario: clear() before a run, then
    set_report() with the new results — headers must survive both."""
    from biracki_odbor.gui.widgets.error_table import ErrorTable
    table = ErrorTable()
    table.clear()
    table.set_report(ValidationReport(issues=[
        Issue(code="X", message_sr="test", severity="warning", file="b.xlsx"),
    ]))
    assert _header_labels(table) == _EXPECTED_HEADERS
    assert table.rowCount() == 1
