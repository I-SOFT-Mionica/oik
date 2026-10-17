"""One-shot utility: extract a table from a RIK PDF and save it as Excel.

RIK typically sends its initial decision document as a PDF (often a Word
or Excel file saved as PDF, possibly with a digital signature). This dialog
lets the operator pick the PDF, previews every table found across all pages,
and writes the selected table to an .xlsx file via openpyxl.

Multi-page tables: pdfplumber returns one fragment per page. The dialog
detects consecutive fragments with the same column count and merges them
automatically, dropping repeated header rows. Merged entries appear at
the top of the selector so the most useful option is always the default.

The digital certificate does not affect text/table extraction — pdfplumber
reads the content layer directly. Merged cells are not preserved (PDF does
not store that concept), so header rows may need a quick manual tidy in
Excel after export.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.worker import start_worker

# (page_num, tbl_idx_on_page, rows)
_Frag = tuple[int, int, list[list[str]]]


def _n_cols(rows: list[list[str]]) -> int:
    return max((len(r) for r in rows), default=0)


def _clean(table: list[list[str | None]]) -> list[list[str]]:
    """Replace None cells, drop fully-empty rows."""
    return [
        [cell or "" for cell in row]
        for row in table
        if any(cell for cell in row)
    ]


def _merge_fragments(frags: list[_Frag]) -> list[tuple[str, list[list[str]]]]:
    """Build combo entries from per-page fragments.

    Returns merged-group entries (multi-page continuations) followed by
    individual page entries. Merged entries appear first so the default
    selection is the most complete version of the table.

    Merge criteria: consecutive page numbers + same column count +
    continuation fragment starts with the same header row as the group.
    The third condition distinguishes a genuine continuation (RIK PDFs
    always repeat the column header at the top of each page) from a new
    table that happens to have the same column count.
    The repeated header row is always dropped from continuation fragments.
    """
    if not frags:
        return []

    # ── Group consecutive same-header fragments ────────────────────
    groups: list[list[_Frag]] = []
    current: list[_Frag] = [frags[0]]

    for frag in frags[1:]:
        prev_page = current[-1][0]
        curr_page, _, curr_rows = frag
        prev_cols = _n_cols(current[-1][2])
        curr_cols = _n_cols(curr_rows)
        group_header = current[0][2][0] if current[0][2] else []
        curr_first = curr_rows[0] if curr_rows else []
        is_continuation = (
            curr_page == prev_page + 1
            and curr_cols == prev_cols
            and curr_first == group_header  # repeated header = same table
        )
        if is_continuation:
            current.append(frag)
        else:
            groups.append(current)
            current = [frag]
    groups.append(current)

    # ── Build merged entries (groups spanning > 1 page) ────────────
    merged_entries: list[tuple[str, list[list[str]]]] = []
    for group in groups:
        if len(group) < 2:
            continue
        combined: list[list[str]] = list(group[0][2])
        for _, _, rows in group[1:]:
            combined.extend(rows[1:])  # drop repeated header (guaranteed by grouping)
        first_page = group[0][0]
        last_page = group[-1][0]
        label = (
            f"◆ Спојено: стране {first_page}–{last_page}"
            f"  ({len(combined)} × {_n_cols(combined)})"
        )
        merged_entries.append((label, combined))

    # ── Individual entries (always present) ────────────────────────
    individual: list[tuple[str, list[list[str]]]] = []
    for page_num, tbl_idx, rows in frags:
        label = (
            f"Страна {page_num}, Табела {tbl_idx}"
            f"  ({len(rows)} × {_n_cols(rows)})"
        )
        individual.append((label, rows))

    return merged_entries + individual


def _extract_fragments(pdf_path: Path) -> list[_Frag]:
    """Blocking pdfplumber table scan — runs in a worker thread (see
    `PdfImportWidget._extract`). No Qt in here, so it's directly callable
    from tests without a QApplication."""
    import pdfplumber

    frags: list[_Frag] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            for tbl_idx, table in enumerate(page.extract_tables(), start=1):
                rows = _clean(table)
                if rows:
                    frags.append((page_num, tbl_idx, rows))
    return frags


class PdfImportWidget(QWidget):
    def __init__(self, state, parent=None) -> None:
        super().__init__(parent)
        self.state = state

        self._tables: list[tuple[str, list[list[str]]]] = []  # (label, rows)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── File picker ────────────────────────────────────────────
        file_row = QHBoxLayout()
        self._path_label = QLabel("Није одабран фајл")
        self._path_label.setObjectName("MutedLabel")
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        file_row.addWidget(self._path_label)
        self._btn_pick = QPushButton("Одабери PDF…")
        self._btn_pick.clicked.connect(self._pick_file)
        file_row.addWidget(self._btn_pick)
        layout.addLayout(file_row)

        # ── Table selector ─────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Табела:"))
        self._combo = QComboBox()
        self._combo.setEnabled(False)
        self._combo.currentIndexChanged.connect(self._on_table_selected)
        sel_row.addWidget(self._combo, stretch=1)
        layout.addLayout(sel_row)

        # ── Status / info ──────────────────────────────────────────
        self._status = QLabel("")
        self._status.setObjectName("MutedLabel")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # ── Progress (extraction runs in a worker thread — see
        # _extract — a multi-page PDF can take several seconds and the
        # dialog must not just freeze with a static label) ──────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate — page count isn't known upfront
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── Preview ────────────────────────────────────────────────
        self._preview = QTableWidget()
        self._preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self._preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._preview.setAlternatingRowColors(True)
        layout.addWidget(self._preview, stretch=1)

        # ── Bottom buttons ─────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save = QPushButton("Сачувај као Excel…")
        self._btn_save.setObjectName("PrimaryButton")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save_excel)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

    # ── File picking + extraction ──────────────────────────────────

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Одабери PDF документ", str(self.state.files_dir("PDF конвертор")),
            "PDF документи (*.pdf);;Сви фајлови (*)",
        )
        if not path:
            return
        self._path_label.setText(Path(path).name)
        self._extract(Path(path))

    def _extract(self, pdf_path: Path) -> None:
        try:
            import pdfplumber  # noqa: F401 — availability check only, real import is in the worker
        except ImportError:
            QMessageBox.critical(
                self, "Недостаје библиотека",
                "pdfplumber није инсталиран. Покрените:\n\n"
                "    pip install pdfplumber",
            )
            return

        self._tables.clear()
        self._combo.clear()
        self._combo.setEnabled(False)
        self._btn_save.setEnabled(False)
        self._btn_pick.setEnabled(False)
        self._clear_preview()
        self._status.setText("Учитавање…")
        self._progress.setVisible(True)

        self._worker, self._thread = start_worker(self, _extract_fragments, pdf_path)
        self._worker.finished.connect(self._on_extract_finished)
        self._worker.failed.connect(self._on_extract_failed)

    def _on_extract_failed(self, error: str) -> None:
        self._progress.setVisible(False)
        self._btn_pick.setEnabled(True)
        QMessageBox.warning(
            self, "Грешка при читању PDF-а",
            f"Не могу да отворим или парсирам фајл:\n\n{error}",
        )
        self._status.setText("")

    def _on_extract_finished(self, frags: list) -> None:
        self._progress.setVisible(False)
        self._btn_pick.setEnabled(True)

        if not frags:
            self._status.setText(
                "У PDF-у нису пронађене никакве табеле. "
                "Могуће да је документ скениран или нема видљивих граница табела."
            )
            return

        self._tables = _merge_fragments(frags)
        n_raw = len(frags)
        n_merged = sum(1 for lbl, _ in self._tables if lbl.startswith("◆"))

        for label, _ in self._tables:
            self._combo.addItem(label)
        self._combo.setEnabled(True)
        self._btn_save.setEnabled(True)

        parts = [f"Пронађено {n_raw} {'фрагмент' if n_raw == 1 else 'фрагмената'} на страницама."]
        if n_merged:
            parts.append(f"Аутоматски спојено у {n_merged} {'табелу' if n_merged == 1 else 'табеле'}.")
        self._status.setText(" ".join(parts))
        self._on_table_selected(0)

    # ── Preview ────────────────────────────────────────────────────

    def _on_table_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._tables):
            return
        _, rows = self._tables[index]
        self._populate_preview(rows)

    def _populate_preview(self, rows: list[list[str]]) -> None:
        self._clear_preview()
        if not rows:
            return
        n_cols = _n_cols(rows)
        self._preview.setRowCount(len(rows))
        self._preview.setColumnCount(n_cols)
        self._preview.setHorizontalHeaderLabels(
            [str(i + 1) for i in range(n_cols)]
        )
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(cell)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._preview.setItem(r, c, item)

    def _clear_preview(self) -> None:
        self._preview.clearContents()
        self._preview.setRowCount(0)
        self._preview.setColumnCount(0)

    # ── Excel export ───────────────────────────────────────────────

    def _save_excel(self) -> None:
        idx = self._combo.currentIndex()
        if idx < 0 or idx >= len(self._tables):
            return
        _, rows = self._tables[idx]

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Сачувај као Excel",
            str(self.state.files_dir("PDF конвертор") / "rik_odluka.xlsx"),
            "Excel радна свеска (*.xlsx)",
        )
        if not save_path:
            return

        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "РИК одлука"
            for row in rows:
                ws.append(row)
            wb.save(save_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, "Грешка при чувању",
                f"Не могу да упишем Excel фајл:\n\n{e}",
            )
            return

        QMessageBox.information(
            self, "Сачувано",
            f"Табела је сачувана у:\n{save_path}\n\n"
            "Напомена: спојене ћелије нису сачуване (PDF не чува тај концепт)."
            " Ако су постојале, можда ће бити потребна брза провера заглавља.",
        )
