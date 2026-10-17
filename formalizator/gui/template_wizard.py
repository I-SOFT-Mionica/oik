"""Create a new calibrated template: pick an official .doc/.docx/.pdf,
convert it to a frozen PDF background if needed, run the label auto-
detector, and let the operator review/place positions by CLICKING
directly on the rendered page — not by typing raw X/Y numbers into a
spreadsheet, which turned out unusable in practice (a real official
form has 10+ fields, several sharing the same detected label text —
e.g. the voter's own "(име и презиме)" versus the certifier's separate
"(име и презиме)" further down the page — and a flagged/unrecognized
row with no assigned key still had to show *something* in its field
dropdown, which looked exactly like a real detection instead of an
unplaced one).

What the detector actually found (its detected label text, or
"аутоматски препознато" for a confident match) is kept per row — used
internally (e.g. to find and replace the original flagged "(ЈМБГ)" row
once the JMBG comb tool supersedes it) — but isn't shown as its own
column; once the field picker shows real labels and unplaced rows get
their own on-page marker, the raw detection text was redundant. The
currently-selected row's position is highlighted on the page with a
numbered marker (red vs blue).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PySide6.QtPdf import QPdfDocument

from biracki_odbor.gui.widgets.spinbox import hide_spinbox_buttons, inset_spinbox_text
from formalizator.core import label_detector, pdf_template
from formalizator.core.home_migration import default_home
from formalizator.core.models import (
    CalibratedTemplate, CustomFieldDef, FieldPosition, auto_box_size,
)
from formalizator.reader import transliterate

# A real conversion takes a couple of seconds — this is generous
# headroom for a slow machine, not an estimate of the normal case, so a
# genuine hang (a file already open elsewhere, a dialog Word can't
# show while invisible) surfaces as an error in well under a minute
# instead of the multi-minute waits this used to allow.
_CONVERT_TIMEOUT_SECONDS = 45

# The 13 JMBG digit cells are managed as ONE row — a start position
# plus a cell width/height/font shared by all 13 — not 13 rows the
# operator has to hand-tune individually. Only expanded into 13 real
# jmbg_1..13 FieldPositions at save time (see _on_save). The individual
# jmbg_N keys and the whole-string "jmbg" key still work as
# FieldPosition.field_key values (VoterEntry.to_dict() always exposes
# them) — they're just not offered in the dropdown, to avoid 14
# JMBG-flavored entries cluttering a list that's supposed to be a
# quick field picker.
_JMBG_COMB_KEY = "__jmbg_comb__"
_JMBG_COMB_LABEL = "ЈМБГ (низ од 13 цифара)"

# Fields the eID chip (or a manually-typed equivalent) can actually
# supply — these get a fixed, translated dropdown entry. Anything else
# — a certifier's name, a list name, a place/date of signing, whatever
# a given document needs fixed for the whole session, or per voter but
# outside the ID card's own data — isn't guessable from a hardcoded
# list, so the operator names it instead — see CustomFieldDef.
_FIELD_KEYS = (
    "full_name", "given_name", "surname", _JMBG_COMB_KEY,
    "date_of_birth", "city", "full_address", "full_residence",
    "document_type", "document_reg_no", "date_of_issue", "issuing_authority",
    "full_document_info",
)
_FIELD_KEY_LABELS = {
    "full_name": "Име и презиме", "given_name": "Име", "surname": "Презиме",
    _JMBG_COMB_KEY: _JMBG_COMB_LABEL,
    "date_of_birth": "Датум рођења", "city": "Место", "full_address": "Адреса",
    # Composites — same pattern as "full_name" (given_name + surname):
    # the real form has ONE blank for these, not several, so they print
    # together at one calibrated position instead of needing one
    # position per underlying value.
    "full_residence": "Место и адреса (заједно)",
    "document_type": "Врста документа",
    "document_reg_no": "Број документа", "date_of_issue": "Датум издавања",
    "issuing_authority": "Издавалац",
    "full_document_info": "Документ: врста, број, датум, издавалац (заједно)",
}
_BLANK_FIELD_LABEL = "— изаберите поље —"
_NEW_CUSTOM_FIELD = "__new_custom_field__"
_NEW_CUSTOM_FIELD_LABEL = "+ Ново поље…"

_STYLE_OPTIONS = (
    ("normal", "Обично"), ("bold", "Подебљано"),
    ("italic", "Курзив"), ("bolditalic", "Оба"),
)
_ALIGN_OPTIONS = (("left", "Лево"), ("center", "Средина"), ("right", "Десно"))

_COLUMNS = ("#", "Поље", "X", "Y", "Шир.", "Вис.", "Фонт", "Стил", "Поравн.", "")
_COLOR_UNFOCUSED = "#2F5496"
_COLOR_FOCUSED = "#C6363C"
_COLOR_UNPLACED_REF = "#8A8A8A"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _size_combo_popup(combo: QComboBox) -> None:
    """Some styles clamp a combo's dropdown *popup* to the closed
    combo's own (often narrow, table-column-constrained) width instead
    of auto-sizing to the widest item — confirmed directly, it read as
    unreadable "…"-truncated mush. Widen the popup past that."""
    metrics = combo.fontMetrics()
    widest = max(
        (metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
        default=0,
    )
    combo.view().setMinimumWidth(widest + 40)


class _CustomFieldDialog(QDialog):
    """Names a field that isn't part of the ID card's own data (e.g. a
    certifier's name/address) and says whether it's typed once for the
    whole session or once per voter."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ново поље")
        root = QVBoxLayout(self)

        root.addWidget(QLabel("Назив поља (нпр. Оверитељ — име и презиме):"))
        self.ed_label = QLineEdit()
        root.addWidget(self.ed_label)

        root.addWidget(QLabel("Када се уноси вредност овог поља?"))
        self.cb_kind = QComboBox()
        self.cb_kind.addItem("Посебно за сваку особу (попуњава се на екрану за унос)", "individual")
        self.cb_kind.addItem("Једном за целу сесију (попуњава се при подешавању сесије)", "universal")
        root.addWidget(self.cb_kind)

        root.addWidget(QLabel("Подразумевани садржај (опционо — може се изменити при сваком уносу):"))
        self.ed_default = QLineEdit()
        root.addWidget(self.ed_default)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.ed_label.text().strip():
            QMessageBox.warning(self, "Недостаје назив", "Унесите назив поља.")
            return
        self.accept()

    def field_label(self) -> str:
        return self.ed_label.text().strip()

    def field_kind(self) -> str:
        return self.cb_kind.currentData()

    def default_value(self) -> str:
        return self.ed_default.text().strip()


