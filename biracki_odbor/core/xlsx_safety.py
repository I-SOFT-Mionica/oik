"""Guard against Excel formula auto-promotion at the point cells are written.

openpyxl treats any string value starting with "=" as a live formula
the instant `.value` is set (`data_type` becomes `'f'`) — Excel then
evaluates it the moment the workbook is opened, no click required.
This isn't only a hostile-external-input concern: an OIK operator
typing a name, address, or note that happens to start with "=" (or
"+", "-", "@" — Excel's other formula/DDE trigger characters) trips
the exact same auto-promotion by accident, whether the text came from
a party's submitted Excel file or was typed directly into a settings
field. Rather than enumerate which fields are "trusted" and which
aren't, every string written to a data cell across this app's Excel
writers goes through here.
"""

from __future__ import annotations

from typing import Any

from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet


def safe_cell(ws: Worksheet, row: int, column: int, value: Any = None) -> Cell:
    """Drop-in replacement for `ws.cell(row=, column=, value=)` that
    never lets openpyxl auto-promote a leading =/+/-/@ string into a
    live formula. Non-string values (numbers, None, ...) pass through
    unchanged.

    NOT for cells that should hold a real, app-authored formula (e.g.
    `=COUNTA(...)`) — write those with a plain `ws.cell(...)` call.
    """
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell
