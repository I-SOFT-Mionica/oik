"""Посматрачи workspace — observer accreditation workflow.

Three inner tabs:
  0. Легитимација  — legitimacija layout builder (block editor + card setup)
  1. Акредитација  — orgs + observers in one place, Excel import
  2. Документи     — generate master list, per-BM lists, legitimacije

OIK is only responsible for observers when local elections are present
in the election cycle (enforced by the sidebar gate, not here).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QDoubleValidator, QFont, QFontMetrics, QIntValidator, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.core.observers import (
    ALL_BLOCK_TYPES, BLOCK_LABELS,
    BLOCK_STATIC_TEXT, BLOCK_FIELD_NAME, BLOCK_FIELD_ORG, BLOCK_FIELD_ID,
    BLOCK_FIELD_BM, BLOCK_FIELD_SERIAL, BLOCK_FIELD_MUNICIPALITY,
    BLOCK_FIELD_ELECTION, BLOCK_DIVIDER, BLOCK_SPACER,
    BLOCK_STAMP_BOX, BLOCK_SIGNATURE_LINE,
    AccreditingOrg, CardSetup, LegitimacijaBlock, Observer, ObserverRegistry,
    PAPER_SIZES, default_legitimacija_layout, validate_observer,
)
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
from biracki_odbor.gui.widgets.searchable_table import SearchableTable
from biracki_odbor.gui.worker import start_worker


log = logging.getLogger(__name__)


def _election_label(state: "AppState") -> str:
    """Return a human-readable election label with year.

    Single type  → "Локални избори 2024"
    Multiple     → "Комбиновани избори 2024"
    """
    from biracki_odbor.config.declension import TYPE_LABELS
    types = state.election.election.types or []
    year = state.election.election.dates.year or ""
    if not types:
        return year
    if len(types) == 1:
        return f"{TYPE_LABELS.get(types[0], types[0])} {year}".strip()
    return f"Комбиновани избори {year}".strip()


# ── Edit dialogs ─────────────────────────────────────────────────────


class _OrgEditDialog(QDialog):
    def __init__(self, org: AccreditingOrg | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Accredited organization"))
        self.setMinimumWidth(420)

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 8)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText(self.tr("Organization name"))
        form.addRow(self.tr("Name:"), self.ed_name)

        self.ed_contact = QLineEdit()
        self.ed_contact.setPlaceholderText(self.tr("Contact person / phone / email"))
        form.addRow(self.tr("Contact:"), self.ed_contact)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Прихвати")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Откажи")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        if org:
            self.ed_name.setText(org.name)
            self.ed_contact.setText(org.contact)

        self._result: AccreditingOrg | None = None

    def _on_accept(self) -> None:
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, self.tr("Error"), self.tr("Enter the organization name."))
            return
        self._result = AccreditingOrg(name=name, contact=self.ed_contact.text().strip())
        self.accept()

    @property
    def result_org(self) -> AccreditingOrg | None:
        return self._result


class _ObserverEditDialog(QDialog):
    def __init__(
        self,
        observer: Observer | None = None,
        org_names: list[str] | None = None,
        preset_org: str = "",
        registry: ObserverRegistry | None = None,
        existing_index: int | None = None,
        election_date_iso: str = "",
        master_jmbgs: set[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Observer"))
        self.setMinimumWidth(520)
        self._registry = registry or ObserverRegistry()
        self._existing_index = existing_index
        self._election_date_iso = election_date_iso
        self._master_jmbgs = master_jmbgs or set()

        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 8)

        self.ed_last = QLineEdit()
        self.ed_last.setPlaceholderText(self.tr("Last name"))
        form.addRow(self.tr("Last name:"), self.ed_last)

        self.ed_first = QLineEdit()
        self.ed_first.setPlaceholderText(self.tr("First name"))
        form.addRow(self.tr("First name:"), self.ed_first)

        self.ed_jmbg = QLineEdit()
        self.ed_jmbg.setPlaceholderText(self.tr("13 digits"))
        self.ed_jmbg.setMaxLength(13)
        form.addRow(self.tr("JMBG:"), self.ed_jmbg)

        self.cb_org = QComboBox()
        self.cb_org.setEditable(True)
        self.cb_org.setMinimumWidth(340)
        # Organization names can be long ("Центар за европске вредности" etc.) —
        # the popup list defaults to the combo's own width and truncates them,
        # so widen it separately from the closed-state box.
        self.cb_org.view().setMinimumWidth(420)
        for name in (org_names or []):
            self.cb_org.addItem(name)
        if preset_org:
            idx = self.cb_org.findText(preset_org)
            self.cb_org.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(self.tr("Organization:"), self.cb_org)

        self.ed_bm = QLineEdit()
        self.ed_bm.setPlaceholderText(self.tr("e.g. All PS or PS 01, PS 03"))
        form.addRow(self.tr("PS assignment:"), self.ed_bm)

        self.ed_serial = QLineEdit()
        self.ed_serial.setPlaceholderText(self.tr("leave empty if not needed"))
        form.addRow(self.tr("ID card number:"), self.ed_serial)

        self.ed_notes = QLineEdit()
        form.addRow(self.tr("Note:"), self.ed_notes)

        self._validation_label = QLabel("")
        self._validation_label.setObjectName("ErrorLabel")
        self._validation_label.setWordWrap(True)
        form.addRow(self._validation_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Прихвати")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Откажи")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        if observer:
            self.ed_last.setText(observer.last_name)
            self.ed_first.setText(observer.first_name)
            self.ed_jmbg.setText(observer.jmbg)
            org_idx = self.cb_org.findText(observer.organization)
            if org_idx >= 0:
                self.cb_org.setCurrentIndex(org_idx)
            else:
                self.cb_org.setEditText(observer.organization)
            self.ed_bm.setText(observer.bm_assignment)
            self.ed_serial.setText(observer.serial_number)
            self.ed_notes.setText(observer.notes)

        self._result: Observer | None = None

    def _on_accept(self) -> None:
        first = self.ed_first.text().strip()
        last = self.ed_last.text().strip()
        if not first or not last:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("Enter first name and last name.")
            )
            return
        org = self.cb_org.currentText().strip()
        if not org:
            QMessageBox.warning(
                self, self.tr("Error"),
                self.tr("Select or enter an organization name.")
            )
            return
        bm = self.ed_bm.text().strip()
        if not bm:
            QMessageBox.warning(
                self, self.tr("Error"),
                self.tr("Enter the polling station assignment (e.g. 'All PS').")
            )
            return

        ob = Observer(
            first_name=first,
            last_name=last,
            organization=org,
            bm_assignment=bm,
            jmbg=self.ed_jmbg.text().strip(),
            serial_number=self.ed_serial.text().strip(),
            notes=self.ed_notes.text().strip(),
        )

        v = validate_observer(
            ob, self._registry,
            election_date_iso=self._election_date_iso,
            master_jmbgs=self._master_jmbgs,
            existing_index=self._existing_index,
        )
        if v.member_conflict:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr(
                    "A person with this JMBG is already a polling board member\n"
                    "and cannot be an observer."
                ),
            )
            return
        if v.underage:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("The observer must be at least 18 years old on election day."),
            )
            return

        warnings = []
        if v.jmbg_invalid:
            warnings.append(self.tr("JMBG does not pass MOD 11 check."))
        if v.jmbg_duplicate:
            warnings.append(self.tr("An observer with the same JMBG already exists in the list."))
        if warnings:
            ans = QMessageBox.question(
                self, self.tr("Warning"),
                "\n".join(warnings) + "\n\n" + self.tr("Continue?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        self._result = ob
        self.accept()

    @property
    def result_observer(self) -> Observer | None:
        return self._result


# ── Tab 1: Акредитација (orgs + observers merged) ────────────────────


class _AkreditacijaTab(QWidget):
    """Orgs and observers in a single tab.

    Top group: compact org list with Add/Edit/Delete.
    Bottom group: observer list with Add/Edit/Delete + Excel import.
    Clicking 'Додај посматрача' pre-fills the currently selected org.
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.banner = StatusBanner(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(self.banner)

        # ── Orgs section ───────────────────────────────────────────
        self._orgs_section = CollapsibleSection(self.tr("Accredited organizations"))

        btn_org_import_qa = QPushButton(self.tr("Import"))
        btn_org_import_qa.clicked.connect(self._import_orgs_excel)
        self._orgs_section.add_quick_action(btn_org_import_qa)

        orgs_body = QWidget()
        orgs_root = QVBoxLayout(orgs_body)
        orgs_root.setContentsMargins(0, 0, 0, 0)
        orgs_root.setSpacing(6)

        self.orgs_table = SearchableTable(
            column_labels=[self.tr("Name"), self.tr("Contact")],
            parent=self,
        )
        self.orgs_table.table.setColumnWidth(0, 200)  # Назив — fixed; Контакт stretches
        self.orgs_table.row_activated.connect(self._edit_org)
        orgs_root.addWidget(self.orgs_table, stretch=1)

        orgs_btns = QHBoxLayout()
        btn_org_add = QPushButton(self.tr("Add organization"))
        btn_org_add.clicked.connect(self._add_org)
        orgs_btns.addWidget(btn_org_add)
        btn_org_edit = QPushButton(self.tr("Edit"))
        btn_org_edit.clicked.connect(lambda: self._edit_org(self.orgs_table.selected_original_index() or 0))
        orgs_btns.addWidget(btn_org_edit)
        btn_org_del = QPushButton(self.tr("Delete"))
        btn_org_del.setObjectName("DangerButton")
        btn_org_del.clicked.connect(self._delete_org)
        orgs_btns.addWidget(btn_org_del)
        orgs_btns.addStretch()
        btn_org_template = QPushButton(self.tr("Export"))
        btn_org_template.setToolTip(self.tr("Export a blank organizations template. Excel format: Name | Contact"))
        btn_org_template.clicked.connect(self._export_orgs_template)
        orgs_btns.addWidget(btn_org_template)
        btn_org_import = QPushButton(self.tr("Import"))
        btn_org_import.setToolTip(self.tr("Excel format: Name | Contact"))
        btn_org_import.clicked.connect(self._import_orgs_excel)
        orgs_btns.addWidget(btn_org_import)
        orgs_root.addLayout(orgs_btns)

        self._orgs_section.set_content(orgs_body)
        root.addWidget(self._orgs_section, stretch=1)

        # ── Observers section ──────────────────────────────────────
        self._obs_section = CollapsibleSection(self.tr("Observers"))

        btn_obs_import_qa = QPushButton(self.tr("Import"))
        btn_obs_import_qa.clicked.connect(self._import_excel)
        self._obs_section.add_quick_action(btn_obs_import_qa)

        obs_body = QWidget()
        obs_root = QVBoxLayout(obs_body)
        obs_root.setContentsMargins(0, 0, 0, 0)
        obs_root.setSpacing(6)

        self.obs_table = SearchableTable(
            column_labels=[
                self.tr("Last name"), self.tr("First name"), self.tr("JMBG"),
                self.tr("Organization"), self.tr("PS assignment"), self.tr("ID no."),
            ],
            parent=self,
        )
        _oh = self.obs_table.table.horizontalHeader()
        for col, (mode, width) in enumerate([
            (QHeaderView.ResizeMode.Interactive, 130),   # Презиме
            (QHeaderView.ResizeMode.Interactive, 110),   # Ime
            (QHeaderView.ResizeMode.Interactive, 115),   # ЈМБГ
            (QHeaderView.ResizeMode.Stretch,     0),     # Организација — fills remaining
            (QHeaderView.ResizeMode.Interactive, 85),    # Расп. БМ
            (QHeaderView.ResizeMode.Interactive, 72),    # Бр.лег.
        ]):
            _oh.setSectionResizeMode(col, mode)
            if mode != QHeaderView.ResizeMode.Stretch:
                self.obs_table.table.setColumnWidth(col, width)
        self.obs_table.row_activated.connect(self._edit_observer)
        obs_root.addWidget(self.obs_table, stretch=1)

        obs_btns = QHBoxLayout()
        btn_obs_add = QPushButton(self.tr("Add observer"))
        btn_obs_add.clicked.connect(self._add_observer)
        obs_btns.addWidget(btn_obs_add)
        btn_obs_edit = QPushButton(self.tr("Edit"))
        btn_obs_edit.clicked.connect(lambda: self._edit_observer(self.obs_table.selected_original_index() or 0))
        obs_btns.addWidget(btn_obs_edit)
        btn_obs_del = QPushButton(self.tr("Delete"))
        btn_obs_del.setObjectName("DangerButton")
        btn_obs_del.clicked.connect(self._delete_observer)
        obs_btns.addWidget(btn_obs_del)
        obs_btns.addStretch()
        btn_obs_template = QPushButton(self.tr("Export"))
        btn_obs_template.setToolTip(self.tr("Export a blank observers template."))
        btn_obs_template.clicked.connect(self._export_observers_template)
        obs_btns.addWidget(btn_obs_template)
        btn_import = QPushButton(self.tr("Import"))
        btn_import.setToolTip(
            self.tr(
                "Excel format: Last name | First name | JMBG | Organization"
                " | PS assignment | ID no. (opt.) | Note (opt.)"
            )
        )
        btn_import.clicked.connect(self._import_excel)
        obs_btns.addWidget(btn_import)
        obs_root.addLayout(obs_btns)

        self._obs_section.set_content(obs_body)
        root.addWidget(self._obs_section, stretch=1)
        root.addStretch()

        self.state.posmatraci_changed.connect(self._reload)
        self._reload()

    # ── Reload ───────────────────────────────────────────────────

    def _reload(self) -> None:
        registry = self.state.observer_registry
        self.orgs_table.set_rows([(o.name, o.contact) for o in registry.orgs])
        self.obs_table.set_rows([
            (ob.last_name, ob.first_name, ob.display_id,
             ob.organization, ob.bm_assignment, ob.serial_number)
            for ob in registry.observers
        ])
        self._orgs_section.set_count(len(registry.orgs) or None)
        self._obs_section.set_count(len(registry.observers) or None)
        dups = registry.jmbg_duplicates()
        if dups:
            self.banner.show_error(
                self.tr("Warning — JMBG duplicates: {dups}").format(dups=", ".join(dups))
            )
        else:
            self.banner.clear()

    # ── Shared helpers ────────────────────────────────────────────

    def _master_jmbgs(self) -> set[str]:
        from biracki_odbor.core import master_io
        from biracki_odbor.core.workflow import STALNI_SPEC, PROSIRENI_SPEC
        jmbgs: set[str] = set()
        committee_db = app_paths.committee_db_path()
        for spec in (STALNI_SPEC, PROSIRENI_SPEC):
            try:
                for person in master_io.read_master(committee_db, spec=spec):
                    if person.jmbg:
                        jmbgs.add(person.jmbg)
            except Exception:  # noqa: BLE001
                pass
        return jmbgs

    def _election_date_iso(self) -> str:
        from biracki_odbor.config import declension
        parsed = declension.parse_serbian_date(self.state.election.election.dates.date_full)
        if parsed:
            y, m, d = parsed
            return f"{y:04d}-{m:02d}-{d:02d}"
        return ""

    def _selected_org_name(self) -> str:
        idx = self.orgs_table.selected_original_index()
        if idx is None:
            return ""
        orgs = self.state.observer_registry.orgs
        return orgs[idx].name if idx < len(orgs) else ""

    # ── Org actions ───────────────────────────────────────────────

    def _add_org(self) -> None:
        dlg = _OrgEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_org:
            self.state.observer_registry.orgs.append(dlg.result_org)
            self.state.save_observer_registry()

    def _edit_org(self, row_index: int) -> None:
        if row_index < 0:
            return
        registry = self.state.observer_registry
        if row_index >= len(registry.orgs):
            return
        dlg = _OrgEditDialog(org=registry.orgs[row_index], parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_org:
            registry.orgs[row_index] = dlg.result_org
            self.state.save_observer_registry()

    def _delete_org(self) -> None:
        idx = self.orgs_table.selected_original_index()
        if idx is None:
            return
        registry = self.state.observer_registry
        if idx >= len(registry.orgs):
            return
        ans = QMessageBox.question(
            self, self.tr("Delete"),
            self.tr("Delete organization «{name}»?").format(name=registry.orgs[idx].name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            registry.orgs.pop(idx)
            self.state.save_observer_registry()

    # ── Observer actions ──────────────────────────────────────────

    def _add_observer(self) -> None:
        registry = self.state.observer_registry
        dlg = _ObserverEditDialog(
            org_names=registry.org_names(),
            preset_org=self._selected_org_name(),
            registry=registry,
            election_date_iso=self._election_date_iso(),
            master_jmbgs=self._master_jmbgs(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_observer:
            registry.observers.append(dlg.result_observer)
            self.state.save_observer_registry()

    def _edit_observer(self, row_index: int) -> None:
        if row_index < 0:
            return
        registry = self.state.observer_registry
        if row_index >= len(registry.observers):
            return
        dlg = _ObserverEditDialog(
            observer=registry.observers[row_index],
            org_names=registry.org_names(),
            registry=registry,
            existing_index=row_index,
            election_date_iso=self._election_date_iso(),
            master_jmbgs=self._master_jmbgs(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_observer:
            registry.observers[row_index] = dlg.result_observer
            self.state.save_observer_registry()

    def _delete_observer(self) -> None:
        idx = self.obs_table.selected_original_index()
        if idx is None:
            return
        registry = self.state.observer_registry
        if idx >= len(registry.observers):
            return
        ob = registry.observers[idx]
        ans = QMessageBox.question(
            self, self.tr("Delete"),
            self.tr("Delete observer «{name}»?").format(name=ob.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            registry.observers.pop(idx)
            self.state.save_observer_registry()

    # ── Excel import ──────────────────────────────────────────────

    def _import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import observers from Excel"),
            str(self.state.files_dir("Посматрачи")), "Excel (*.xlsx *.xls)",
        )
        if not path:
            return
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True)) if ws is not None else []
            wb.close()
        except Exception as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot open file:\n{error}").format(error=e)
            )
            return

        registry = self.state.observer_registry
        existing_org_names = {o.name.lower() for o in registry.orgs}
        new_orgs: list[AccreditingOrg] = []
        new_obs: list[Observer] = []
        skipped = 0

        for row in rows:
            # Pad to 7 columns
            cells = list(row) + [None] * 7
            last   = str(cells[0] or "").strip()
            first  = str(cells[1] or "").strip()
            jmbg   = str(cells[2] or "").strip()
            org    = str(cells[3] or "").strip()
            bm     = str(cells[4] or "").strip()
            serial = str(cells[5] or "").strip()
            notes  = str(cells[6] or "").strip()

            if not last or not first or not org or not bm:
                skipped += 1
                continue

            if org.lower() not in existing_org_names and org.lower() not in {o.name.lower() for o in new_orgs}:
                new_orgs.append(AccreditingOrg(name=org))

            new_obs.append(Observer(
                first_name=first, last_name=last,
                organization=org, bm_assignment=bm,
                jmbg=jmbg, serial_number=serial, notes=notes,
            ))

        if not new_obs and not new_orgs:
            QMessageBox.information(
                self, self.tr("Import"), self.tr("No valid rows to import.")
            )
            return

        msg = self.tr("Found {n} observer(s)").format(n=len(new_obs))
        if new_orgs:
            msg += self.tr(" and {n} new organization(s)").format(n=len(new_orgs))
        if skipped:
            msg += self.tr(" ({n} rows skipped — incomplete data)").format(n=skipped)
        msg += ".\n\n" + self.tr("Add to registry?")

        ans = QMessageBox.question(
            self, self.tr("Confirm import"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        registry.orgs.extend(new_orgs)
        registry.observers.extend(new_obs)
        self.state.save_observer_registry()

    def _import_orgs_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import organizations from Excel"),
            str(self.state.files_dir("Посматрачи")), "Excel (*.xlsx *.xls)",
        )
        if not path:
            return
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(min_row=2, values_only=True)) if ws is not None else []
            wb.close()
        except Exception as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot open file:\n{error}").format(error=e)
            )
            return

        registry = self.state.observer_registry
        existing_names = {o.name.lower() for o in registry.orgs}
        new_orgs: list[AccreditingOrg] = []
        skipped = 0

        for row in rows:
            cells = list(row) + [None] * 2
            name = str(cells[0] or "").strip()
            contact = str(cells[1] or "").strip()
            if not name:
                skipped += 1
                continue
            if name.lower() in existing_names or name.lower() in {o.name.lower() for o in new_orgs}:
                skipped += 1
                continue
            new_orgs.append(AccreditingOrg(name=name, contact=contact))

        if not new_orgs:
            QMessageBox.information(
                self, self.tr("Import"), self.tr("No valid rows to import.")
            )
            return

        msg = self.tr("Found {n} organization(s)").format(n=len(new_orgs))
        if skipped:
            msg += self.tr(" ({n} rows skipped — empty or duplicate name)").format(n=skipped)
        msg += ".\n\n" + self.tr("Add to registry?")

        ans = QMessageBox.question(
            self, self.tr("Confirm import"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        registry.orgs.extend(new_orgs)
        self.state.save_observer_registry()

    # ── Excel template export ────────────────────────────────────

    def _export_orgs_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export organizations template"),
            str(self.state.files_dir("Посматрачи") / "posmatraci_organizacije.xlsx"),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Организације"
            for c, h in enumerate((self.tr("Name"), self.tr("Contact")), start=1):
                ws.cell(row=1, column=c, value=h).font = openpyxl.styles.Font(bold=True)
            ws.column_dimensions["A"].width = 32
            ws.column_dimensions["B"].width = 32
            wb.save(path)
            wb.close()
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot write template:\n{error}").format(error=e),
            )
            return
        self.banner.show_ok(self.tr("Template exported: {path}").format(path=path))

    def _export_observers_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export observers template"),
            str(self.state.files_dir("Посматрачи") / "posmatraci_lista.xlsx"),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Посматрачи"
            headers = (
                self.tr("Last name"), self.tr("First name"), self.tr("JMBG"),
                self.tr("Organization"), self.tr("PS assignment"),
                self.tr("ID no. (opt.)"), self.tr("Note (opt.)"),
            )
            for c, h in enumerate(headers, start=1):
                ws.cell(row=1, column=c, value=h).font = openpyxl.styles.Font(bold=True)
            for col, width in zip("ABCDEFG", (16, 16, 15, 28, 18, 12, 24)):
                ws.column_dimensions[col].width = width
            wb.save(path)
            wb.close()
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot write template:\n{error}").format(error=e),
            )
            return
        self.banner.show_ok(self.tr("Template exported: {path}").format(path=path))


# ── Tab 2: Документи ──────────────────────────────────────────────────


class _DocumentiTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.banner = StatusBanner(self)
        self._workers: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        title = QLabel(self.tr("Document generation"))
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        root.addWidget(self.banner)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # Master list
        master_box = QGroupBox(self.tr("1. Master list"))
        master_layout = QVBoxLayout(master_box)
        master_hint = QLabel(
            self.tr(
                "Excel table of all observers, sorted by PS and organization.\n"
                "Output: posmatraci/master_posmatraci.xlsx"
            )
        )
        master_hint.setObjectName("MutedLabel")
        master_hint.setWordWrap(True)
        master_layout.addWidget(master_hint)
        self.btn_master = QPushButton(self.tr("Generate master list"))
        self.btn_master.setObjectName("PrimaryButton")
        self.btn_master.clicked.connect(self._generate_master)
        master_layout.addWidget(self.btn_master)
        root.addWidget(master_box)

        # Per-BM lists
        bm_box = QGroupBox(self.tr("2. Lists by polling station"))
        bm_layout = QVBoxLayout(bm_box)
        bm_hint = QLabel(
            self.tr(
                "One Word document per polling station, grouped by organization.\n"
                "Output: posmatraci/liste/"
            )
        )
        bm_hint.setObjectName("MutedLabel")
        bm_hint.setWordWrap(True)
        bm_layout.addWidget(bm_hint)
        self.btn_bm = QPushButton(self.tr("Generate lists by PS"))
        self.btn_bm.setObjectName("PrimaryButton")
        self.btn_bm.clicked.connect(self._generate_bm_lists)
        bm_layout.addWidget(self.btn_bm)
        root.addWidget(bm_box)

        # Legitimacije
        leg_box = QGroupBox(self.tr("3. Observer ID cards"))
        leg_layout = QVBoxLayout(leg_box)
        leg_hint = QLabel(
            self.tr(
                "Word document with observer ID cards for printing.\n"
                "Block layout is configured in OIK Settings → Observers.\n"
                "Output: posmatraci/legitimacije/legitimacije.docx"
            )
        )
        leg_hint.setObjectName("MutedLabel")
        leg_hint.setWordWrap(True)
        leg_layout.addWidget(leg_hint)
        self.btn_leg = QPushButton(self.tr("Generate ID cards"))
        self.btn_leg.setObjectName("PrimaryButton")
        self.btn_leg.clicked.connect(self._generate_legitimacije)
        leg_layout.addWidget(self.btn_leg)
        root.addWidget(leg_box)

        root.addStretch()

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        for btn in (self.btn_master, self.btn_bm, self.btn_leg):
            btn.setEnabled(not busy)

    def _generate_master(self) -> None:
        from biracki_odbor.core.posmatraci_docx import (
            generate_master_list, posmatraci_paths,
        )
        observers = list(self.state.observer_registry.observers)
        out = posmatraci_paths(app_paths.home())["master"]
        self._set_busy(True)

        def _run():
            generate_master_list(observers, out)
            return out

        worker, thread = start_worker(self, _run)
        self._workers.append((worker, thread))
        # Bound methods, not lambdas — a signal connected to a bare
        # lambda (no QObject anchoring its lifetime) can silently fail
        # to fire even after emit() "succeeds"; see prosireni_workspace's
        # _run() for a confirmed repro of exactly this failure mode.
        worker.finished.connect(self._on_master_done)
        worker.failed.connect(self._on_failed)

    def _on_master_done(self, out_path) -> None:
        self._set_busy(False)
        self.state.export_generated("Посматрачи документи", [out_path])
        self.banner.show_ok(self.tr("Master list: {path}").format(path=out_path))

    def _generate_bm_lists(self) -> None:
        from biracki_odbor.core.posmatraci_docx import (
            generate_bm_lists, posmatraci_paths,
        )
        observers = list(self.state.observer_registry.observers)
        election_name = _election_label(self.state)
        out_dir = posmatraci_paths(app_paths.home())["liste_dir"]
        self._set_busy(True)

        def _run():
            return generate_bm_lists(observers, out_dir, election_name)

        worker, thread = start_worker(self, _run)
        self._workers.append((worker, thread))
        worker.finished.connect(self._on_bm_done)
        worker.failed.connect(self._on_failed)

    def _on_bm_done(self, paths) -> None:
        self._set_busy(False)
        if paths:
            self.state.export_generated("Посматрачи документи", paths)
        count = len(paths) if paths else 0
        self.banner.show_ok(self.tr("Generated {n} lists by PS.").format(n=count))

    def _generate_legitimacije(self) -> None:
        from biracki_odbor.core.posmatraci_docx import (
            generate_legitimacije, posmatraci_paths,
        )
        observers = list(self.state.observer_registry.observers)
        settings = self.state.app_settings.posmatraci
        municipality = self.state.oik.municipality.name
        election_name = _election_label(self.state)
        oik = self.state.oik
        out = posmatraci_paths(app_paths.home())["legitimacije"]
        self._set_busy(True)

        def _run():
            return generate_legitimacije(
                observers, settings,
                municipality=municipality,
                election_name=election_name,
                out_path=out,
                oik=oik,
            )

        worker, thread = start_worker(self, _run)
        self._workers.append((worker, thread))
        worker.finished.connect(self._on_leg_done)
        worker.failed.connect(self._on_failed)

    def _on_leg_done(self, out_path) -> None:
        self._set_busy(False)
        self.state.export_generated("Посматрачи документи", [out_path])
        self.banner.show_ok(self.tr("Observer ID cards: {path}").format(path=out_path))

    def _on_failed(self, err: str) -> None:
        self._set_busy(False)
        self.banner.show_error(self.tr("Error: {err}").format(err=err))


# ── Legitimacija layout editor ────────────────────────────────────────

# Override for the compact ▲▼/Горе/Доле/Уклони buttons.
# The global QPushButton CSS sets padding: 10px 22px which leaves no
# room for text in a narrow button — override per-button with this style.
_COMPACT_BTN = "padding: 3px 8px; font-size: 11pt;"
_COMPACT_BTN_DANGER = _COMPACT_BTN + " color: #9B0000; border-color: #F0B0B0;"

_BLOCK_PREVIEW_COLORS: dict[str, str] = {
    BLOCK_STATIC_TEXT:       "#D0E8F5",
    BLOCK_FIELD_NAME:        "#D5F0DA",
    BLOCK_FIELD_ORG:         "#D5F0DA",
    BLOCK_FIELD_ID:          "#D5F0DA",
    BLOCK_FIELD_BM:          "#D5F0DA",
    BLOCK_FIELD_SERIAL:      "#D5F0DA",
    BLOCK_FIELD_MUNICIPALITY: "#D5F0DA",
    BLOCK_FIELD_ELECTION:    "#D5F0DA",
    BLOCK_DIVIDER:           "#DADADA",
    BLOCK_SPACER:            "#F8F8F8",
    BLOCK_STAMP_BOX:         "#FDEBD0",
    BLOCK_SIGNATURE_LINE:    "#EDE0F5",
}


def _block_preview_text(
    blk: LegitimacijaBlock,
    municipality: str,
    election: str,
    chairman_title: str = "",
    chairman_name: str = "",
) -> str:
    """Return the text that will actually appear in the printed card."""
    if blk.block_type == BLOCK_STATIC_TEXT:
        return (
            blk.value
            .replace("[municipality]", municipality or "Општина")
            .replace("[election]", election or "Назив избора")
        ) or "…"
    title = ((chairman_title + " ОИК") if chairman_title else "ПРЕДСЕДНИК ОИК")
    name = chairman_name or "Пера Перић"
    underline = "_" * max(int(len(name) * 2), 14)
    _computed = {
        BLOCK_FIELD_NAME:         "ПЕРА ПЕРИЋ",
        BLOCK_FIELD_ORG:          "Назив организације",
        BLOCK_FIELD_ID:           "0101990710013",
        BLOCK_FIELD_BM:           "БМ 01",
        BLOCK_FIELD_SERIAL:       "001",
        BLOCK_FIELD_MUNICIPALITY: municipality or "Општина",
        BLOCK_FIELD_ELECTION:     election or "Назив избора",
        BLOCK_STAMP_BOX:          "(М.П.)",
        BLOCK_SIGNATURE_LINE:     f"{title}\n{underline}\n{name}",
    }
    return _computed.get(blk.block_type, BLOCK_LABELS.get(blk.block_type, ""))


class _NoWheelFilter(QObject):
    """Swallows WheelEvents so QComboBox values don't change on scroll."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


_NO_WHEEL_SINGLETON: _NoWheelFilter | None = None


def _no_wheel() -> _NoWheelFilter:
    global _NO_WHEEL_SINGLETON
    if _NO_WHEEL_SINGLETON is None:
        _NO_WHEEL_SINGLETON = _NoWheelFilter()
    return _NO_WHEEL_SINGLETON


class _CardPreview(QWidget):
    """Live painted preview of the legitimacija card layout.

    Scales the card to fit the available area while keeping the aspect
    ratio. Blocks are painted row-by-row using the 12-column grid so
    the preview matches the intended print output.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocks: list[LegitimacijaBlock] = []
        self._card_w_mm = 90.0
        self._card_h_mm = 60.0
        self._municipality = ""
        self._election = ""
        self._chairman_title = ""
        self._chairman_name = ""
        self.setMinimumWidth(200)
        self.setMinimumHeight(200)

    def update_preview(
        self,
        blocks: list[LegitimacijaBlock],
        card_w_mm: float,
        card_h_mm: float,
        municipality: str = "",
        election: str = "",
        chairman_title: str = "",
        chairman_name: str = "",
    ) -> None:
        self._blocks = list(blocks)
        self._card_w_mm = max(20.0, card_w_mm)
        self._card_h_mm = max(20.0, card_h_mm)
        self._municipality = municipality
        self._election = election
        self._chairman_title = chairman_title
        self._chairman_name = chairman_name
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = 20
        avail_w = self.width() - 2 * margin
        avail_h = self.height() - 2 * margin
        if avail_w <= 0 or avail_h <= 0:
            painter.end()
            return

        scale = min(avail_w / self._card_w_mm, avail_h / self._card_h_mm)
        cw = self._card_w_mm * scale
        ch = self._card_h_mm * scale
        cx = margin + (avail_w - cw) / 2
        cy = margin + (avail_h - ch) / 2

        # Drop shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#C0C0C0"))
        painter.drawRoundedRect(QRectF(cx + 3, cy + 3, cw, ch), 4, 4)

        # Card background + border
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#2F5496"), 1.5))
        painter.drawRoundedRect(QRectF(cx, cy, cw, ch), 4, 4)

        # Clip content to card interior
        painter.setClipRect(QRect(int(cx) + 1, int(cy) + 1, int(cw) - 2, int(ch) - 2))

        # Layout: each row_height unit = ch/10, minimum 14 px
        base_h = max(14.0, ch / 10)
        pad = 3.0
        small_font = QFont("Segoe UI", max(6, int(base_h * 0.45)))
        painter.setFont(small_font)

        # Group blocks into rows respecting the 12-column grid
        rows: list[tuple[list, float]] = []
        cur_row: list = []
        cur_col = 0
        cur_row_h = 0.0
        for blk in self._blocks:
            span = max(1, min(12, blk.col_span))
            h = max(1, blk.row_height) * base_h
            if cur_col + span > 12:
                rows.append((list(cur_row), cur_row_h))
                cur_row, cur_col, cur_row_h = [], 0, 0.0
            cur_row.append((blk, span, h))
            cur_col += span
            cur_row_h = max(cur_row_h, h)
        if cur_row:
            rows.append((cur_row, cur_row_h))

        draw_y = cy + pad
        usable_w = cw - 2 * pad

        for row_items, row_h in rows:
            if draw_y + row_h > cy + ch:
                break
            draw_x = cx + pad
            for blk, span, blk_h in row_items:
                bw = (span / 12) * usable_w - 1
                bh = blk_h - 1

                if blk.block_type == BLOCK_DIVIDER:
                    painter.setPen(QPen(QColor("#888888"), 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    mid = draw_y + bh / 2
                    painter.drawLine(int(draw_x), int(mid), int(draw_x + bw), int(mid))
                elif blk.block_type != BLOCK_SPACER:
                    fill = QColor(_BLOCK_PREVIEW_COLORS.get(blk.block_type, "#F0F0F0"))
                    painter.setBrush(fill)
                    painter.setPen(QPen(QColor("#AAAAAA"), 0.5))
                    painter.drawRect(QRectF(draw_x, draw_y, bw, bh))
                    label = _block_preview_text(
                        blk, self._municipality, self._election,
                        self._chairman_title, self._chairman_name,
                    )
                    if label:
                        _h_align = {
                            "left":   Qt.AlignmentFlag.AlignLeft,
                            "center": Qt.AlignmentFlag.AlignHCenter,
                            "right":  Qt.AlignmentFlag.AlignRight,
                        }.get(blk.alignment, Qt.AlignmentFlag.AlignHCenter)
                        text_rect = QRectF(draw_x + 2, draw_y, bw - 4, bh)
                        wrap_flags = int(Qt.AlignmentFlag.AlignVCenter | _h_align | Qt.TextFlag.TextWordWrap)
                        # Shrink font until the wrapped text fits vertically
                        base_font = painter.font()
                        fit_font = QFont(base_font)
                        while fit_font.pointSize() > 5:
                            fm = QFontMetrics(fit_font)
                            br = fm.boundingRect(
                                QRect(0, 0, int(text_rect.width()), 9999),
                                wrap_flags, label,
                            )
                            if br.height() <= text_rect.height():
                                break
                            fit_font.setPointSize(fit_font.pointSize() - 1)
                        if fit_font.pointSize() != base_font.pointSize():
                            painter.setFont(fit_font)
                        painter.setPen(QColor("#1F2A44"))
                        painter.drawText(text_rect, wrap_flags, label)
                        if fit_font.pointSize() != base_font.pointSize():
                            painter.setFont(base_font)
                draw_x += bw + 1
            draw_y += row_h

        painter.end()


class _LegitimacijaBlockCard(QFrame):
    """One block card in the legitimacija layout editor."""

    def __init__(
        self,
        block: LegitimacijaBlock,
        *,
        on_remove,
        on_move_up,
        on_move_down,
        on_changed,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("Card")
        self._block_type = block.block_type
        self._bg = _BLOCK_PREVIEW_COLORS.get(block.block_type, "#F5F5F5")
        self._apply_style(active=False)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # Top row: type label + compact action buttons.
        # setStyleSheet overrides the global padding: 10px 22px rule that
        # would otherwise make narrow buttons show no text at all.
        top = QHBoxLayout()
        type_label = QLabel(f"<b>{BLOCK_LABELS.get(block.block_type, block.block_type)}</b>")
        type_label.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(type_label, stretch=1)

        btn_up = QPushButton(self.tr("Up"))
        btn_up.setStyleSheet(_COMPACT_BTN)
        btn_up.setToolTip(self.tr("Move up"))
        btn_up.clicked.connect(lambda: on_move_up(self))
        top.addWidget(btn_up)

        btn_down = QPushButton(self.tr("Down"))
        btn_down.setStyleSheet(_COMPACT_BTN)
        btn_down.setToolTip(self.tr("Move down"))
        btn_down.clicked.connect(lambda: on_move_down(self))
        top.addWidget(btn_down)

        btn_rm = QPushButton(self.tr("Remove"))
        btn_rm.setStyleSheet(_COMPACT_BTN_DANGER)
        btn_rm.setToolTip(self.tr("Remove block"))
        btn_rm.clicked.connect(lambda: on_remove(self))
        top.addWidget(btn_rm)
        root.addLayout(top)

        # Width (col_span) + height row — QLineEdit for height to avoid
        # the scroll-to-change behavior of QSpinBox.
        props_row = QHBoxLayout()
        props_row.addWidget(QLabel(self.tr("Width:")))
        self._col_combo = QComboBox()
        self._col_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._col_combo.installEventFilter(_no_wheel())
        for c in range(1, 13):
            self._col_combo.addItem(f"{c} / 12", c)
        self._col_combo.setCurrentIndex(max(0, min(11, block.col_span - 1)))
        self._col_combo.setToolTip(
            self.tr(
                "Block width in 12-column grid.\n"
                "12 = full width  |  6 = half  |  4 = third  |  3 = quarter"
            )
        )
        self._col_combo.currentIndexChanged.connect(on_changed)
        props_row.addWidget(self._col_combo)

        props_row.addSpacing(12)
        props_row.addWidget(QLabel(self.tr("Height:")))
        self._row_edit = QLineEdit(str(max(1, block.row_height)))
        self._row_edit.setValidator(QIntValidator(1, 20))
        self._row_edit.setFixedWidth(50)
        self._row_edit.setToolTip(self.tr("Relative block height in rows (1 = standard row)."))
        self._row_edit.editingFinished.connect(on_changed)
        props_row.addWidget(self._row_edit)

        props_row.addSpacing(12)
        props_row.addWidget(QLabel(self.tr("Alignment:")))
        self._align_combo = QComboBox()
        self._align_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._align_combo.installEventFilter(_no_wheel())
        for label, data in (
            (self.tr("Left"), "left"),
            (self.tr("Center"), "center"),
            (self.tr("Right"), "right"),
        ):
            self._align_combo.addItem(label, data)
        idx = self._align_combo.findData(block.alignment or "center")
        self._align_combo.setCurrentIndex(max(0, idx))
        self._align_combo.currentIndexChanged.connect(on_changed)
        props_row.addWidget(self._align_combo)
        props_row.addStretch()
        root.addLayout(props_row)

        # Text field — only for STATIC_TEXT blocks
        self._text_edit: QLineEdit | None = None
        if block.block_type == BLOCK_STATIC_TEXT:
            self._text_edit = QLineEdit(block.value)
            self._text_edit.setPlaceholderText(
                self.tr("e.g. REPUBLIC OF SERBIA or [municipality]")
            )
            self._text_edit.setToolTip(
                self.tr(
                    "Placeholders replaced during generation:\n"
                    "  [municipality] → municipality name\n"
                    "  [election]     → election name"
                )
            )
            self._text_edit.editingFinished.connect(on_changed)
            root.addWidget(self._text_edit)

    def _apply_style(self, active: bool) -> None:
        border = "#2F5496" if active else "#AAAAAA"
        width  = "2px"     if active else "1px"
        self.setStyleSheet(
            f"QFrame#Card {{ background-color: {self._bg};"
            f" border: {width} solid {border}; border-radius: 4px; }}"
        )

    def set_active(self, active: bool) -> None:
        self._apply_style(active)

    def to_block(self) -> LegitimacijaBlock:
        value = self._text_edit.text().strip() if self._text_edit else ""
        try:
            row_h = max(1, int(self._row_edit.text()))
        except ValueError:
            row_h = 1
        return LegitimacijaBlock(
            block_type=self._block_type,
            value=value,
            col_span=self._col_combo.currentData() or 12,
            row_height=row_h,
            alignment=self._align_combo.currentData() or "center",
        )


class _LegitimacijaTab(QWidget):
    """Tab 0 of PosmatraciWorkspace — legitimacija layout builder.

    Left half: card-setup (plain QLineEdit mm inputs) + scrollable block
    editor. Right half: live _CardPreview that redraws on every change.
    """

    def __init__(self, state: AppState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._cards: list[_LegitimacijaBlockCard] = []
        self._active_card: _LegitimacijaBlockCard | None = None
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar with title + save button
        header = QWidget()
        header.setObjectName("TabHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(16, 8, 16, 8)
        lbl = QLabel(self.tr("Legitimacija design"))
        lbl.setObjectName("TitleLabel")
        header_row.addWidget(lbl)
        header_row.addStretch()
        self._btn_save = QPushButton(self.tr("Save"))
        self._btn_save.setObjectName("PrimaryButton")
        self._btn_save.clicked.connect(self._manual_save)
        header_row.addWidget(self._btn_save)
        self._save_label = QLabel("")
        self._save_label.setObjectName("MutedLabel")
        header_row.addWidget(self._save_label)
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        # ── Left: scrollable editor ───────────────────────────
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(scroll)

        editor = QWidget()
        editor_root = QVBoxLayout(editor)
        editor_root.setContentsMargins(16, 16, 8, 16)
        editor_root.setSpacing(14)
        scroll.setWidget(editor)

        # Card setup group — plain QLineEdit fields, no spinbox arrows
        setup_box = QGroupBox(self.tr("Legitimacija card settings"))
        setup_form = QFormLayout(setup_box)
        setup_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        setup_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        setup_form.setSpacing(8)

        def _mm_field(default: str, lo: float, hi: float) -> tuple[QLineEdit, QHBoxLayout]:
            ed = QLineEdit(default)
            ed.setValidator(QDoubleValidator(lo, hi, 1))
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(ed, stretch=1)
            row.addWidget(QLabel(self.tr("mm")))
            return ed, row

        self._card_w, w_row = _mm_field("90.0", 20.0, 400.0)
        self._card_w.setToolTip(self.tr("Legitimacija width in mm (e.g. 90.0)"))
        setup_form.addRow(self.tr("Card width:"), w_row)

        self._card_h, h_row = _mm_field("60.0", 20.0, 400.0)
        self._card_h.setToolTip(self.tr("Legitimacija height in mm (e.g. 60.0)"))
        setup_form.addRow(self.tr("Card height:"), h_row)

        self._gutter, g_row = _mm_field("5.0", 0.0, 50.0)
        self._gutter.setToolTip(self.tr("Gap between cards (e.g. 5.0)"))
        setup_form.addRow(self.tr("Gap (gutter):"), g_row)

        self._margin, m_row = _mm_field("10.0", 0.0, 50.0)
        self._margin.setToolTip(self.tr("Sheet margin on each side (e.g. 10.0)"))
        setup_form.addRow(self.tr("Sheet margin:"), m_row)

        self._paper_combo = QComboBox()
        self._paper_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._paper_combo.installEventFilter(_no_wheel())
        for ps in PAPER_SIZES:
            pw, ph = PAPER_SIZES[ps]
            self._paper_combo.addItem(f"{ps}  ({int(pw)}×{int(ph)} mm)", ps)
        setup_form.addRow(self.tr("Paper size:"), self._paper_combo)

        self._capacity_label = QLabel()
        self._capacity_label.setObjectName("MutedLabel")
        setup_form.addRow(self.tr("Capacity:"), self._capacity_label)

        editor_root.addWidget(setup_box)

        # Block list group
        blocks_box = QGroupBox(self.tr("Block layout on legitimacija"))
        blocks_vbox = QVBoxLayout(blocks_box)

        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch(1)

        self._blocks_scroll = QScrollArea()
        self._blocks_scroll.setWidgetResizable(True)
        self._blocks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._blocks_scroll.setMinimumHeight(320)
        self._blocks_scroll.setWidget(self._cards_container)
        blocks_vbox.addWidget(self._blocks_scroll)

        add_row = QHBoxLayout()
        self._block_type_combo = QComboBox()
        self._block_type_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._block_type_combo.installEventFilter(_no_wheel())
        for i, bt in enumerate(ALL_BLOCK_TYPES):
            self._block_type_combo.addItem(BLOCK_LABELS.get(bt, bt), bt)
            color = _BLOCK_PREVIEW_COLORS.get(bt)
            if color:
                self._block_type_combo.setItemData(i, QColor(color), Qt.ItemDataRole.BackgroundRole)
        add_row.addWidget(self._block_type_combo, stretch=1)
        btn_add = QPushButton(self.tr("+ Add block"))
        btn_add.clicked.connect(self._add_block)
        add_row.addWidget(btn_add)
        btn_reset = QPushButton(self.tr("Reset to default"))
        btn_reset.setToolTip(self.tr("Resets the layout to the standard template (Mionica 2024)"))
        btn_reset.clicked.connect(self._reset_layout)
        add_row.addWidget(btn_reset)
        blocks_vbox.addLayout(add_row)

        editor_root.addWidget(blocks_box)
        editor_root.addStretch()

        # ── Right: live preview ────────────────────────────────
        right_w = QWidget()
        right_vbox = QVBoxLayout(right_w)
        right_vbox.setContentsMargins(8, 16, 16, 16)
        right_vbox.setSpacing(8)

        preview_heading = QLabel(self.tr("Card preview"))
        preview_heading.setObjectName("HeadLabel")
        right_vbox.addWidget(preview_heading)

        self._preview = _CardPreview()
        right_vbox.addWidget(self._preview, stretch=1)
        splitter.addWidget(right_w)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 500])
        root.addWidget(splitter, stretch=1)

        # Wire setup signals — editingFinished avoids re-rendering while typing
        self._card_w.editingFinished.connect(self._on_setup_changed)
        self._card_h.editingFinished.connect(self._on_setup_changed)
        self._gutter.editingFinished.connect(self._on_setup_changed)
        self._margin.editingFinished.connect(self._on_setup_changed)
        self._paper_combo.currentIndexChanged.connect(self._on_setup_changed)

        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance()
        if isinstance(_app, QApplication):
            _app.focusChanged.connect(self._on_focus_changed)
        self.state.election_changed.connect(self._refresh_preview)
        self.state.oik_changed.connect(self._refresh_preview)

        self._load_from_state()

    def _read_mm(self, edit: QLineEdit, default: float) -> float:
        try:
            return max(1.0, float(edit.text().replace(",", ".")))
        except ValueError:
            return default

    def _load_from_state(self) -> None:
        self._loading = True
        try:
            cs = self.state.app_settings.posmatraci.card_setup
            self._card_w.setText(f"{cs.card_width_mm:.1f}")
            self._card_h.setText(f"{cs.card_height_mm:.1f}")
            self._gutter.setText(f"{cs.gutter_mm:.1f}")
            self._margin.setText(f"{cs.margin_mm:.1f}")
            idx = self._paper_combo.findData(cs.paper_size)
            self._paper_combo.setCurrentIndex(max(0, idx))
            self._update_capacity(cs)
            self._load_layout(self.state.app_settings.posmatraci.legitimacija_layout)
        finally:
            self._loading = False
        self._refresh_preview()

    def _update_capacity(self, cs: CardSetup) -> None:
        n = cs.cards_per_sheet()
        pw, ph = PAPER_SIZES.get(cs.paper_size, PAPER_SIZES["A4"])
        self._capacity_label.setText(
            self.tr("{n} card(s) per {paper} sheet ({w}×{h} mm)").format(
                n=n, paper=cs.paper_size, w=int(pw), h=int(ph)
            )
        )

    @log_timing("PosmatraciWorkspace._refresh_preview")
    def _refresh_preview(self) -> None:
        card_w = self._read_mm(self._card_w, 90.0)
        card_h = self._read_mm(self._card_h, 60.0)
        mun = self.state.oik.municipality
        chairman = self.state.oik.chairman
        election = _election_label(self.state)
        self._preview.update_preview(
            [c.to_block() for c in self._cards], card_w, card_h,
            municipality=mun.name,
            election=election,
            chairman_title=chairman.title,
            chairman_name=chairman.name,
        )

    def _load_layout(self, blocks: list[LegitimacijaBlock]) -> None:
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._cards.clear()
        for block in blocks:
            self._insert_card(block)

    def _set_active_card(self, card: _LegitimacijaBlockCard | None) -> None:
        if card is self._active_card:
            return
        if self._active_card is not None and self._active_card in self._cards:
            self._active_card.set_active(False)
        self._active_card = card
        if card is not None:
            card.set_active(True)

    def _on_focus_changed(self, _old, new) -> None:
        if new is None:
            return
        w = new
        while w is not None:
            if isinstance(w, _LegitimacijaBlockCard) and w in self._cards:
                self._set_active_card(w)
                return
            w = w.parent()

    def _insert_card(
        self,
        block: LegitimacijaBlock,
        after: "_LegitimacijaBlockCard | None" = None,
    ) -> _LegitimacijaBlockCard:
        card = _LegitimacijaBlockCard(
            block,
            on_remove=self._remove_card,
            on_move_up=self._move_card_up,
            on_move_down=self._move_card_down,
            on_changed=self._on_layout_changed,
        )
        if after is not None and after in self._cards:
            idx = self._cards.index(after)
            self._cards_layout.insertWidget(idx + 1, card)
            self._cards.insert(idx + 1, card)
        else:
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._cards.append(card)
        return card

    def _remove_card(self, card: _LegitimacijaBlockCard) -> None:
        if card is self._active_card:
            # Move active to the card above, or below, or None
            idx = self._cards.index(card)
            next_active = (
                self._cards[idx - 1] if idx > 0
                else self._cards[idx + 1] if idx + 1 < len(self._cards)
                else None
            )
            self._set_active_card(next_active)
        if card in self._cards:
            self._cards.remove(card)
        self._cards_layout.removeWidget(card)
        card.deleteLater()
        self._on_layout_changed()

    def _move_card_up(self, card: _LegitimacijaBlockCard) -> None:
        idx = self._cards.index(card) if card in self._cards else -1
        if idx <= 0:
            return
        self._cards.insert(idx - 1, self._cards.pop(idx))
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx - 1, card)
        self._on_layout_changed()

    def _move_card_down(self, card: _LegitimacijaBlockCard) -> None:
        idx = self._cards.index(card) if card in self._cards else -1
        if idx < 0 or idx >= len(self._cards) - 1:
            return
        self._cards.insert(idx + 1, self._cards.pop(idx))
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx + 1, card)
        self._on_layout_changed()

    def _add_block(self) -> None:
        bt = self._block_type_combo.currentData()
        if not bt:
            return
        card = self._insert_card(LegitimacijaBlock(block_type=bt), after=self._active_card)
        self._set_active_card(card)
        self._blocks_scroll.ensureWidgetVisible(card)
        self._on_layout_changed()

    def _reset_layout(self) -> None:
        self._load_layout(default_legitimacija_layout())
        self._on_layout_changed()

    def _collect_card_setup(self) -> CardSetup:
        return CardSetup(
            card_width_mm=self._read_mm(self._card_w, 90.0),
            card_height_mm=self._read_mm(self._card_h, 60.0),
            gutter_mm=self._read_mm(self._gutter, 5.0),
            paper_size=self._paper_combo.currentData() or "A4",
            margin_mm=self._read_mm(self._margin, 10.0),
        )

    def _on_setup_changed(self) -> None:
        if self._loading:
            return
        cs = self._collect_card_setup()
        self.state.app_settings.posmatraci.card_setup = cs
        self._update_capacity(cs)
        self._refresh_preview()
        self._save()

    def _on_layout_changed(self) -> None:
        if self._loading:
            return
        self.state.app_settings.posmatraci.legitimacija_layout = [
            c.to_block() for c in self._cards
        ]
        self._refresh_preview()
        self._save()

    def _save(self) -> None:
        try:
            self.state.save_app_settings()
        except OSError as e:
            log.warning("legitimacija settings save failed: %s", e)

    def _manual_save(self) -> None:
        self._save()
        self._save_label.setText(self.tr("Saved ✓"))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self._save_label.setText(""))


# ── Workspace ─────────────────────────────────────────────────────────


class PosmatraciWorkspace(QWidget):
    """Three-tab observer accreditation workspace.

    Replaces PlaceholderPage("Посматрачи") in main_window.py.
    Gated by the sidebar — only enabled when local elections are present.
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(False)

        self.tabs.addTab(_LegitimacijaTab(state), self.tr("0. ID cards"))
        self.tabs.addTab(_AkreditacijaTab(state), self.tr("1. Accreditation"))
        self.tabs.addTab(_DocumentiTab(state), self.tr("2. Documents"))

        root.addWidget(self.tabs)