class _ManageCustomFieldsDialog(QDialog):
    """Edit the default content of custom fields this template already
    has — "+ Ново поље…" only offers a default at the moment a field is
    first created, so an operator who defined fields before that (or
    simply didn't set one then) had no way back in to add or change it.

    Label and kind are shown but not editable here: the field's `key`
    (used everywhere a placed position or a session/voter value refers
    to it) is derived from the label once at creation and never
    changes, and kind decides which screen the field appears on — both
    are one-time decisions made deliberately narrow in scope so editing
    this dialog can never disturb something already placed or typed."""

    def __init__(self, custom_fields: list[CustomFieldDef], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Прилагођена поља")
        self.resize(640, 360)
        self._custom_fields = custom_fields

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Подразумевани садржај се уписује унапред у поље, али остаје"
            " потпуно измењив при сваком уносу."
        ))

        self.table = QTableWidget(len(custom_fields), 3)
        self.table.setHorizontalHeaderLabels(("Назив", "Тип", "Подразумевани садржај"))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for row, cf in enumerate(custom_fields):
            label_item = QTableWidgetItem(cf.label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, label_item)
            kind_text = "једном за сесију" if cf.kind == "universal" else "по особи"
            kind_item = QTableWidgetItem(kind_text)
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, kind_item)
            self.table.setCellWidget(row, 2, QLineEdit(cf.default_value))
        root.addWidget(self.table, stretch=1)

        if not custom_fields:
            root.addWidget(QLabel(
                "Овај шаблон још нема прилагођених поља — додајте их преко"
                " „+ Ново поље…” у падајућем менију неког реда."
            ))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сачувај")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_save(self) -> None:
        for row, cf in enumerate(self._custom_fields):
            ed: QLineEdit = self.table.cellWidget(row, 2)
            cf.default_value = ed.text().strip()
        self.accept()


