"""Displays a ValidationReport as a sortable table the operator can scan."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

from biracki_odbor.core.models import Issue, ValidationReport
from biracki_odbor.gui import style as st


_SEVERITY_LABEL = {
    "error": "Грешка",
    "warning": "Упозорење",
    "info": "Инфо",
}


class ErrorTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels([
            "Озбиљност", "Фајл", "Ред", "Колона / Слот", "Порука",
        ])
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.resizeSection(0, 110)
        header.resizeSection(1, 220)
        header.resizeSection(2, 60)
        header.resizeSection(3, 180)

    def clear(self) -> None:
        """Override QTableWidget.clear() -- it also wipes the header
        labels set in __init__, with nothing to restore them, leaving
        Qt's default numeric "1 2 3 4 5" column headers behind (a real
        bug: prosireni's Phase 2 called .clear() before each run and
        silently lost its headers after the first one). Row-only clear
        is what every caller actually wants."""
        self.setRowCount(0)

    def set_report(self, report: ValidationReport) -> None:
        self.setSortingEnabled(False)
        self.setRowCount(0)
        for issue in report.issues:
            self._append(issue)
        self.setSortingEnabled(True)
        self.sortItems(0, Qt.AscendingOrder)

    def _append(self, issue: Issue) -> None:
        row = self.rowCount()
        self.insertRow(row)
        severity = _SEVERITY_LABEL.get(issue.severity, issue.severity)
        color = self._color_for(issue.severity)

        items = [
            QTableWidgetItem(severity),
            QTableWidgetItem(issue.file or ""),
            QTableWidgetItem(str(issue.row) if issue.row is not None else ""),
            QTableWidgetItem(
                str(issue.column) if issue.column is not None
                else (issue.sheet or issue.detail or "")
            ),
            QTableWidgetItem(issue.message_sr),
        ]
        for col, item in enumerate(items):
            if color is not None:
                item.setBackground(QColor(color))
            self.setItem(row, col, item)

    @staticmethod
    def _color_for(severity: str) -> str | None:
        return {
            "error": st.ERROR_BG,
            "warning": st.WARN_BG,
        }.get(severity)
