"""First-run setup wizard.

Shown at startup when ``AppState.onboarding_complete`` is False. Goal:
after finishing it the operator never needs to open Поставке ИК -- every
value a решење needs is either asked here or derived (municipality
code, AP Vojvodina, case forms, commission name all come from the
municipality picked from the bundled registry).

Offers a restore-from-backup shortcut so reinstalling operators don't
have to re-enter everything by hand.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpacerItem, QStackedWidget,
    QVBoxLayout, QWidget,
)

from biracki_odbor.config import opstine as opstine_mod
from biracki_odbor.config.commission import NACELNIK_ROLES, default_full_committee_name
from biracki_odbor.config.oik import default_station_full_name
from biracki_odbor.core.models import PollingStation
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.sidebar import SECTION_IZBORNA
from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

log = logging.getLogger(__name__)

# Page indices
_P_WELCOME = 0
_P_RESTORE = 1
_P_OIK = 2
_P_FOLDER = 3
_P_STATIONS = 4
_P_ELECTION = 5
_P_DONE = 6

STATIONS_PURPOSE = "Бирачка места"
STATIONS_TEMPLATE_NAME = "bm.xlsx"

_ELECTION_TYPES = [
    ("presidential",  "Председнички избори"),
    ("parliamentary", "Парламентарни избори"),
    ("provincial",    "Покрајински избори"),
    ("local",         "Локални избори"),
]


class SetupWizard(QDialog):
    """Modal first-run wizard."""

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self.requested_section: int | None = None
        self._stations: dict[int, PollingStation] = {}

        self.setWindowTitle(self.tr("OIK Setup"))
        self.setMinimumSize(720, 720)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_welcome())    # 0
        self._stack.addWidget(self._build_restore())    # 1
        self._stack.addWidget(self._build_oik())        # 2
        self._stack.addWidget(self._build_folder())     # 3
        self._stack.addWidget(self._build_stations())   # 4
        self._stack.addWidget(self._build_election())   # 5
        self._stack.addWidget(self._build_done())       # 6

        self._stack.setCurrentIndex(_P_WELCOME)

    # ── Page builders ─────────────────────────────────────────────────

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 32, 32, 24)
        lay.setSpacing(12)
        return page, lay

    def _build_welcome(self) -> QWidget:
        page, lay = self._page()
        lay.setSpacing(16)

        title = QLabel(self.tr("Welcome to OIK"))
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        title.setFont(font)
        lay.addWidget(title)

        body = QLabel(self.tr(
            "Before you can start working, a few settings need to be filled in:\n"
            "  • Municipality and commission chairman\n"
            "  • Folder for exported and imported files\n"
            "  • Polling stations\n"
            "  • Election type and date\n\n"
            "If you are reinstalling and have a backup .zip from a previous\n"
            "installation, you can restore it instead."
        ))
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addSpacerItem(QSpacerItem(0, 16, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        btn_restore = QPushButton(self.tr("Restore from backup .zip…"))
        btn_restore.clicked.connect(lambda: self._go(_P_RESTORE))
        lay.addWidget(btn_restore)

        btn_fresh = QPushButton(self.tr("Fresh setup  →"))
        btn_fresh.setObjectName("PrimaryButton")
        btn_fresh.clicked.connect(lambda: self._go(_P_OIK))
        lay.addWidget(btn_fresh)

        lay.addStretch()

        skip = QPushButton(self.tr("Skip — I will configure manually"))
        skip.setFlat(True)
        skip.setObjectName("LinkButton")
        skip.clicked.connect(self.reject)
        lay.addWidget(skip, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _build_restore(self) -> QWidget:
        page, lay = self._page()

        lay.addWidget(self._header(self.tr("Restore from backup")))

        intro = QLabel(self.tr(
            "Select the .zip backup file from your previous installation.\n"
            "All settings and data will be restored from it."
        ))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        self._ed_zip = QLineEdit()
        self._ed_zip.setPlaceholderText(self.tr("Path to .zip backup…"))
        self._ed_zip.setReadOnly(True)
        row.addWidget(self._ed_zip, stretch=1)
        btn_pick = QPushButton(self.tr("Choose .zip…"))
        btn_pick.clicked.connect(self._pick_zip)
        row.addWidget(btn_pick)
        lay.addLayout(row)

        self._btn_do_restore = QPushButton(self.tr("Restore"))
        self._btn_do_restore.setObjectName("PrimaryButton")
        self._btn_do_restore.setEnabled(False)
        self._btn_do_restore.clicked.connect(self._do_restore)
        lay.addWidget(self._btn_do_restore)

        self._restore_log = QPlainTextEdit()
        self._restore_log.setReadOnly(True)
        self._restore_log.setMaximumHeight(120)
        lay.addWidget(self._restore_log)

        lay.addStretch()
        lay.addLayout(self._nav_row(back=_P_WELCOME))
        return page

    def _build_oik(self) -> QWidget:
        page, lay = self._page()

        lay.addWidget(self._header(self.tr("Commission details")))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Same strict registry picker as Поставке ИК: the name can only be
        # a real registry entry, which is what gives us the municipality
        # code (RIK РАСПОДЕЛА import) and AP Vojvodina for free.
        self.cb_municipality = QComboBox()
        self.cb_municipality.setEditable(True)
        self.cb_municipality.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        registry = opstine_mod.load_registry()
        for entry in registry:
            self.cb_municipality.addItem(entry.name, entry.sifra)
        self.cb_municipality.setCurrentIndex(-1)
        self.cb_municipality.lineEdit().setPlaceholderText(self.tr("Start typing, e.g. Мионица"))
        completer = QCompleter([e.name for e in registry], self.cb_municipality)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.cb_municipality.setCompleter(completer)
        self.cb_municipality.activated.connect(self._on_municipality_activated)
        self.cb_municipality.lineEdit().editingFinished.connect(self._on_municipality_typed)
        form.addRow(self.tr("Municipality or city:"), self.cb_municipality)

        self.lbl_municipality_info = QLabel("")
        self.lbl_municipality_info.setObjectName("MutedLabel")
        form.addRow("", self.lbl_municipality_info)

        self._ed_mun_gen = QLineEdit()
        self._ed_mun_gen.setPlaceholderText(self.tr("e.g. Мионице"))
        form.addRow(self.tr("Genitive (e.g. Мионице):"), self._ed_mun_gen)

        self._ed_mun_loc = QLineEdit()
        self._ed_mun_loc.setPlaceholderText(self.tr("e.g. Мионици"))
        form.addRow(self.tr("Locative (e.g. Мионици):"), self._ed_mun_loc)

        self._ed_mun_full = QLineEdit()
        form.addRow(self.tr("Full committee name:"), self._ed_mun_full)

        self._ed_chairman = QLineEdit()
        self._ed_chairman.setPlaceholderText(self.tr("e.g. Пера Перић"))
        form.addRow(self.tr("Chairman name:"), self._ed_chairman)

        self._ed_email = QLineEdit()
        self._ed_email.setPlaceholderText(self.tr("e.g. oik@mionica.rs"))
        form.addRow(self.tr("Commission email (optional):"), self._ed_email)

        self._ed_website = QLineEdit()
        self._ed_website.setPlaceholderText(self.tr("e.g. ub.rs"))
        form.addRow(self.tr("Municipality website (optional):"), self._ed_website)

        lay.addLayout(form)

        note = QLabel(self.tr(
            "Case forms and the commission name are suggested from the"
            " municipality — check them, they appear in every decision."
        ))
        note.setObjectName("MutedLabel")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()
        lay.addLayout(self._nav_row(back=_P_WELCOME, next_page=_P_FOLDER,
                                    next_label=self.tr("Next →"),
                                    next_guard=self._oik_page_valid))
        return page

    def _build_folder(self) -> QWidget:
        page, lay = self._page()

        lay.addWidget(self._header(self.tr("Folder for your files")))

        note = QLabel(self.tr(
            "Everything the program exports (party files, decisions, reports)"
            " is saved here, and import dialogs open here. The polling station"
            " template in the next step is also created in this folder."
        ))
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        self._ed_folder = QLineEdit()
        self._ed_folder.setReadOnly(True)
        configured = self.state.app_settings.default_files_dir.strip()
        self._ed_folder.setText(configured or str(Path.home() / "Documents" / "OIK"))
        row.addWidget(self._ed_folder, stretch=1)
        btn_browse = QPushButton(self.tr("Browse…"))
        btn_browse.clicked.connect(self._pick_folder)
        row.addWidget(btn_browse)
        lay.addLayout(row)

        lay.addStretch()
        lay.addLayout(self._nav_row(back=_P_OIK, next_page=_P_STATIONS,
                                    next_label=self.tr("Next →"),
                                    next_guard=self._folder_page_valid))
        return page

    def _build_stations(self) -> QWidget:
        page, lay = self._page()

        lay.addWidget(self._header(self.tr("Polling stations")))

        note = QLabel(self.tr(
            "1. Create the template — an Excel file opens in your folder.\n"
            "2. Fill in number, name and address of every polling station, save it.\n"
            "3. Import it here."
        ))
        note.setWordWrap(True)
        lay.addWidget(note)

        btn_row = QHBoxLayout()
        self.btn_make_template = QPushButton(self.tr("Create template"))
        self.btn_make_template.setObjectName("PrimaryButton")
        self.btn_make_template.clicked.connect(self._make_station_template)
        btn_row.addWidget(self.btn_make_template)
        self.btn_import_stations = QPushButton(self.tr("Import from Excel…"))
        self.btn_import_stations.setObjectName("PrimaryButton")
        self.btn_import_stations.clicked.connect(self._import_stations)
        btn_row.addWidget(self.btn_import_stations)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.lbl_station_count = QLabel("")
        lay.addWidget(self.lbl_station_count)
        self._stations_list = QListWidget()
        self._stations_list.setObjectName("BorderedList")
        self._stations_list.setMinimumHeight(120)
        lay.addWidget(self._stations_list, stretch=1)

        manual = QGroupBox(self.tr("Or add one manually"))
        add_row = QHBoxLayout(manual)
        self._ed_bm = QLineEdit()
        self._ed_bm.setPlaceholderText(self.tr("BM number"))
        self._ed_bm.setFixedWidth(120)
        add_row.addWidget(self._ed_bm)
        self._ed_ps_name = QLineEdit()
        self._ed_ps_name.setPlaceholderText(self.tr("Name"))
        add_row.addWidget(self._ed_ps_name, stretch=1)
        self._ed_ps_address = QLineEdit()
        self._ed_ps_address.setPlaceholderText(self.tr("Address"))
        add_row.addWidget(self._ed_ps_address, stretch=1)
        btn_add = QPushButton(self.tr("Add"))
        btn_add.clicked.connect(self._add_station)
        add_row.addWidget(btn_add)
        lay.addWidget(manual)

        btn_remove = QPushButton(self.tr("Remove selected"))
        btn_remove.clicked.connect(self._remove_station)
        lay.addWidget(btn_remove, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addLayout(self._nav_row(back=_P_FOLDER, next_page=_P_ELECTION,
                                    next_label=self.tr("Next →"),
                                    next_guard=self._stations_page_valid))
        self._refresh_stations()
        return page

    def _build_election(self) -> QWidget:
        page, lay = self._page()

        lay.addWidget(self._header(self.tr("Election cycle")))

        types_box = QGroupBox(self.tr("Election types (select all that apply)"))
        types_lay = QVBoxLayout(types_box)
        self._type_checks: dict[str, ToggleSwitch] = {}
        for key, label in _ELECTION_TYPES:
            cb = ToggleSwitch(label)
            types_lay.addWidget(cb)
            self._type_checks[key] = cb
        lay.addWidget(types_box)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._dt_election = make_date_picker()
        self._dt_election.setDate(QDate.currentDate().addDays(30))
        form.addRow(self.tr("Election date:"), self._dt_election)
        lay.addLayout(form)

        lay.addStretch()
        lay.addLayout(self._nav_row(back=_P_STATIONS, next_page=_P_DONE,
                                    next_label=self.tr("Finish"),
                                    next_guard=self._election_page_valid,
                                    next_action=self._save_all))
        return page

    def _build_done(self) -> QWidget:
        page, lay = self._page()
        lay.setSpacing(16)

        lay.addWidget(self._header(self.tr("Setup complete")))

        self._done_msg = QLabel(self.tr(
            "Basic configuration has been saved.\n\n"
            "Next step: Election configuration — parties, candidates,\n"
            "deadlines and the RIK decision for this election cycle."
        ))
        self._done_msg.setWordWrap(True)
        lay.addWidget(self._done_msg)
        lay.addStretch()

        btn_izborna = QPushButton(self.tr("Election configuration  →"))
        btn_izborna.setObjectName("PrimaryButton")
        btn_izborna.clicked.connect(lambda: self._finish_navigate(SECTION_IZBORNA))
        lay.addWidget(btn_izborna)

        btn_start = QPushButton(self.tr("Start working"))
        btn_start.clicked.connect(self.accept)
        lay.addWidget(btn_start)

        return page

    # ── Shared helpers ────────────────────────────────────────────────

    def _header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        font = lbl.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        lbl.setFont(font)
        return lbl

    def _nav_row(
        self,
        back: int | None = None,
        next_page: int | None = None,
        next_label: str = "Next →",
        next_guard=None,
        next_action=None,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        if back is not None:
            btn_back = QPushButton(self.tr("← Back"))
            btn_back.clicked.connect(lambda: self._go(back))
            row.addWidget(btn_back)
        row.addStretch()
        if next_page is not None:
            btn_next = QPushButton(next_label)
            btn_next.setObjectName("PrimaryButton")

            def _on_next():
                if next_guard and not next_guard():
                    return
                if next_action:
                    next_action()
                self._go(next_page)

            btn_next.clicked.connect(_on_next)
            row.addWidget(btn_next)
        return row

    def _go(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    # ── Commission page logic ─────────────────────────────────────────

    def _selected_entry(self) -> opstine_mod.OpstinaEntry | None:
        sifra = self.cb_municipality.currentData()
        return opstine_mod.find_by_sifra(sifra) if sifra else None

    def _on_municipality_activated(self, index: int) -> None:
        self._apply_municipality(self.cb_municipality.itemData(index) or "")

    def _on_municipality_typed(self) -> None:
        entry = opstine_mod.find_by_name(self.cb_municipality.currentText())
        if entry is not None:
            self._apply_municipality(entry.sifra)

    def _apply_municipality(self, sifra: str) -> None:
        from biracki_odbor.config.declension import place_to_genitive, place_to_locative
        entry = opstine_mod.find_by_sifra(sifra)
        if entry is None:
            return
        self.cb_municipality.setCurrentIndex(self.cb_municipality.findData(entry.sifra))
        name = entry.document_name
        gen = place_to_genitive(name)
        self._ed_mun_gen.setText(gen)
        self._ed_mun_loc.setText(entry.doc_locative or place_to_locative(name))
        self._ed_mun_full.setText(default_full_committee_name(entry.vrsta, name, gen))
        info = self.tr("Code {sifra} · {okrug}").format(sifra=entry.sifra, okrug=entry.okrug)
        info += " · " + self._vrsta_label(entry.vrsta)
        if entry.is_vojvodina:
            info += " · " + self.tr("AP Vojvodina")
        self.lbl_municipality_info.setText(info)

    def _vrsta_label(self, vrsta: str) -> str:
        if vrsta == opstine_mod.VRSTA_GRAD:
            return self.tr("City")
        if vrsta == opstine_mod.VRSTA_GRADSKA_OPSTINA:
            return self.tr("City municipality")
        return self.tr("Municipality")

    def _oik_page_valid(self) -> bool:
        if self._selected_entry() is None:
            QMessageBox.warning(self, self.tr("Required"),
                                self.tr("Pick the municipality from the list."))
            return False
        if not self._ed_chairman.text().strip():
            QMessageBox.warning(self, self.tr("Required"),
                                self.tr("Chairman name is required — it is printed on every decision."))
            return False
        return True

    # ── Folder page logic ─────────────────────────────────────────────

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("Select folder"), self._ed_folder.text())
        if path:
            self._ed_folder.setText(path)

    def _folder_page_valid(self) -> bool:
        folder = Path(self._ed_folder.text().strip())
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, self.tr("Invalid"),
                                self.tr("Cannot use this folder: {e}").format(e=e))
            return False
        # In memory now so files_dir() points here for the template step;
        # persisted together with everything else in _save_all().
        self.state.app_settings.default_files_dir = str(folder)
        return True

    # ── Stations page logic ───────────────────────────────────────────

    def _template_path(self) -> Path:
        return self.state.files_dir(STATIONS_PURPOSE) / STATIONS_TEMPLATE_NAME

    def _make_station_template(self) -> None:
        from biracki_odbor.core.template import build_bm_workbook
        path = self._template_path()
        if path.exists():
            reply = QMessageBox.question(
                self, self.tr("Template exists"),
                self.tr("{path} already exists. Replace it with an empty template?\n\n"
                        "Choose No to open the existing file.").format(path=path),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self._open_file(path)
                return
        try:
            build_bm_workbook([], path)
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        log.info("setup wizard: blank polling station template written to %s", path)
        self._open_file(path)

    def _open_file(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # noqa: S606
        except OSError:
            log.warning("could not open %s", path, exc_info=True)
            QMessageBox.information(self, self.tr("Template"),
                                    self.tr("Open this file in Excel: {path}").format(path=path))

    def _import_stations(self) -> None:
        start = self._template_path()
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select bm.xlsx"), str(start if start.exists() else start.parent),
            self.tr("Excel files (*.xlsx)"),
        )
        if path:
            self._import_stations_from(Path(path))

    def _import_stations_from(self, path: Path) -> None:
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.core.template import read_bm_sheet
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(path)
        if not safety.ok:
            QMessageBox.warning(self, self.tr("Invalid file"), _msg(safety.code, file=path.name))
            return
        stations, errors = read_bm_sheet(path)
        if errors:
            QMessageBox.warning(self, self.tr("Invalid file"), "\n".join(errors))
            return
        self._stations = {}
        for ps in stations:
            if not ps.full_name.strip():
                ps.full_name = default_station_full_name(ps.name, ps.address)
            self._stations[ps.bm_number] = ps
        self._refresh_stations()

    def _refresh_stations(self) -> None:
        self.lbl_station_count.setText(
            self.tr("Polling stations added: {n}").format(n=len(self._stations))
        )
        self._stations_list.clear()
        for bm in sorted(self._stations):
            ps = self._stations[bm]
            item = QListWidgetItem(f"БМ {bm} — {ps.full_name}")
            item.setData(Qt.ItemDataRole.UserRole, bm)
            self._stations_list.addItem(item)

    def _add_station(self) -> None:
        bm_text = self._ed_bm.text().strip()
        name = self._ed_ps_name.text().strip()
        address = self._ed_ps_address.text().strip()
        if not bm_text or not name:
            QMessageBox.warning(self, self.tr("Required"), self.tr("BM number and name are required."))
            return
        try:
            bm = int(bm_text)
            if bm <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, self.tr("Invalid"), self.tr("BM number must be a positive integer."))
            return
        if bm in self._stations:
            QMessageBox.warning(self, self.tr("Duplicate"), self.tr("BM {n} already added.").format(n=bm))
            return
        self._stations[bm] = PollingStation(
            bm_number=bm, name=name, address=address,
            full_name=default_station_full_name(name, address),
        )
        self._refresh_stations()
        self._ed_bm.clear()
        self._ed_ps_name.clear()
        self._ed_ps_address.clear()
        self._ed_bm.setFocus()

    def _remove_station(self) -> None:
        for item in self._stations_list.selectedItems():
            self._stations.pop(item.data(Qt.ItemDataRole.UserRole), None)
        self._refresh_stations()

    def _stations_page_valid(self) -> bool:
        if not self._stations:
            QMessageBox.warning(self, self.tr("Required"),
                                self.tr("Add at least one polling station."))
            return False
        return True

    # ── Election page logic ───────────────────────────────────────────

    def _election_page_valid(self) -> bool:
        if not any(cb.isChecked() for cb in self._type_checks.values()):
            QMessageBox.warning(self, self.tr("Required"),
                                self.tr("Select at least one election type."))
            return False
        return True

    # ── Save ──────────────────────────────────────────────────────────

    def _save_all(self) -> None:
        from biracki_odbor.config.declension import format_serbian_date
        from biracki_odbor.config.oik import Chairman, Municipality

        entry = self._selected_entry()
        oik = self.state._oik  # noqa: SLF001
        oik.municipality = Municipality(
            name=entry.document_name,
            name_genitive=self._ed_mun_gen.text().strip(),
            name_locative=self._ed_mun_loc.text().strip(),
            full_committee_name=self._ed_mun_full.text().strip(),
            is_vojvodina=entry.is_vojvodina,
            website=self._ed_website.text().strip(),
            sifra_opstine=entry.sifra,
        )
        oik.chairman = Chairman(title=oik.chairman.title, name=self._ed_chairman.text().strip())
        oik.nacelnik_full_name = NACELNIK_ROLES[entry.vrsta]
        oik.polling_stations = [self._stations[bm] for bm in sorted(self._stations)]
        self.state.save_oik()

        settings = self.state.app_settings
        settings.default_files_dir = self._ed_folder.text().strip()
        settings.oik_email = self._ed_email.text().strip()
        self.state.save_app_settings()

        ec = self.state._election  # noqa: SLF001
        qd = self._dt_election.date()
        ec.election.dates.date_full = format_serbian_date(qd.year(), qd.month(), qd.day())
        ec.election.types = [k for k, cb in self._type_checks.items() if cb.isChecked()]
        self.state.save_election()

    # ── Restore page logic ────────────────────────────────────────────

    def _pick_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select backup .zip"), str(Path.home()), "ZIP (*.zip)",
        )
        if path:
            self._ed_zip.setText(path)
            self._btn_do_restore.setEnabled(True)
            self._restore_log.clear()

    def _do_restore(self) -> None:
        from biracki_odbor.core.backup import inspect_zip, restore_from_zip
        from biracki_odbor import app_paths
        zip_path = Path(self._ed_zip.text())
        home = app_paths.home()
        self._restore_log.clear()
        self._btn_do_restore.setEnabled(False)
        try:
            info = inspect_zip(zip_path, home)
            if info.has_stale_entries:
                self._restore_log.appendPlainText(
                    self.tr("Warning: some files in the backup are older than existing files.")
                )
            result = restore_from_zip(zip_path, home, make_pre_restore_backup=False)
            self._restore_log.appendPlainText(
                self.tr("Restored {n} files. Click Finish to continue.").format(
                    n=len(result.restored_files)
                )
            )
            self.state.reload_oik()
            self.state.reload_election()
            self._go(_P_DONE)
            self._done_msg.setText(self.tr(
                "Configuration restored from backup.\n\n"
                "You can start working right away."
            ))
        except Exception as exc:  # noqa: BLE001
            self._restore_log.appendPlainText(self.tr("Error: {e}").format(e=exc))
            self._btn_do_restore.setEnabled(True)

    # ── Done page ─────────────────────────────────────────────────────

    def _finish_navigate(self, section: int) -> None:
        self.requested_section = section
        self.accept()