class _QuietDoubleSpinBox(QDoubleSpinBox):
    """No up/down arrows, no wheel-scroll — both are easy to trigger by
    accident while scrolling the table to read it, and would silently
    move a field's print position (same bug class as the seat-quota
    spinboxes in the main app's settings_election.py)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        hide_spinbox_buttons(self)
        inset_spinbox_text(self, 4)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class _PageCanvas(QLabel):
    """Shows one rendered PDF page at a fixed, known scale — clicking
    on it maps directly and exactly back to PDF point coordinates
    (no QPdfView viewport-transform guesswork)."""

    clicked_at_page_point = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page_width_pt = 0.0
        self._page_height_pt = 0.0
        self._base_pixmap: QPixmap | None = None
        self.setCursor(Qt.CrossCursor)

    def set_page(self, pixmap: QPixmap, width_pt: float, height_pt: float) -> None:
        self._base_pixmap = pixmap
        self._page_width_pt = width_pt
        self._page_height_pt = height_pt
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())

    def redraw_markers(
        self,
        rows: list[tuple[int, float, float, float, float, bool]],
        ref_rows: list[tuple[int, float, float, bool]] | None = None,
    ) -> None:
        """`rows`: (row_number, x_pt, y_pt, width_pt, height_pt,
        is_selected) for every row that's actually been placed. Draws
        the real writable box the text will land in — not just a dot
        near it — so it's clear what area a placement covers, not only
        where its anchor point sits. Fixed two-color scheme: blue for
        every placed field, red only for the one currently selected in
        the table.

        `ref_rows`: (row_number, x_pt, y_pt, is_selected) for flagged-
        but-not-yet-placed rows — the detector's own guess at where
        that row's label sits, shown as a small hollow marker so
        "where's row 8" has an answer before it's assigned and placed,
        not just after. Selecting one in the table turns it red too,
        same as an already-placed row — otherwise clicking an unplaced
        row gave no visible feedback on the page at all."""
        if self._base_pixmap is None:
            return
        pm = QPixmap(self._base_pixmap)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        px_per_pt = pm.width() / self._page_width_pt

        for row_no, x_pt, y_pt, is_selected in sorted(ref_rows or [], key=lambda r: r[3]):
            px = x_pt * px_per_pt
            py = (1 - y_pt / self._page_height_pt) * pm.height()
            color = QColor(_COLOR_FOCUSED if is_selected else _COLOR_UNPLACED_REF)
            d = 20 if is_selected else 16
            painter.setPen(QPen(color, 2 if is_selected else 1, Qt.SolidLine if is_selected else Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(int(px) - d // 2, int(py) - d // 2, d, d)
            badge_font = QFont()
            badge_font.setBold(is_selected)
            badge_font.setPointSize(9 if is_selected else 7)
            painter.setFont(badge_font)
            painter.drawText(int(px) - d // 2, int(py) - d // 2, d, d, Qt.AlignCenter, str(row_no))

        # Selected drawn last (on top of every other box) and with a
        # visibly bigger, bolder badge — otherwise a small selected
        # marker sitting near/under an unselected one was easy to lose,
        # and the plain 18px/8pt badge read as barely-there next to the
        # page's own printed text at this zoom level.
        for row_no, x_pt, y_pt, width_pt, height_pt, is_selected in sorted(
            rows, key=lambda r: r[5],
        ):
            color = QColor(_COLOR_FOCUSED if is_selected else _COLOR_UNFOCUSED)
            px = x_pt * px_per_pt
            py = (1 - y_pt / self._page_height_pt) * pm.height()
            box_w = width_pt * px_per_pt
            box_h = height_pt * px_per_pt
            fill = QColor(color)
            fill.setAlpha(50)
            painter.setPen(QPen(color, 3 if is_selected else 2))
            painter.setBrush(fill)
            # drawString anchors at the text baseline's left edge, so
            # the box sits just above-and-right of (px, py), matching
            # where reportlab will actually place the glyphs.
            painter.drawRect(int(px), int(py - box_h), int(box_w), int(box_h))

            badge_d = 26 if is_selected else 18
            badge_font = QFont()
            badge_font.setBold(True)
            badge_font.setPointSize(11 if is_selected else 8)
            painter.setFont(badge_font)
            bx, by = int(px) - badge_d // 2, int(py - box_h) - badge_d // 2
            if is_selected:
                # A white halo ring first so the badge stands out
                # against any nearby color, not just the page's white.
                painter.setPen(QPen(QColor("#FFFFFF"), 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(bx - 3, by - 3, badge_d + 6, badge_d + 6)
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.setBrush(color)
            painter.drawEllipse(bx, by, badge_d, badge_d)
            painter.drawText(bx, by, badge_d, badge_d, Qt.AlignCenter, str(row_no))
        painter.end()
        self.setPixmap(pm)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt override
        if self._base_pixmap is not None:
            pos = event.position()
            page_x = pos.x() / self._base_pixmap.width() * self._page_width_pt
            page_y = (1 - pos.y() / self._base_pixmap.height()) * self._page_height_pt
            self.clicked_at_page_point.emit(page_x, page_y)
        super().mousePressEvent(event)


class NewTemplateDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Нови шаблон")
        self.resize(1850, 950)
        self.setMinimumSize(1550, 800)
        self._background_pdf_path: str | None = None
        self._pdf_doc = QPdfDocument(self)
        self._armed_row: int | None = None
        self._jmbg_comb_armed = False
        self._jmbg_comb_click1: tuple[float, float] | None = None
        self._jmbg_comb_target_row: int | None = None
        self._custom_fields: list[CustomFieldDef] = []
        # Snapshots of the table's row state, pushed before every
        # structural change (place, comb, add/remove row, reassign a
        # field) — calibration is a lot of fiddly clicking, and one
        # careless click shouldn't mean starting the row over by hand.
        self._undo_stack: list[list[dict]] = []

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("Назив шаблона (нпр. НПРС-3 2026)")
        top.addWidget(self.ed_name)
        self.btn_pick_file = QPushButton("Изабери документ…")
        self.btn_pick_file.clicked.connect(self._on_pick_file)
        top.addWidget(self.btn_pick_file)
        root.addLayout(top)

        self.lbl_hint = QLabel(
            'Кликните дугме „Постави кликом” за жељено поље, па кликните тачно'
            ' место на страни лево где то поље треба да се одштампа.'
        )
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        body = QHBoxLayout()

        self.canvas = _PageCanvas()
        self.canvas.clicked_at_page_point.connect(self._on_canvas_clicked)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self.canvas)
        self._scroll.setWidgetResizable(False)
        body.addWidget(self._scroll, stretch=3)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        header = self.table.horizontalHeader()
        # Explicit widths, not just Stretch — a table squeezed by the
        # canvas's stretch=3 share still needs every column readable.
        header.resizeSection(0, 32)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 220)
        header.setMinimumSectionSize(60)
        for col, width in ((2, 70), (3, 70), (4, 60), (5, 60), (6, 55), (7, 95), (8, 75), (9, 120)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            header.resizeSection(col, width)
        self.table.setMinimumWidth(32 + 220 + 70 + 70 + 60 + 60 + 55 + 95 + 75 + 120 + 40)
        self.table.itemSelectionChanged.connect(self._redraw_markers)
        body.addWidget(self.table, stretch=2)

        root.addLayout(body, stretch=1)

        add_row = QHBoxLayout()
        self.btn_add_field = QPushButton("Додај поље")
        self.btn_add_field.clicked.connect(self._on_add_field)
        add_row.addWidget(self.btn_add_field)
        self.btn_remove_field = QPushButton("Уклони изабрано")
        self.btn_remove_field.clicked.connect(self._on_remove_field)
        add_row.addWidget(self.btn_remove_field)
        # JMBG is always exactly 13 digit cells, evenly spaced — instead
        # of placing (and sizing) 13 rows one at a time, two clicks (left
        # edge of digit 1, right edge of digit 13) calibrate the whole
        # row of boxes at once, matching the real comb exactly.
        self.btn_jmbg_comb = QPushButton("Постави ЈМБГ низ (13 цифара)…")
        self.btn_jmbg_comb.clicked.connect(self._on_place_jmbg_comb)
        add_row.addWidget(self.btn_jmbg_comb)
        self.btn_undo = QPushButton("Опозови (Ctrl+Z)")
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._on_undo)
        add_row.addWidget(self.btn_undo)
        self.btn_manage_custom_fields = QPushButton("Прилагођена поља…")
        self.btn_manage_custom_fields.setToolTip(
            "Измени подразумевани садржај поља која већ постоје на овом шаблону."
        )
        self.btn_manage_custom_fields.clicked.connect(self._on_manage_custom_fields)
        add_row.addWidget(self.btn_manage_custom_fields)
        QShortcut(QKeySequence.Undo, self).activated.connect(self._on_undo)
        root.addLayout(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сачувај шаблон")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._result: CalibratedTemplate | None = None

    # ── Loading the document ─────────────────────────────────────

    def _on_pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Изабери документ", str(Path.home()),
            "Документи (*.doc *.docx *.pdf)",
        )
        if not path:
            return

        src = Path(path)
        if src.suffix.lower() == ".pdf":
            self._load_background(src, src)
            return

        if not pdf_template.WORD_COM_AVAILABLE:
            QMessageBox.critical(
                self, "Word недоступан",
                "Microsoft Word је потребан за претварање .doc/.docx у PDF.",
            )
            return
        out_dir = default_home() / "templates"
        background = out_dir / f"{src.stem}.pdf"

        # Word automation (a real, external application, not just a
        # library call) has hung this dialog solid before — a file
        # already open elsewhere, or a modal dialog Word can't show
        # since it's running invisibly, both block the call forever
        # with no way to even close the window. A plain background
        # *thread* isn't enough to protect against that: pywin32's
        # blocking COM calls hold the GIL while they wait, so a stuck
        # Word instance can still freeze this whole process — confirmed
        # directly (a conversion sat "in progress" for 5+ minutes with
        # no timeout ever firing). Running it as its own OS *process*
        # means it can be waited on and killed without this process
        # ever being at risk, no matter how long Word hangs for.
        self.btn_pick_file.setEnabled(False)
        self.lbl_hint.setText("Претварам документ у PDF… (може потрајати, Word ради у позадини)")
        self._convert_proc = pdf_template.start_conversion_process(src, background)
        self._convert_src = src
        self._convert_out = background
        self._convert_started_at = time.monotonic()
        self._convert_timer = QTimer(self)
        self._convert_timer.setInterval(200)
        self._convert_timer.timeout.connect(self._poll_conversion)
        self._convert_timer.start()

    def _stop_conversion(self) -> None:
        """Abandon an in-flight conversion. Closing the wizard has to
        take Word down with it — otherwise the poll timer keeps running
        against a dialog that is on its way out and eventually raises a
        modal error on a dead parent, which crashed a whole test run
        from inside an unrelated test that happened to pump the event
        loop."""
        timer = getattr(self, "_convert_timer", None)
        if timer is not None:
            timer.stop()
        proc = getattr(self, "_convert_proc", None)
        if proc is not None and proc.poll() is None:
            proc.kill()
        self._convert_proc = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_conversion()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._stop_conversion()
        super().done(result)

    def _poll_conversion(self) -> None:
        proc = self._convert_proc
        if proc is None:  # already abandoned — nothing left to report
            self._convert_timer.stop()
            return
        if proc.poll() is None:
            if time.monotonic() - self._convert_started_at > _CONVERT_TIMEOUT_SECONDS:
                self._convert_timer.stop()
                proc.kill()
                self._on_convert_failed(
                    f"истекло је {_CONVERT_TIMEOUT_SECONDS}s без одговора — можда је ова"
                    " (или нека друга) Word датотека тренутно отворена негде другде"
                )
            return

        self._convert_timer.stop()
        if proc.returncode != 0:
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            self._on_convert_failed(stderr.strip() or f"излазни код {proc.returncode}")
            return
        self.btn_pick_file.setEnabled(True)
        self._reset_hint()
        self._load_background(self._convert_src, self._convert_out)

    def _on_convert_failed(self, message: str) -> None:
        self.btn_pick_file.setEnabled(True)
        self._reset_hint()
        QMessageBox.critical(
            self, "Грешка",
            f"Не могу да претворим у PDF: {message}\n\n"
            "Ако је ова датотека (или неки други Word документ) тренутно"
            " отворена, затворите је и покушајте поново.",
        )

    def _reset_hint(self) -> None:
        self.lbl_hint.setText(
            'Кликните дугме „Постави кликом” за жељено поље, па кликните тачно'
            ' место на страни лево где то поље треба да се одштампа.'
        )

    def _load_background(self, src: Path, background: Path) -> None:
        self._background_pdf_path = str(background)
        self._pdf_doc.load(str(background))
        if not self.ed_name.text().strip():
            self.ed_name.setText(src.stem)

        self._render_page(0)
        result = label_detector.detect(background)
        self._populate_table(result)
        self._redraw_markers()

    def _render_page(self, page_index: int) -> None:
        size_pt = self._pdf_doc.pagePointSize(page_index)
        width_pt, height_pt = size_pt.width(), size_pt.height()
        # Fit the rendered width to the scroll area's own viewport —
        # a fixed DPI either wastes most of the panel or (as reported)
        # renders zoomed in so far past the visible width that reading
        # the form means constantly scrolling sideways.
        available_px = max(self._scroll.viewport().width() - 4, 200)
        scale = available_px / width_pt
        image_size = QSize(int(width_pt * scale), int(height_pt * scale))
        image = self._pdf_doc.render(page_index, image_size)
        self.canvas.set_page(QPixmap.fromImage(image), width_pt, height_pt)

    # ── Table population ─────────────────────────────────────────

    def _populate_table(self, result: label_detector.DetectionResult) -> None:
        self.table.setRowCount(0)
        for pos in result.detected:
            self._append_row(
                pos.field_key, pos.page_index, pos.x, pos.y, pos.font_size,
                source="аутоматски препознато",
            )
        for flagged in result.flagged:
            self._append_row(
                "", flagged.page_index, 0.0, 0.0, 10.0,
                source=f'означено: „{flagged.text}“ — {flagged.reason}',
                ref_point=(flagged.x0, flagged.y),
            )

    def _append_row(
        self, field_key: str, page_index: int, x: float, y: float,
        font_size: float, *, source: str,
        width: float = 0.0, height: float = 0.0,
        bold: bool = False, italic: bool = False, align: str = "center",
        ref_point: tuple[float, float] | None = None,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        num_item = QTableWidgetItem(str(row + 1))
        num_item.setFlags(num_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, num_item)

        combo = QComboBox()
        self._populate_field_combo(combo, field_key)
        combo.currentIndexChanged.connect(
            lambda _idx, c=combo: self._on_field_combo_changed(c)
        )
        self.table.setCellWidget(row, 1, combo)

        # One decimal place, not the QDoubleSpinBox default of two —
        # calibration doesn't need sub-point precision, and "406.15"
        # doesn't fit a table cell this narrow ("406.2" does).
        sb_x = _QuietDoubleSpinBox()
        sb_x.setDecimals(1)
        sb_x.setRange(0, 3000)
        sb_x.setValue(x)
        sb_x.valueChanged.connect(self._redraw_markers)
        self.table.setCellWidget(row, 2, sb_x)

        sb_y = _QuietDoubleSpinBox()
        sb_y.setDecimals(1)
        sb_y.setRange(0, 3000)
        sb_y.setValue(y)
        sb_y.valueChanged.connect(self._redraw_markers)
        self.table.setCellWidget(row, 3, sb_y)

        # 0 = "auto" (sized from the field/font, see core.models.auto_box_size) —
        # the preview box, but also the real box "Поравн." (below)
        # centers/right-aligns text within at print time. "авто" as the
        # special-value text didn't fit this column at any sane width
        # and rendered as unreadable mush — a single "—" always fits,
        # with the explanation moved to a tooltip instead.
        sb_width = _QuietDoubleSpinBox()
        sb_width.setDecimals(1)
        sb_width.setRange(0, 500)
        sb_width.setSpecialValueText("—")
        sb_width.setToolTip("„—” = аутоматски прорачунато из величине фонта")
        sb_width.setValue(width)
        sb_width.valueChanged.connect(self._redraw_markers)
        self.table.setCellWidget(row, 4, sb_width)

        sb_height = _QuietDoubleSpinBox()
        sb_height.setDecimals(1)
        sb_height.setRange(0, 200)
        sb_height.setSpecialValueText("—")
        sb_height.setToolTip("„—” = аутоматски прорачунато из величине фонта")
        sb_height.setValue(height)
        sb_height.valueChanged.connect(self._redraw_markers)
        self.table.setCellWidget(row, 5, sb_height)

        sb_font = _QuietDoubleSpinBox()
        sb_font.setDecimals(1)
        sb_font.setRange(4, 72)
        sb_font.setValue(font_size)
        sb_font.valueChanged.connect(self._redraw_markers)
        self.table.setCellWidget(row, 6, sb_font)

        cb_style = QComboBox()
        for value, label in _STYLE_OPTIONS:
            cb_style.addItem(label, value)
        style_key = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "normal"
        idx = cb_style.findData(style_key)
        cb_style.setCurrentIndex(idx if idx >= 0 else 0)
        cb_style.currentIndexChanged.connect(self._redraw_markers)
        _size_combo_popup(cb_style)
        self.table.setCellWidget(row, 7, cb_style)

        cb_align = QComboBox()
        for value, label in _ALIGN_OPTIONS:
            cb_align.addItem(label, value)
        idx = cb_align.findData(align)
        cb_align.setCurrentIndex(idx if idx >= 0 else 1)  # default "center"
        cb_align.currentIndexChanged.connect(self._redraw_markers)
        _size_combo_popup(cb_align)
        self.table.setCellWidget(row, 8, cb_align)

        btn_place = QPushButton("Постави")
        btn_place.setToolTip("Постави кликом на страну лево")
        # Looks up its OWN current row at click time rather than
        # capturing `row` now — rows get removed/replaced later (the
        # JMBG comb tool alone can remove up to two rows and add one),
        # which silently shifts every later row's true index. A button
        # bound to a fixed row number at creation time would then arm
        # the WRONG row after such a change — confirmed directly: a
        # click meant for one field ended up moving a completely
        # different one several rows away.
        btn_place.clicked.connect(lambda _=False, b=btn_place: self._arm_row(self._row_of_widget(b, 9)))
        self.table.setCellWidget(row, 9, btn_place)

        # page_index/ref_point/source are stored but hidden — no longer
        # shown as its own "Извор" column (redundant once the field
        # picker shows real labels and unplaced rows get their own
        # on-page marker), but source is still used internally (see
        # _remove_unassigned_jmbg_flag_rows) and ref_point feeds the
        # ghost marker; neither is printed or saved.
        self._set_row_meta(row, page_index, ref_point, source)

    # ── Field picker (fixed ID-card keys + operator-named custom ones) ──

    def _populate_field_combo(self, combo: QComboBox, current_key: str = "") -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_BLANK_FIELD_LABEL, "")
        for key in _FIELD_KEYS:
            combo.addItem(_FIELD_KEY_LABELS.get(key, key), key)
        for cf in self._custom_fields:
            suffix = "универзално" if cf.kind == "universal" else "појединачно"
            combo.addItem(f"{cf.label} ({suffix})", cf.key)
        combo.addItem(_NEW_CUSTOM_FIELD_LABEL, _NEW_CUSTOM_FIELD)
        idx = combo.findData(current_key)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)
        _size_combo_popup(combo)

    def _on_field_combo_changed(self, combo: QComboBox) -> None:
        if combo.currentData() == _NEW_CUSTOM_FIELD:
            self._define_new_custom_field(combo)
            return
        self._redraw_markers()

    def _define_new_custom_field(self, combo: QComboBox) -> None:
        dlg = _CustomFieldDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cf = CustomFieldDef(
                key=self._make_custom_key(dlg.field_label()),
                label=dlg.field_label(), kind=dlg.field_kind(),
                default_value=dlg.default_value(),
            )
            self._custom_fields.append(cf)
            self._refresh_all_field_combos(select_key=cf.key, in_combo=combo)
            return
        # Cancelled — don't leave "+ Ново поље…" selected.
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _on_manage_custom_fields(self) -> None:
        dlg = _ManageCustomFieldsDialog(self._custom_fields, self)
        dlg.exec()

    def _refresh_all_field_combos(self, *, select_key: str = "", in_combo: QComboBox | None = None) -> None:
        for row in range(self.table.rowCount()):
            combo: QComboBox = self.table.cellWidget(row, 1)
            if combo is None:
                continue
            keep = select_key if combo is in_combo else combo.currentData()
            self._populate_field_combo(combo, keep or "")

    def _make_custom_key(self, label: str) -> str:
        base = _SLUG_RE.sub("_", transliterate.cyr_to_lat(label).lower()).strip("_") or "polje"
        existing = set(_FIELD_KEYS) | {cf.key for cf in self._custom_fields}
        key, n = base, 2
        while key in existing:
            key = f"{base}_{n}"
            n += 1
        return key

    def _set_row_meta(
        self, row: int, page_index: int,
        ref_point: tuple[float, float] | None, source: str = "",
    ) -> None:
        item = self.table.item(row, 0)
        item.setData(Qt.UserRole, page_index)
        item.setData(Qt.UserRole + 1, ref_point)
        item.setData(Qt.UserRole + 2, source)

    def _row_page_index(self, row: int) -> int:
        item = self.table.item(row, 0)
        val = item.data(Qt.UserRole) if item else None
        return int(val) if val is not None else 0

    def _row_ref_point(self, row: int) -> tuple[float, float] | None:
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole + 1) if item else None

    def _row_source(self, row: int) -> str:
        item = self.table.item(row, 0)
        val = item.data(Qt.UserRole + 2) if item else None
        return val or ""

    def _row_of_widget(self, widget, column: int) -> int:
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, column) is widget:
                return row
        return -1

    def _on_add_field(self) -> None:
        self._push_undo()
        self._append_row("", 0, 0.0, 0.0, 10.0, source="ручно додато")

    def _on_remove_field(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self._push_undo()
            self.table.removeRow(row)
            self._renumber_rows()
            self._redraw_markers()

    # ── Undo ─────────────────────────────────────────────────────

    _UNDO_STACK_LIMIT = 50

    def _snapshot_rows(self) -> list[dict]:
        rows = []
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, 1)
            cb_style = self.table.cellWidget(r, 7)
            cb_align = self.table.cellWidget(r, 8)
            style_key = cb_style.currentData() if cb_style is not None else "normal"
            rows.append({
                "field_key": combo.currentData() if combo is not None else "",
                "source": self._row_source(r),
                "x": self.table.cellWidget(r, 2).value(),
                "y": self.table.cellWidget(r, 3).value(),
                "width": self.table.cellWidget(r, 4).value(),
                "height": self.table.cellWidget(r, 5).value(),
                "font_size": self.table.cellWidget(r, 6).value(),
                "bold": style_key in ("bold", "bolditalic"),
                "italic": style_key in ("italic", "bolditalic"),
                "align": cb_align.currentData() if cb_align is not None else "center",
                "page_index": self._row_page_index(r),
                "ref_point": self._row_ref_point(r),
            })
        return rows

    def _push_undo(self) -> None:
        self._undo_stack.append(self._snapshot_rows())
        del self._undo_stack[:-self._UNDO_STACK_LIMIT]
        self.btn_undo.setEnabled(True)

    def _on_undo(self) -> None:
        if not self._undo_stack:
            return
        snapshot = self._undo_stack.pop()
        self.table.setRowCount(0)
        for r in snapshot:
            self._append_row(
                r["field_key"], r["page_index"], r["x"], r["y"], r["font_size"],
                source=r["source"],
                width=r["width"], height=r["height"],
                bold=r["bold"], italic=r["italic"], align=r["align"],
                ref_point=r["ref_point"],
            )
        self.btn_undo.setEnabled(bool(self._undo_stack))
        self._redraw_markers()

    def _renumber_rows(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            page_index = item.data(Qt.UserRole) if item else 0
            ref_point = item.data(Qt.UserRole + 1) if item else None
            source = item.data(Qt.UserRole + 2) if item else ""
            new_item = QTableWidgetItem(str(row + 1))
            new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            new_item.setData(Qt.UserRole, page_index)
            new_item.setData(Qt.UserRole + 1, ref_point)
            new_item.setData(Qt.UserRole + 2, source)
            self.table.setItem(row, 0, new_item)

    # ── Click-to-place ───────────────────────────────────────────

    def _arm_row(self, row: int) -> None:
        combo = self.table.cellWidget(row, 1)
        if combo is not None and combo.currentData() == _JMBG_COMB_KEY:
            # Recalibrating an existing comb — same two clicks, but they
            # update this one row instead of creating a new one.
            self._armed_row = None
            self._jmbg_comb_armed = True
            self._jmbg_comb_click1 = None
            self._jmbg_comb_target_row = row
            self.lbl_hint.setText(
                "Кликните на ЛЕВУ ивицу ПРВЕ ЈМБГ кућице на страни лево."
            )
            return
        self._jmbg_comb_armed = False
        self._jmbg_comb_click1 = None
        self._jmbg_comb_target_row = None
        self._armed_row = row
        self.lbl_hint.setText(
            f"Кликните на страну лево да поставите поље у реду {row + 1}."
        )

    def _on_canvas_clicked(self, x_pt: float, y_pt: float) -> None:
        if self._jmbg_comb_armed:
            self._on_jmbg_comb_click(x_pt, y_pt)
            return
        if self._armed_row is None:
            return
        row = self._armed_row
        self._push_undo()
        self.table.cellWidget(row, 2).setValue(x_pt)
        self.table.cellWidget(row, 3).setValue(y_pt)
        self._armed_row = None
        self._reset_hint()
        self.table.selectRow(row)
        self._redraw_markers()

    # ── JMBG comb (13 evenly-spaced digit cells, calibrated at once) ──

    def _on_place_jmbg_comb(self) -> None:
        self._armed_row = None
        self._jmbg_comb_armed = True
        self._jmbg_comb_click1 = None
        self._jmbg_comb_target_row = None
        self.lbl_hint.setText(
            "Кликните на ЛЕВУ ивицу ПРВЕ ЈМБГ кућице на страни лево."
        )

    def _on_jmbg_comb_click(self, x_pt: float, y_pt: float) -> None:
        if self._jmbg_comb_click1 is None:
            self._jmbg_comb_click1 = (x_pt, y_pt)
            self.lbl_hint.setText(
                "Сада кликните на ДЕСНУ ивицу ПОСЛЕДЊЕ (13.) ЈМБГ кућице."
            )
            return
        x1, y1 = self._jmbg_comb_click1
        self._jmbg_comb_armed = False
        self._jmbg_comb_click1 = None
        self._reset_hint()
        self._apply_jmbg_comb(x1, y1, x_pt, y_pt)

    def _apply_jmbg_comb(self, x1: float, y1: float, x2: float, y2: float) -> None:
        left, right = min(x1, x2), max(x1, x2)
        total_width = right - left
        if total_width <= 0:
            QMessageBox.warning(
                self, "Неисправан низ",
                "Друга тачка мора бити десно од прве — покушајте поново.",
            )
            return
        cell_width = total_width / 13
        y = (y1 + y2) / 2.0
        height = cell_width
        self._push_undo()

        if self._jmbg_comb_target_row is not None:
            # Recalibrating a comb already on the table — update its
            # one row in place, nothing to add or remove.
            row = self._jmbg_comb_target_row
            self.table.cellWidget(row, 2).setValue(left)
            self.table.cellWidget(row, 3).setValue(y)
            self.table.cellWidget(row, 4).setValue(cell_width)
            self.table.cellWidget(row, 5).setValue(height)
            self._jmbg_comb_target_row = None
            self.table.selectRow(row)
            self._redraw_markers()
            return

        # New comb — replaces whatever JMBG placement existed before
        # (an earlier comb row, any leftover individual jmbg_N rows
        # from before this was one row, or the original single flagged
        # "(ЈМБГ)" row) so redoing it never leaves duplicates behind.
        self._remove_rows_by_field_keys({_JMBG_COMB_KEY, *(f"jmbg_{i}" for i in range(1, 14))})
        self._remove_unassigned_jmbg_flag_rows()

        row = self.table.rowCount()
        self._append_row(
            _JMBG_COMB_KEY, 0, left, y, 10.0,
            source="ЈМБГ низ (13 цифара)", width=cell_width, height=height,
        )
        self.table.selectRow(row)
        self._redraw_markers()

    def _remove_rows_by_field_keys(self, keys: set[str]) -> None:
        for row in reversed(range(self.table.rowCount())):
            combo = self.table.cellWidget(row, 1)
            if combo is not None and combo.currentData() in keys:
                self.table.removeRow(row)
        self._renumber_rows()

    def _remove_unassigned_jmbg_flag_rows(self) -> None:
        for row in reversed(range(self.table.rowCount())):
            combo = self.table.cellWidget(row, 1)
            if (
                combo is not None and not combo.currentData()
                and "јмбг" in self._row_source(row).lower()
            ):
                self.table.removeRow(row)
        self._renumber_rows()

    def _redraw_markers(self) -> None:
        rows = []
        ref_rows = []
        selected = self.table.currentRow()
        for row in range(self.table.rowCount()):
            sb_x = self.table.cellWidget(row, 2)
            sb_y = self.table.cellWidget(row, 3)
            if sb_x is None or sb_y is None:
                continue
            x, y = sb_x.value(), sb_y.value()
            if x == 0.0 and y == 0.0:
                # Not placed yet — show the detector's own guess at
                # where this row's label sits, if it has one, instead
                # of leaving the page with no trace of that row at all.
                ref = self._row_ref_point(row)
                if ref is not None:
                    ref_rows.append((row + 1, ref[0], ref[1], row == selected))
                continue
            sb_width = self.table.cellWidget(row, 4)
            sb_height = self.table.cellWidget(row, 5)
            sb_font = self.table.cellWidget(row, 6)
            font_size = sb_font.value() if sb_font is not None else 10.0
            combo = self.table.cellWidget(row, 1)
            field_key = combo.currentData() if combo is not None else ""
            auto_w, auto_h = auto_box_size(field_key or "", font_size)
            width = (sb_width.value() if sb_width is not None else 0.0) or auto_w
            height = (sb_height.value() if sb_height is not None else 0.0) or auto_h
            is_selected = row == selected
            if field_key == _JMBG_COMB_KEY:
                # One row, 13 boxes — badge each with its digit position
                # (1-13), not the table row number, since that's what
                # actually needs to line up with the real form.
                for i in range(13):
                    rows.append((i + 1, x + width * i, y, width, height, is_selected))
                continue
            rows.append((row + 1, x, y, width, height, is_selected))
        self.canvas.redraw_markers(rows, ref_rows)

    # ── Save ─────────────────────────────────────────────────────

    def _on_save(self) -> None:
        if not self._background_pdf_path:
            QMessageBox.warning(self, "Недостаје документ", "Прво изаберите документ.")
            return
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Недостаје назив", "Унесите назив шаблона.")
            return

        valid_keys = set(_FIELD_KEYS) | {cf.key for cf in self._custom_fields}
        field_labels = {**_FIELD_KEY_LABELS, **{cf.key: cf.label for cf in self._custom_fields}}
        positions: list[FieldPosition] = []
        unplaced: list[str] = []
        for row in range(self.table.rowCount()):
            combo: QComboBox = self.table.cellWidget(row, 1)
            sb_x: QDoubleSpinBox = self.table.cellWidget(row, 2)
            sb_y: QDoubleSpinBox = self.table.cellWidget(row, 3)
            sb_width: QDoubleSpinBox = self.table.cellWidget(row, 4)
            sb_height: QDoubleSpinBox = self.table.cellWidget(row, 5)
            sb_font: QDoubleSpinBox = self.table.cellWidget(row, 6)
            cb_style: QComboBox = self.table.cellWidget(row, 7)
            cb_align: QComboBox = self.table.cellWidget(row, 8)
            field_key = combo.currentData()
            if not field_key or field_key not in valid_keys:
                continue  # "— изаберите поље —" or otherwise unassigned — skip silently
            if sb_x.value() == 0.0 and sb_y.value() == 0.0:
                unplaced.append(f"{row + 1} ({field_labels.get(field_key, field_key)})")
                continue
            style_key = cb_style.currentData()
            bold = style_key in ("bold", "bolditalic")
            italic = style_key in ("italic", "bolditalic")
            align = cb_align.currentData()
            if field_key == _JMBG_COMB_KEY:
                cell_w = sb_width.value() or auto_box_size("jmbg_1", sb_font.value())[0]
                cell_h = sb_height.value() or cell_w
                for i in range(1, 14):
                    positions.append(FieldPosition(
                        field_key=f"jmbg_{i}", page_index=self._row_page_index(row),
                        x=sb_x.value() + cell_w * (i - 1), y=sb_y.value(),
                        font_size=sb_font.value(), width=cell_w, height=cell_h,
                        bold=bold, italic=italic, align=align,
                    ))
                continue
            positions.append(FieldPosition(
                field_key=field_key, page_index=self._row_page_index(row),
                x=sb_x.value(), y=sb_y.value(), font_size=sb_font.value(),
                width=sb_width.value(), height=sb_height.value(),
                bold=bold, italic=italic, align=align,
            ))

        if unplaced:
            reply = QMessageBox.question(
                self, "Непостављена поља",
                "Ови редови имају изабрано поље али нису кликом постављени на"
                " страну, па неће бити сачувани: " + ", ".join(unplaced)
                + ".\n\nСачувати шаблон без њих?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if not positions:
            QMessageBox.warning(self, "Нема постављених поља", "Поставите бар једно поље пре чувања.")
            return

        used_keys = {p.field_key for p in positions}
        used_custom_fields = [cf for cf in self._custom_fields if cf.key in used_keys]

        self._result = CalibratedTemplate(
            name=name, background_pdf_path=self._background_pdf_path,
            positions=positions, custom_fields=used_custom_fields,
        )
        self.accept()

    def result_template(self) -> CalibratedTemplate | None:
        return self._result

    # ── Editing an already-saved template ──────────────────────────

    def load_template(self, template: CalibratedTemplate) -> None:
        """Reopen an already-calibrated template for more editing —
        without this, finishing a template meant getting every field
        placed correctly in one sitting or starting over from scratch."""
        self.setWindowTitle(f"Уређивање шаблона — {template.name}")
        self.ed_name.setText(template.name)
        self._background_pdf_path = template.background_pdf_path
        self._pdf_doc.load(template.background_pdf_path)
        self._render_page(0)
        self._custom_fields = list(template.custom_fields)

        # The JMBG comb only exists as ONE row in this dialog — a saved
        # template only ever has the 13 expanded jmbg_N positions, so
        # they're collapsed back into a single comb row here, the
        # reverse of what _on_save does. Picking the leftmost one as
        # the anchor matches how the comb tool always builds them.
        jmbg_positions = [p for p in template.positions if p.field_key.startswith("jmbg_")]
        other_positions = [p for p in template.positions if not p.field_key.startswith("jmbg_")]

        if jmbg_positions:
            first = min(jmbg_positions, key=lambda p: p.x)
            self._append_row(
                _JMBG_COMB_KEY, first.page_index, first.x, first.y, first.font_size,
                source="ЈМБГ низ (учитано из сачуваног шаблона)",
                width=first.width, height=first.height,
                bold=first.bold, italic=first.italic, align=first.align,
            )

        for pos in other_positions:
            self._append_row(
                pos.field_key, pos.page_index, pos.x, pos.y, pos.font_size,
                source="учитано из сачуваног шаблона",
                width=pos.width, height=pos.height,
                bold=pos.bold, italic=pos.italic, align=pos.align,
            )

        self._redraw_markers()
