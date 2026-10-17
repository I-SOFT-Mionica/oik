"""Fill and print many voters' declarations at once, from a .xlsx/.csv
file instead of one card read or manual entry per person.

Two steps, both inside this one dialog: pick a file and review every
row (nothing prints yet — a row with a bad ЈМБГ is shown, not silently
skipped or silently accepted), then confirm to run the same fill+print
pipeline `FilloutScreen._process_entry` already uses for a single
interactive entry, once per valid row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from formalizator.core import bulk_import
from formalizator.core.models import CalibratedTemplate, VoterEntry

# Columns: row #, name, ЈМБГ, status. Kept narrow on purpose — this is a
# pre-flight review, not a data grid to edit in place; a wrong row gets
# fixed in the source file and re-imported, not patched cell-by-cell
# here (Excel is already the right tool for that).
_COL_ROW, _COL_NAME, _COL_JMBG, _COL_STATUS = range(4)


class BulkImportDialog(QDialog):
    def __init__(
        self,
        template: CalibratedTemplate,
        process_entry: Callable[[VoterEntry], tuple[VoterEntry, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._template = template
        self._process_entry = process_entry
        self._result: bulk_import.ImportResult | None = None
        self._path: Path | None = None

        self.setWindowTitle("Увоз из фајла")
        self.setMinimumSize(640, 480)

        root = QVBoxLayout(self)

        hint = QLabel(
            "Учитајте .xlsx или .csv фајл са подацима за више особа —"
            " попуниће се и одштампати изјава за сваки исправан ред,"
            " као да сте их унели ручно један по један."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        template_row = QHBoxLayout()
        self.btn_template_xlsx = QPushButton("Преузми празан шаблон (Excel)")
        self.btn_template_xlsx.clicked.connect(lambda: self._save_template(".xlsx"))
        template_row.addWidget(self.btn_template_xlsx)
        self.btn_template_csv = QPushButton("Преузми празан шаблон (CSV)")
        self.btn_template_csv.clicked.connect(lambda: self._save_template(".csv"))
        template_row.addWidget(self.btn_template_csv)
        template_row.addStretch()
        root.addLayout(template_row)

        pick_row = QHBoxLayout()
        self.btn_pick = QPushButton("Изабери фајл…")
        self.btn_pick.clicked.connect(self._on_pick_file)
        pick_row.addWidget(self.btn_pick)
        self.lbl_file = QLabel("Није изабран фајл.")
        self.lbl_file.setObjectName("MutedLabel")
        pick_row.addWidget(self.lbl_file, stretch=1)
        root.addLayout(pick_row)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        root.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ред", "Име и презиме", "ЈМБГ", "Статус"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_COL_STATUS, QHeaderView.Stretch)
        root.addWidget(self.table, stretch=1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.btn_run = QPushButton("Одштампај исправне редове")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._on_run)
        self.buttons.addButton(self.btn_run, QDialogButtonBox.ActionRole)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    # ── Template download ────────────────────────────────────────

    def _save_template(self, suffix: str) -> None:
        filt = "Excel (*.xlsx)" if suffix == ".xlsx" else "CSV (*.csv)"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сачувај празан шаблон", f"sablon{suffix}", filt,
        )
        if not path:
            return
        if not path.lower().endswith(suffix):
            path += suffix
        try:
            bulk_import.write_template(self._template, path)
        except OSError as e:
            QMessageBox.critical(self, "Грешка", f"Шаблон није сачуван: {e}")
            return
        QMessageBox.information(self, "Сачувано", f"Шаблон је сачуван:\n{path}")

    # ── Pick + preview ───────────────────────────────────────────

    def _on_pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Изабери фајл за увоз", "",
            "Excel и CSV (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)",
        )
        if not path:
            return
        self._path = Path(path)
        self.lbl_file.setText(self._path.name)
        self._result = bulk_import.read_entries(self._path, self._template)
        self._render_result()

    def _render_result(self) -> None:
        result = self._result
        self.table.setRowCount(0)
        if result is None:
            return

        if result.file_error:
            self.lbl_summary.setText(result.file_error)
            self.btn_run.setEnabled(False)
            return

        valid, invalid = len(result.valid_rows), len(result.invalid_rows)
        self.lbl_summary.setText(
            f"Учитано {len(result.rows)} ред(ова): {valid} исправно"
            + (f", {invalid} са грешком (неће бити одштампано)." if invalid else ".")
        )
        self.table.setRowCount(len(result.rows))
        for i, row in enumerate(result.rows):
            self.table.setItem(i, _COL_ROW, QTableWidgetItem(str(row.row_number)))
            self.table.setItem(i, _COL_NAME, QTableWidgetItem(row.entry.full_name))
            self.table.setItem(i, _COL_JMBG, QTableWidgetItem(row.entry.jmbg))
            status_text = "У реду" if row.ok else "; ".join(row.errors)
            status_item = QTableWidgetItem(status_text)
            if not row.ok:
                status_item.setForeground(Qt.red)
            self.table.setItem(i, _COL_STATUS, status_item)
        self.btn_run.setEnabled(valid > 0)

    # ── Run ──────────────────────────────────────────────────────

    def _on_run(self) -> None:
        assert self._result is not None
        valid_rows = self._result.valid_rows
        if not valid_rows:
            return

        answer = QMessageBox.question(
            self, "Потврда",
            f"Одштампати {len(valid_rows)} изјава(е)? Свака ће одмах бити"
            " послата на штампач и сачувана у сесији.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.btn_run.setEnabled(False)
        self.btn_pick.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(valid_rows))
        self.progress.setValue(0)

        succeeded = 0
        print_failures: list[str] = []
        fill_failures: list[str] = []
        for i, row in enumerate(valid_rows, start=1):
            self.progress.setValue(i)
            self.progress.setFormat(f"{row.entry.full_name} ({i}/{len(valid_rows)})")
            # One bad row (a font/overlay problem specific to that
            # row's data) must not abort everyone after it — a partial
            # run the operator can see the summary of beats losing the
            # rest of a real signature-collection sitting to one row.
            try:
                _final_entry, print_error = self._process_entry(row.entry)
            except Exception as e:  # noqa: BLE001
                fill_failures.append(f"{row.row_number} ({row.entry.full_name}): {e}")
                continue
            succeeded += 1
            if print_error:
                print_failures.append(f"{row.row_number} ({row.entry.full_name}): {print_error}")

        self.progress.setVisible(False)
        self._show_summary(succeeded, fill_failures, print_failures)
        self.accept()

    def _show_summary(
        self, succeeded: int, fill_failures: list[str], print_failures: list[str],
    ) -> None:
        lines = [f"Сачувано и покушано штампање за {succeeded} унос(а)."]
        if print_failures:
            lines.append(
                "\nШтампање није успело за (унос ЈЕ сачуван, документ се налази"
                " у фасцикли прегледа и може се ручно одштампати):"
            )
            lines.extend(f"  • {m}" for m in print_failures)
        if fill_failures:
            lines.append("\nДокумент НИЈЕ направљен за (унос није сачуван):")
            lines.extend(f"  • {m}" for m in fill_failures)
        if print_failures or fill_failures:
            QMessageBox.warning(self, "Увоз завршен уз грешке", "\n".join(lines))
        else:
            QMessageBox.information(self, "Готово", "\n".join(lines))
