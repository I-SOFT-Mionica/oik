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
from biracki_odbor.gui.widgets.block_layout_editor import (
    BlockLayoutEditor, BlockPalette, no_wheel,
)
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
# The builder itself is gui/widgets/block_layout_editor.py (shared with
# envelopes); this supplies the observer-card blocks, card setup and
# persistence.

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


class _LegitimacijaTab(BlockLayoutEditor):
    """Tab 0 of PosmatraciWorkspace — legitimacija layout builder."""

    def __init__(self, state: AppState, parent=None) -> None:
        self.state = state
        self.TITLE = self.tr("Legitimacija design")
        self.BLOCKS_TITLE = self.tr("Block layout on legitimacija")
        self.PREVIEW_TITLE = self.tr("Card preview")
        super().__init__(parent)

        for ed in (self._card_w, self._card_h, self._gutter, self._margin):
            ed.editingFinished.connect(self._on_setup_changed)
        self._paper_combo.currentIndexChanged.connect(self._on_setup_changed)
        self.state.election_changed.connect(self._refresh_preview)
        self.state.oik_changed.connect(self._refresh_preview)
        self._load_from_state()

    # ── BlockLayoutEditor hooks ───────────────────────────────────
    def _palette(self) -> BlockPalette:
        def preview(blk: LegitimacijaBlock) -> str:
            chairman = self.state.oik.chairman
            return _block_preview_text(
                blk, self.state.oik.municipality.name, _election_label(self.state),
                chairman.title, chairman.name,
            )
        return BlockPalette(
            types=list(ALL_BLOCK_TYPES), labels=BLOCK_LABELS, colors=_BLOCK_PREVIEW_COLORS,
            preview_text=preview,
            static_hint=self.tr("e.g. REPUBLIC OF SERBIA or [municipality]"),
            static_tooltip=self.tr(
                "Placeholders replaced during generation:\n"
                "  [municipality] → municipality name\n"
                "  [election]     → election name"
            ),
        )

    def _page_size_mm(self) -> tuple[float, float]:
        return self._read_mm(self._card_w, 90.0), self._read_mm(self._card_h, 60.0)

    def _build_setup_box(self) -> QWidget:
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
        self._paper_combo.installEventFilter(no_wheel())
        for ps in PAPER_SIZES:
            pw, ph = PAPER_SIZES[ps]
            self._paper_combo.addItem(f"{ps}  ({int(pw)}×{int(ph)} mm)", ps)
        setup_form.addRow(self.tr("Paper size:"), self._paper_combo)

        self._capacity_label = QLabel()
        self._capacity_label.setObjectName("MutedLabel")
        setup_form.addRow(self.tr("Capacity:"), self._capacity_label)
        return setup_box

    def _stored_layout(self) -> list[LegitimacijaBlock]:
        return self.state.app_settings.posmatraci.legitimacija_layout

    def _store_layout(self, blocks: list[LegitimacijaBlock]) -> None:
        self.state.app_settings.posmatraci.legitimacija_layout = blocks

    def _default_layout(self) -> list[LegitimacijaBlock]:
        return default_legitimacija_layout()

    def _save(self) -> None:
        try:
            self.state.save_app_settings()
        except OSError as e:
            log.warning("legitimacija settings save failed: %s", e)

    # ── card setup ────────────────────────────────────────────────
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
            self._paper_combo.setCurrentIndex(max(0, self._paper_combo.findData(cs.paper_size)))
            self._update_capacity(cs)
            self._load_layout(self._stored_layout())
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
        super()._refresh_preview()

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
