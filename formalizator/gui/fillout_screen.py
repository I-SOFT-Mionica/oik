"""Screen 2 — fill out one voter's declaration: editable identity
fields, a document-type dropdown, a Cyrillic/Latin/original script
choice, a "read from chip" button, a live preview of the filled
document, and a print button that also records the entry.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from biracki_odbor.core import jmbg as jmbg_mod
from biracki_odbor.gui.widgets.validators import jmbg_validator
from formalizator.core.models import (
    DOCUMENT_TYPES, CalibratedTemplate, SessionInfo, VoterEntry,
)
from formalizator.core import home_migration
from formalizator.core.overlay_fill import fill_declaration
from formalizator.core.print_pdf import SAVE_AS_PDF, print_pdf
from formalizator.reader import transliterate
from formalizator.reader.eid_reader import (
    EID_READER_AVAILABLE, EidReaderError, EidReaderUnavailable, SerbianIDReader,
)

_PREVIEW_DEBOUNCE_MS = 400

# Sort key for a custom field never placed on the page — keeps it after
# every placed one instead of pretending it belongs at the top.
_UNPLACED_ORDER = (10**6, 0.0, 0.0)


def _page_order_key(template: CalibratedTemplate, field_key: str) -> tuple[int, float, float]:
    """Where a field sits on the calibrated page, as a sort key that
    reads top-to-bottom then left-to-right.

    PDF coordinates put the origin at the bottom-left, so a *larger* y
    is higher up the page — hence the negation. The operator fills the
    form while looking at the document, so a field's own place on that
    document is the only order that isn't confusing; the order they
    happened to be defined in during calibration is arbitrary."""
    positions = [p for p in template.positions if p.field_key == field_key]
    if not positions:
        return _UNPLACED_ORDER
    best = min(positions, key=lambda p: (p.page_index, -p.y, p.x))
    return (best.page_index, -best.y, best.x)


class FilloutScreen(QWidget):
    entry_printed = Signal(object)  # VoterEntry
    back_requested = Signal()
    finish_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._template: CalibratedTemplate | None = None
        self._session_info: SessionInfo | None = None
        self._copies = 1
        self._reader: SerbianIDReader | None = None
        self._custom_edits: dict[str, QLineEdit] = {}
        self._custom_field_defaults: dict[str, str] = {}
        self._preview_dir = Path(tempfile.mkdtemp(prefix="formalizator_preview_"))

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_back = QPushButton("← Назад")
        self.btn_back.clicked.connect(self.back_requested.emit)
        top.addWidget(self.btn_back)
        top.addStretch()
        self.lbl_count = QLabel("Унето: 0")
        top.addWidget(self.lbl_count)
        # Whether this ends up producing a spreadsheet depends entirely
        # on what was chosen on the setup screen (the optional "Извоз у
        # Excel" step, right after the template) — "(без извоза)" means
        # this just closes the session with no export at all.
        self.btn_finish = QPushButton("Заврши сесију и извези…")
        self.btn_finish.setObjectName("PrimaryButton")
        self.btn_finish.clicked.connect(self.finish_requested.emit)
        top.addWidget(self.btn_finish)
        root.addLayout(top)

        body = QHBoxLayout()

        left = QVBoxLayout()
        form_box = QGroupBox("Подаци о бирачу")
        form = QFormLayout(form_box)
        self.ed_given_name = QLineEdit()
        self.ed_surname = QLineEdit()
        self.ed_jmbg = QLineEdit()
        # Digits only, at most 13, enforced at keystroke time — the same
        # validator the main app puts on every JMBG field. Without it
        # this accepted free text of any length, and because
        # `jmbg.normalize()` turns anything non-numeric into an empty
        # string, typed rubbish silently became *no* JMBG at all rather
        # than a rejected one.
        self.ed_jmbg.setValidator(jmbg_validator())
        self.ed_jmbg.setPlaceholderText("13 цифара")
        self.ed_date_of_birth = QLineEdit()
        # Same shape the chip itself returns ("23.08.1985"), so a typed
        # entry and a card read can't disagree on formatting.
        self.ed_date_of_birth.setPlaceholderText("нпр. 01.01.1990 (из ЈМБГ-а)")
        self.ed_city = QLineEdit()
        self.ed_full_address = QLineEdit()
        self.cb_document_type = QComboBox()
        self.cb_document_type.addItems(DOCUMENT_TYPES)
        self.ed_document_reg_no = QLineEdit()
        self.ed_date_of_issue = QLineEdit()
        self.ed_issuing_authority = QLineEdit()

        form.addRow("Име:", self.ed_given_name)
        form.addRow("Презиме:", self.ed_surname)
        form.addRow("ЈМБГ:", self.ed_jmbg)
        form.addRow("Датум рођења:", self.ed_date_of_birth)
        form.addRow("Место:", self.ed_city)
        form.addRow("Адреса:", self.ed_full_address)
        form.addRow("Врста документа:", self.cb_document_type)
        form.addRow("Број документа:", self.ed_document_reg_no)
        form.addRow("Датум издавања:", self.ed_date_of_issue)
        form.addRow("Издавалац:", self.ed_issuing_authority)
        left.addWidget(form_box)

        # Rebuilt per template in set_template() — fields this specific
        # document needs that aren't part of the ID card's own data
        # (e.g. a certifier's name is session-wide, not per-voter, so it
        # lives on SetupScreen instead) but still vary voter-to-voter.
        self.custom_box = QGroupBox("Додатна поља (за ову особу)")
        self.custom_form = QFormLayout(self.custom_box)
        self.custom_box.setVisible(False)
        left.addWidget(self.custom_box)

        script_box = QGroupBox("Писмо")
        script_layout = QHBoxLayout(script_box)
        self.cb_script = QComboBox()
        self.cb_script.addItem("Изворно", "original")
        self.cb_script.addItem("Латиница", "latin")
        self.cb_script.addItem("Ћирилица", "cyrillic")
        script_layout.addWidget(self.cb_script)
        left.addWidget(script_box)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(420)

        # The data column is taller than an ordinary laptop screen and
        # there is no way to make it shorter: ten fixed ID fields, plus
        # however many extra fields this particular document needs, plus
        # the script picker and the action buttons. Measured, it asks for
        # ~876 px and the whole screen for ~952 — while a 1920x1080
        # laptop at 125% scaling has 864 logical pixels, and only 816
        # once the taskbar takes its cut.
        #
        # Without a scroll area the layout simply overflows and the
        # bottom is cut off, which is what put the action buttons under
        # the taskbar and clipped the lowest fields. It also explains why
        # the symptom eases when the taskbar is set to auto-hide: that
        # hands back ~48 px of available height, so less is lost — the
        # giveaway that this was about available height all along, not
        # DPI or font metrics.
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # The three buttons that get used on every single voter live
        # below the scroll area rather than inside it, pinned. Scrolling
        # solves the clipping, but a Штампај button that has to be
        # scrolled to is its own election-day problem.
        left_panel = QWidget()
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)
        left_panel_layout.addWidget(left_scroll, stretch=1)

        # Two rows, not three-across: at this column's 420-446 px cap,
        # the global stylesheet's QPushButton padding (10px 22px, see
        # gui/style.py) left too little room for three Cyrillic labels
        # in one row — Qt compressed each button below its own
        # minimumSizeHint and clipped the text at both edges instead of
        # simply widening the row (confirmed live: "Прочитај картицу"
        # and "Увоз из фајла…" both lost characters off the front and
        # back). Splitting into two rows halves the per-button width
        # pressure instead of fighting the shared stylesheet locally.
        actions_row1 = QHBoxLayout()
        self.btn_read_card = QPushButton("Прочитај картицу")
        self.btn_read_card.setEnabled(EID_READER_AVAILABLE)
        self.btn_read_card.clicked.connect(self._on_read_card)
        actions_row1.addWidget(self.btn_read_card)
        self.btn_clear = QPushButton("Очисти")
        self.btn_clear.clicked.connect(self._clear_fields)
        actions_row1.addWidget(self.btn_clear)
        left_panel_layout.addLayout(actions_row1)

        actions_row2 = QHBoxLayout()
        self.btn_bulk_import = QPushButton("Увоз из фајла…")
        self.btn_bulk_import.setToolTip(
            "Попуните и одштампајте изјаве за више особа одједном из"
            " Excel (.xlsx) или CSV фајла."
        )
        self.btn_bulk_import.clicked.connect(self._on_bulk_import)
        actions_row2.addWidget(self.btn_bulk_import)
        left_panel_layout.addLayout(actions_row2)

        self.btn_print = QPushButton("Штампај")
        self.btn_print.setObjectName("PrimaryButton")
        self.btn_print.clicked.connect(self._on_print)
        left_panel_layout.addWidget(self.btn_print)

        # Room for the vertical scrollbar on top of the column's own
        # 420 px, so it never overlaps the fields it scrolls.
        left_panel.setMaximumWidth(446)
        body.addWidget(left_panel, stretch=0)

        preview_box = QGroupBox("Преглед документа")
        preview_layout = QVBoxLayout(preview_box)
        self.preview = QPdfView()
        self._pdf_doc = QPdfDocument(self)
        self.preview.setDocument(self._pdf_doc)
        self.preview.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        preview_layout.addWidget(self.preview)
        body.addWidget(preview_box, stretch=1)

        root.addLayout(body, stretch=1)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)
        for ed in (
            self.ed_given_name, self.ed_surname, self.ed_jmbg, self.ed_date_of_birth,
            self.ed_city, self.ed_full_address, self.ed_document_reg_no,
            self.ed_date_of_issue, self.ed_issuing_authority,
        ):
            ed.textChanged.connect(self._schedule_preview)
        self.cb_document_type.currentIndexChanged.connect(self._schedule_preview)
        self.cb_script.currentIndexChanged.connect(self._schedule_preview)
        self.ed_jmbg.textChanged.connect(self._on_jmbg_changed)

    # ── Session wiring ───────────────────────────────────────────

    def set_template(self, template: CalibratedTemplate) -> None:
        self._template = template
        self._rebuild_custom_fields(template)
        self._schedule_preview()

    def set_session_info(self, info: SessionInfo) -> None:
        self._session_info = info

    def set_copies(self, copies: int) -> None:
        self._copies = copies

    @property
    def _printer_name(self) -> str:
        """The printer chosen for this sitting, "" to follow Windows."""
        return self._session_info.printer_name if self._session_info else ""

    def _rebuild_custom_fields(self, template: CalibratedTemplate) -> None:
        while self.custom_form.rowCount():
            self.custom_form.removeRow(0)
        self._custom_edits.clear()
        self._custom_field_defaults.clear()
        individual = [cf for cf in template.custom_fields if cf.kind == "individual"]
        # Follow the document, not the order the fields happened to be
        # defined in — sorting is stable, so any never-placed fields
        # keep their defined order at the end.
        individual.sort(key=lambda cf: _page_order_key(template, cf.key))
        for cf in individual:
            ed = QLineEdit(cf.default_value)
            ed.textChanged.connect(self._schedule_preview)
            self.custom_form.addRow(f"{cf.label}:", ed)
            self._custom_edits[cf.key] = ed
            self._custom_field_defaults[cf.key] = cf.default_value
        self.custom_box.setVisible(bool(individual))

    def set_entry_count(self, count: int) -> None:
        self.lbl_count.setText(f"Унето: {count}")

    def cleanup_previews(self) -> None:
        """Delete this session's rendered declarations.

        They are personal data, not scratch: each PDF carries a voter's
        name, JMBG and address, and the file name embeds the JMBG. Left
        alone they accumulate in the system temp directory
        indefinitely — a machine used for a day of collection ends up
        holding hundreds of filled declarations in a world-readable
        folder."""
        import shutil

        shutil.rmtree(self._preview_dir, ignore_errors=True)

    # ── Fields <-> VoterEntry ────────────────────────────────────

    def _on_jmbg_changed(self, text: str) -> None:
        """A JMBG's first seven digits *are* the date of birth, so a
        manual entry shouldn't have to type it twice — the only thing
        typing it twice can add is a disagreement with the card.
        `extract_date_of_birth` only answers on a full 13 digits, so
        this stays quiet while the operator is still typing."""
        self._refresh_jmbg_validity()
        dob = jmbg_mod.extract_date_of_birth(text)
        if dob is None:
            return
        derived = f"{dob.day:02d}.{dob.month:02d}.{dob.year}"
        if self.ed_date_of_birth.text().strip() != derived:
            self.ed_date_of_birth.setText(derived)

    def _refresh_jmbg_validity(self, *, include_incomplete: bool = False) -> None:
        """Red border via the shared `[invalid="true"]` QSS rule.

        A half-typed JMBG is not marked wrong while the operator is
        still typing — only a complete 13 digits that fails MOD 11.
        `include_incomplete` is for submit time, where "not finished" is
        every bit as unusable as "wrong"."""
        text = self.ed_jmbg.text()
        if include_incomplete:
            invalid = not jmbg_mod.is_valid(text)
        else:
            invalid = len(text) == 13 and not jmbg_mod.is_valid(text)
        self.ed_jmbg.setProperty("invalid", bool(invalid))
        # Force re-polish so the property change actually re-applies QSS.
        self.ed_jmbg.style().unpolish(self.ed_jmbg)
        self.ed_jmbg.style().polish(self.ed_jmbg)

    def _current_script(self) -> str:
        return self.cb_script.currentData() or "original"

    def _collect_entry(self, *, source: str = "manual") -> VoterEntry:
        return VoterEntry(
            given_name=self.ed_given_name.text().strip(),
            surname=self.ed_surname.text().strip(),
            jmbg=jmbg_mod.normalize(self.ed_jmbg.text()),
            date_of_birth=self.ed_date_of_birth.text().strip(),
            city=self.ed_city.text().strip(),
            full_address=self.ed_full_address.text().strip(),
            document_type=self.cb_document_type.currentText(),
            document_reg_no=self.ed_document_reg_no.text().strip(),
            date_of_issue=self.ed_date_of_issue.text().strip(),
            issuing_authority=self.ed_issuing_authority.text().strip(),
            source=source,
            custom_values={key: ed.text().strip() for key, ed in self._custom_edits.items()},
        )

    def _apply_entry_to_fields(self, entry: VoterEntry) -> None:
        script = self._current_script()
        data = transliterate.transliterate_dict(entry.to_dict(), script)
        self.ed_given_name.setText(data.get("given_name", ""))
        self.ed_surname.setText(data.get("surname", ""))
        self.ed_jmbg.setText(entry.jmbg)  # digits — never transliterated
        self.ed_date_of_birth.setText(entry.date_of_birth)
        self.ed_city.setText(data.get("city", ""))
        self.ed_full_address.setText(data.get("full_address", ""))
        self.ed_document_reg_no.setText(entry.document_reg_no)
        self.ed_date_of_issue.setText(entry.date_of_issue)
        self.ed_issuing_authority.setText(data.get("issuing_authority", ""))

    def _clear_fields(self) -> None:
        for ed in (
            self.ed_given_name, self.ed_surname, self.ed_jmbg, self.ed_date_of_birth,
            self.ed_city, self.ed_full_address, self.ed_document_reg_no,
            self.ed_date_of_issue, self.ed_issuing_authority,
        ):
            ed.clear()
        self.cb_document_type.setCurrentIndex(0)
        # Re-apply each field's default rather than blanking — a
        # default is meant to save re-typing for every voter, not just
        # the first one in the session.
        for key, ed in self._custom_edits.items():
            ed.setText(self._custom_field_defaults.get(key, ""))

    # ── Card read ────────────────────────────────────────────────

    def _on_read_card(self) -> None:
        try:
            if self._reader is None:
                self._reader = SerbianIDReader()
                self._reader.startup()
            entry = self._reader.read_card()
        except EidReaderUnavailable as e:
            QMessageBox.critical(self, "Читач није доступан", str(e))
            return
        except EidReaderError as e:
            QMessageBox.warning(self, "Грешка при читању картице", str(e))
            return
        self._apply_entry_to_fields(entry)

    # ── Preview ──────────────────────────────────────────────────

    def _schedule_preview(self, *_args) -> None:
        self._preview_timer.start()

    def _transliterated(self, entry: VoterEntry, script: str) -> VoterEntry:
        """Transliterate every printable value on `entry`, including
        its per-template custom fields — `entry.to_dict()` flattens
        `custom_values` into top-level keys (for overlay_fill's uniform
        lookup), so reconstructing only from VoterEntry's own
        dataclass-field names would silently drop them; they're pulled
        back out by their own keys instead."""
        entry_dict = transliterate.transliterate_dict(entry.to_dict(), script)
        entry_dict["jmbg"] = entry.jmbg  # digits — never transliterated
        result = VoterEntry(**{
            k: v for k, v in entry_dict.items()
            if k in VoterEntry.__dataclass_fields__
        })
        result.custom_values = {
            key: entry_dict.get(key, "") for key in entry.custom_values
        }
        result.source = entry.source
        return result

    def _refresh_preview(self) -> None:
        if self._template is None:
            return
        entry = self._collect_entry()
        preview_entry = self._transliterated(entry, self._current_script())
        out_path = self._preview_dir / "preview.pdf"
        try:
            fill_declaration(self._template, preview_entry, out_path, self._session_info)
        except Exception:  # noqa: BLE001 — preview is best-effort
            return
        self._pdf_doc.load(str(out_path))

    # ── Print + record ───────────────────────────────────────────

    def _validate_for_print(self, entry: VoterEntry) -> str:
        """Return an error message if `entry` isn't fit to print, or ""
        if it's fine. Shared by the interactive Штампај path and the
        bulk-import preview, so a row imported from a file is held to
        exactly the same bar as one typed by hand — not a weaker one.

        Not `if entry.jmbg and ...`: an empty JMBG used to pass this
        gate once, and since normalize() maps anything non-numeric to
        "", typed rubbish arrived as empty and sailed through —
        producing a printed declaration and an NPRS-4 row with a blank
        ЈМБГ column. These sheets are merged by hand in Belgrade, so a
        missing JMBG is not a soft warning, it is an unusable entry.
        """
        if not entry.given_name or not entry.surname:
            return "Име и презиме су обавезни."
        if not jmbg_mod.is_valid(entry.jmbg):
            return (
                "ЈМБГ мора имати тачно 13 цифара и проћи MOD 11 проверу."
                if entry.jmbg else
                "ЈМБГ је обавезан — унесите 13 цифара или прочитајте картицу."
            )
        return ""

    def _process_entry(self, entry: VoterEntry) -> tuple[VoterEntry, str]:
        """Fill, print, and record one already-validated entry — the
        single pipeline behind both the interactive Штампај button and
        a bulk import's per-row loop, so the two can never drift apart
        on what "recorded" means.

        Raises on a fill failure (nothing was produced — the caller
        must not record an entry with no document behind it). A print
        failure is different: the declaration file DOES exist by that
        point, so it is recorded regardless and the failure is
        returned as a message instead, matching the reasoning below.
        """
        final_entry = self._transliterated(entry, self._current_script())
        out_path = self._preview_dir / f"declaration_{final_entry.jmbg or 'bez_jmbg'}.pdf"
        fill_declaration(self._template, final_entry, out_path, self._session_info)

        if self._printer_name == SAVE_AS_PDF:
            # A deliberate operator choice from the session setup screen
            # — not core.print_pdf's automatic refusal to fall back onto
            # a virtual printer, which stays exactly as strict as it
            # was. No printer is touched at all: the declaration already
            # exists (the line above just wrote it) in the preview
            # folder, which is a temp directory wiped on exit — this
            # copies it somewhere that survives past the session, since
            # choosing "save as PDF" makes the file itself the
            # deliverable rather than a paper printout.
            error = ""
            try:
                saved_path = home_migration.saved_pdf_dir() / out_path.name
                shutil.copy2(out_path, saved_path)
            except OSError as e:
                error = f"Чување PDF-а није успело: {e}"
            self.entry_printed.emit(final_entry)
            return final_entry, error

        # Catch everything, not just PrintUnavailable: os.startfile's
        # "print" verb raises OSError when no application is registered
        # to print a .pdf — routine on a fresh or locked-down machine —
        # and that escaped this slot uncaught once. In a windowed build
        # a Qt slot's traceback goes to stderr, i.e. nowhere, so
        # pressing Штампај did nothing at all: no printout, no dialog,
        # and (worst of all) the entry was silently dropped. Reported
        # directly from the field.
        print_error = ""
        try:
            print_pdf(out_path, copies=self._copies, printer_name=self._printer_name)
        except Exception as e:  # noqa: BLE001
            print_error = str(e)

        # Recorded whether or not printing worked. The voter has already
        # signed by this point; losing their entry because a printer
        # isn't set up is far worse than a printout that has to be
        # redone, and the roster export is the legally binding artefact.
        self.entry_printed.emit(final_entry)
        return final_entry, print_error

    def _confirm_saved_pdf(self, saved_path: Path) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Information, "Сачувано",
            f"PDF изјава је сачувана:\n{saved_path}", parent=self,
        )
        btn_open = box.addButton("Отвори фасциклу", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is btn_open:
            try:
                subprocess.Popen(["explorer", str(saved_path.parent)])
            except OSError:
                pass

    def _on_bulk_import(self) -> None:
        if self._template is None:
            QMessageBox.warning(self, "Нема шаблона", "Није изабран шаблон изјаве.")
            return
        from formalizator.gui.dialogs.bulk_import_dialog import BulkImportDialog

        dialog = BulkImportDialog(self._template, self._process_entry, self)
        dialog.exec()

    def _on_print(self) -> None:
        if self._template is None:
            QMessageBox.warning(self, "Нема шаблона", "Није изабран шаблон изјаве.")
            return
        entry = self._collect_entry(source="card" if self._reader else "manual")
        error = self._validate_for_print(entry)
        if error:
            if "ЈМБГ" in error:
                self._refresh_jmbg_validity(include_incomplete=True)
                self.ed_jmbg.setFocus()
                QMessageBox.warning(self, "Неисправан ЈМБГ", error)
            else:
                QMessageBox.warning(self, "Недостају подаци", error)
            return

        try:
            final_entry, print_error = self._process_entry(entry)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Грешка", f"Не могу да направим документ: {e}")
            return

        self._clear_fields()

        if self._printer_name == SAVE_AS_PDF:
            # A printed page is its own confirmation; a saved file isn't
            # — nothing else on screen shows where it went, so say so
            # explicitly. The destination sits straight under the user
            # profile root behind a Cyrillic folder name ("Сачуване
            # изјаве") — easy to type past or lose in a manual search —
            # so an "Отвори фасциклу" button is offered right there
            # rather than relying on the operator to navigate to a path
            # they only saw once, in passing, in a dialog they've
            # already dismissed.
            if print_error:
                QMessageBox.warning(self, "Чување PDF-а није успело", print_error)
            else:
                saved_path = home_migration.saved_pdf_dir() / f"declaration_{final_entry.jmbg or 'bez_jmbg'}.pdf"
                self._confirm_saved_pdf(saved_path)
            return

        if print_error:
            out_path = self._preview_dir / f"declaration_{final_entry.jmbg or 'bez_jmbg'}.pdf"
            QMessageBox.warning(
                self, "Штампа није успела",
                f"Унос ЈЕ сачуван и ући ће у извоз, али штампање није успело:\n\n"
                f"{print_error}\n\n"
                f"Документ можете одштампати ручно одавде:\n{out_path}",
            )
