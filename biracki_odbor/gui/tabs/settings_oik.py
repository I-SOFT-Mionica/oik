"""Поставке ОИК — rarely-changed constants owned by the commission.

V1 layout: four inner tabs inside the page so the form isn't a
single long scroll any more.
  - Опште: Општина + Председник + Пун назив комисије
  - Бирачка места: editable table + Excel import / export
  - Систем: desktop-shortcut + verbose-logging + open logs
  - Посматрачи: legitimacija block layout builder + cards-per-page

The allocation template (Stalni_sastav.xlsx) upload lives in
Изборна конфигурација → Tab 1 (inside Одлука РИК-а card).

`full_name` of each polling station is derived as
`name + " — " + municipality.name` on save. Lozinka is on the
Изборна tab.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCompleter, QComboBox, QDialog,
    QFileDialog, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from biracki_odbor.gui.widgets.spinbox import WheelSafeDoubleSpinBox, inset_spinbox_text
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

from biracki_odbor import app_paths
from biracki_odbor.config import opstine as opstine_mod
from biracki_odbor.config.commission import NACELNIK_ROLES, default_full_committee_name
from biracki_odbor.config.oik import (
    Chairman, DocumentFormat, Municipality, default_station_full_name,
)
from biracki_odbor.core.models import PollingStation
from biracki_odbor.core.template import build_bm_workbook, read_bm_sheet
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.searchable_table import (
    RowEditDialog, SearchableTable,
)
from biracki_odbor.installer.scaffold import create_desktop_shortcut


log = logging.getLogger(__name__)


_STANDARD_FULL_NAME_PREFIXES = (
    "Општинска изборна комисија у општини",
    "Градска изборна комисија",
    "Изборна комисија градске општине",
)

class OikSettingsTab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, stretch=1)

        # Centering wrap with a 1600 px max-width cap — fluid between
        # 720 px laptops and 1600 px desktops; ultrawides get side
        # whitespace instead of stretched cards. See the matching
        # rationale in settings_election.py.
        viewport_wrap = QWidget()
        hwrap = QHBoxLayout(viewport_wrap)
        hwrap.setContentsMargins(0, 0, 0, 0)
        hwrap.addStretch()
        container = QWidget()
        container.setMaximumWidth(1600)
        hwrap.addWidget(container, stretch=1)
        hwrap.addStretch()
        scroll.setWidget(viewport_wrap)

        root = QVBoxLayout(container)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(14)

        # No page title / hint inline — sidebar labels the page; tabs
        # below are the top element. Intro copy fires once via the
        # auto-hiding info banner — see settings_election.py for the
        # full rationale.
        self.banner = StatusBanner()
        self._first_open_note = self.tr(
            "OIK settings — these settings change rarely, usually once"
            " during initial setup or when the commission membership changes."
        )

        # ── Inner tabs ───────────────────────────────────────
        # Three logical sections split into tabs instead of one long
        # scroll. Switching tabs is purely visual — the same fields,
        # the same Save button, the same dirty-flag plumbing all stay
        # in this one widget. Per-tab QWidgets just host the existing
        # builders' QGroupBox outputs.
        self.inner_tabs = QTabWidget()
        self.inner_tabs.setDocumentMode(True)
        self.inner_tabs.setMovable(False)
        self.inner_tabs.setUsesScrollButtons(False)
        root.addWidget(self.inner_tabs, stretch=1)

        # Tab 1 — Опште: Општина + Председник (side-by-side) + Пун назив
        opste_page = QWidget()
        opste_layout = QVBoxLayout(opste_page)
        opste_layout.setContentsMargins(0, 14, 0, 0)
        opste_layout.setSpacing(14)

        mun_box = QGroupBox(self.tr("Municipality"))
        mun_layout = QFormLayout(mun_box)
        mun_layout.setLabelAlignment(Qt.AlignRight)
        # Strict picker, not free text: a plain name search is fragile at
        # national scale (a short municipality name can be a substring of
        # an unrelated one), so Назив is sourced from the bundled
        # config.opstine registry and only ever holds a real entry from
        # that list. self._last_valid_sifra tracks the currently-accepted
        # selection so a typed-but-unmatched edit can be reverted instead
        # of silently accepted (see _on_name_edit_finished).
        self.cb_name = QComboBox()
        self.cb_name.setEditable(True)
        self.cb_name.setInsertPolicy(QComboBox.NoInsert)
        registry = opstine_mod.load_registry()
        for entry in registry:
            self.cb_name.addItem(entry.name, entry.sifra)
        self.cb_name.setCurrentIndex(-1)
        completer = QCompleter([e.name for e in registry], self.cb_name)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.cb_name.setCompleter(completer)
        self._last_valid_sifra = ""
        self.lbl_sifra = QLabel("")
        self.lbl_sifra.setStyleSheet("color:#666;")
        self.ed_genitive = QLineEdit()
        self.ed_locative = QLineEdit()
        self.ed_website = QLineEdit()
        self.ed_website.setPlaceholderText(self.tr("e.g. ub.rs"))
        self.cb_vojvodina = ToggleSwitch(self.tr("Municipality is in AP Vojvodina"))
        mun_layout.addRow(self.tr("Name (Ub):"), self.cb_name)
        mun_layout.addRow(self.tr("Municipality code:"), self.lbl_sifra)
        mun_layout.addRow(self.tr("Genitive (Uba):"), self.ed_genitive)
        mun_layout.addRow(self.tr("Locative (Ubu):"), self.ed_locative)
        mun_layout.addRow(self.tr("Website:"), self.ed_website)
        mun_layout.addRow("", self.cb_vojvodina)

        ch_box = QGroupBox(self.tr("OIK President"))
        ch_layout = QFormLayout(ch_box)
        ch_layout.setLabelAlignment(Qt.AlignRight)
        self.ed_ch_title = QLineEdit()
        self.ed_ch_name = QLineEdit()
        ch_layout.addRow(self.tr("Title:"), self.ed_ch_title)
        ch_layout.addRow(self.tr("Name:"), self.ed_ch_name)

        nacelnik_box = QGroupBox(self.tr("Chief (начелник)"))
        nacelnik_layout = QFormLayout(nacelnik_box)
        nacelnik_layout.setLabelAlignment(Qt.AlignRight)
        self.ed_nacelnik_full_name = QLineEdit()
        self.ed_nacelnik_full_name.setPlaceholderText(self.tr("e.g. начелника Општинске управе"))
        self.ed_nacelnik_full_name.setToolTip(self.tr(
            "Used in decision text (Решења/Измене) when RIK didn't receive a"
            " proposal for a slot from any party. Pre-filled with the"
            " standard legal title — only change it if your municipality"
            " genuinely uses different wording. The municipality name above"
            " is appended automatically, so decisions read e.g. '…начелника"
            " Општинске управе општине Уб'. Doesn't change between election"
            " cycles, so it lives here rather than on the Election Settings"
            " tab."
        ))
        nacelnik_layout.addRow(self.tr("Role (for decisions):"), self.ed_nacelnik_full_name)

        header_row = QHBoxLayout()
        header_row.setSpacing(14)
        header_row.addWidget(mun_box, stretch=1)
        header_row.addWidget(ch_box, stretch=1)
        opste_layout.addLayout(header_row)
        opste_layout.addWidget(nacelnik_box)

        full_box = QGroupBox(self.tr("Full commission name"))
        full_layout = QVBoxLayout(full_box)
        self.ed_full = QLineEdit()
        self.ed_full.setPlaceholderText(
            self.tr("e.g. MUNICIPAL ELECTION COMMISSION OF MUNICIPALITY UB")
        )
        full_layout.addWidget(self.ed_full)
        opste_layout.addWidget(full_box)
        opste_layout.addStretch(1)
        self.inner_tabs.addTab(opste_page, self.tr("1. General"))

        # Tab 2 — Бирачка места
        bm_page = QWidget()
        bm_page_layout = QVBoxLayout(bm_page)
        bm_page_layout.setContentsMargins(0, 14, 0, 0)
        bm_box = QGroupBox(self.tr("Polling stations"))
        bm_layout = QVBoxLayout(bm_box)

        # Parent-owned data backing the SearchableTable. List of dicts
        # with keys: bm_number (str — kept as string for display, parsed
        # at save time), name, address, full_name.
        #
        # full_name is a real, independently editable field again — not
        # a formula re-applied at every save. Two field reports
        # (Мионица, Уб) confirmed that auto-deriving it from Name +
        # Municipality (then later Name + Address) with no visible/
        # editable field left every BM stuck with whatever the formula
        # produced, no way to override a wrong result. _collect_
        # polling_stations() below only falls back to the Name+Address
        # default when this field is left blank.
        self._bm_rows: list[dict[str, str]] = []

        self.bm_table = SearchableTable(
            [self.tr("No."), self.tr("Name"), self.tr("Address"), self.tr("Full name")],
            placeholder=self.tr("Type number, name, address or full name…"),
        )
        h = self.bm_table.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(False)
        h.resizeSection(0, 70)
        h.resizeSection(1, 220)
        h.resizeSection(2, 220)
        h.resizeSection(3, 260)
        self.bm_table.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.bm_table.table.setMinimumHeight(280)
        self.bm_table.table.verticalHeader().setDefaultSectionSize(34)
        self.bm_table.row_activated.connect(self._edit_bm_row)
        bm_layout.addWidget(self.bm_table)

        bm_btns = QHBoxLayout()
        self.btn_add_bm = QPushButton(self.tr("Add polling station"))
        self.btn_rm_bm = QPushButton(self.tr("Remove selected"))
        self.btn_rm_bm.setObjectName("DangerButton")
        self.btn_import_bm = QPushButton(self.tr("Import"))
        self.btn_import_bm.setToolTip(self.tr(
            "Imports the polling station list from a standalone Excel file"
            " (e.g. bm.xlsx) — sheet with headers No., Name, Address."
        ))
        self.btn_export_bm = QPushButton(self.tr("Export"))
        self.btn_export_bm.setToolTip(self.tr(
            "Exports the current polling station list to a standalone Excel file"
            " that you can edit or share with the municipality."
        ))
        bm_btns.addWidget(self.btn_add_bm)
        bm_btns.addWidget(self.btn_rm_bm)
        bm_btns.addWidget(self.btn_import_bm)
        bm_btns.addWidget(self.btn_export_bm)
        bm_btns.addStretch()
        bm_layout.addLayout(bm_btns)

        full_name_hint = QLabel(self.tr(
            "Full name is its own editable field — leave it blank and it"
            " defaults to \"Name, Address\" on save; type your own text"
            " to override that default for a specific station."
        ))
        full_name_hint.setObjectName("MutedLabel")
        full_name_hint.setWordWrap(True)
        bm_layout.addWidget(full_name_hint)

        bm_page_layout.addWidget(bm_box)
        bm_page_layout.addStretch(1)
        self.inner_tabs.addTab(bm_page, self.tr("2. Polling stations"))

        self.btn_add_bm.clicked.connect(self._add_bm_row)
        self.btn_rm_bm.clicked.connect(self._remove_selected_bm)
        self.btn_import_bm.clicked.connect(self._import_bm_from_excel)
        self.btn_export_bm.clicked.connect(self._export_bm_to_excel)

        # Tab 3 — Систем. Two-column grouping: left = File explorer +
        # Debugging, right = Localization + Email — replaces one long
        # scrolling list of separator-divided fields with focused cards.
        sys_page = QWidget()
        sys_page_layout = QVBoxLayout(sys_page)
        sys_page_layout.setContentsMargins(0, 14, 0, 0)

        columns_row = QHBoxLayout()
        columns_row.setSpacing(16)
        left_col = QVBoxLayout()
        left_col.setSpacing(16)
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        # ── Left: File explorer ──────────────────────────────────
        explorer_box = QGroupBox(self.tr("File explorer"))
        explorer_layout = QVBoxLayout(explorer_box)

        files_dir_row = QHBoxLayout()
        files_dir_row.addWidget(QLabel(self.tr("Default export/import folder:")))
        self.ed_files_dir = QLineEdit()
        self.ed_files_dir.setReadOnly(True)
        files_dir_row.addWidget(self.ed_files_dir, stretch=1)
        self.btn_browse_files_dir = QPushButton(self.tr("Browse…"))
        self.btn_browse_files_dir.clicked.connect(self._on_browse_files_dir)
        files_dir_row.addWidget(self.btn_browse_files_dir)
        explorer_layout.addLayout(files_dir_row)
        files_dir_hint = QLabel(self.tr(
            "Where export/import dialogs (parliamentary groups, lists,"
            " allocation matrix, observers, polling stations, reports, PDF"
            " converter) open by default. Purpose subfolders (Групе, Листе,"
            " Расподела…) are created automatically underneath it."
            " Default: Documents."
        ))
        files_dir_hint.setObjectName("MutedLabel")
        files_dir_hint.setWordWrap(True)
        explorer_layout.addWidget(files_dir_hint)

        shortcut_row = QHBoxLayout()
        self.btn_shortcut = QPushButton(self.tr("Create desktop shortcut"))
        self.btn_shortcut.clicked.connect(self._create_shortcut)
        shortcut_row.addWidget(self.btn_shortcut)
        shortcut_row.addStretch()
        explorer_layout.addLayout(shortcut_row)
        self.lbl_shortcut_status = QLabel("")
        self.lbl_shortcut_status.setObjectName("MutedLabel")
        self.lbl_shortcut_status.setWordWrap(True)
        explorer_layout.addWidget(self.lbl_shortcut_status)

        folder_shortcut_row = QHBoxLayout()
        self.btn_folder_shortcut = QPushButton(self.tr("Create desktop shortcut for default folder"))
        self.btn_folder_shortcut.clicked.connect(self._create_folder_shortcut)
        folder_shortcut_row.addWidget(self.btn_folder_shortcut)
        folder_shortcut_row.addStretch()
        explorer_layout.addLayout(folder_shortcut_row)
        self.lbl_folder_shortcut_status = QLabel("")
        self.lbl_folder_shortcut_status.setObjectName("MutedLabel")
        self.lbl_folder_shortcut_status.setWordWrap(True)
        explorer_layout.addWidget(self.lbl_folder_shortcut_status)

        left_col.addWidget(explorer_box)

        # ── Left: Debugging ──────────────────────────────────────
        debug_box = QGroupBox(self.tr("Debugging"))
        debug_layout = QVBoxLayout(debug_box)

        self.cb_debug = ToggleSwitch(self.tr("Verbose logging (for troubleshooting)"))
        self.cb_debug.toggled.connect(self._on_debug_toggled)
        debug_layout.addWidget(self.cb_debug)
        log_hint = QLabel(
            self.tr("Log file: {log_path}\nLogging level change takes effect on next launch.").format(
                log_path=app_paths.log_dir() / "app.log"
            )
        )
        log_hint.setObjectName("MutedLabel")
        log_hint.setWordWrap(True)
        debug_layout.addWidget(log_hint)
        log_btn_row = QHBoxLayout()
        self.btn_open_logs = QPushButton(self.tr("Open log folder"))
        self.btn_open_logs.clicked.connect(self._open_logs)
        log_btn_row.addWidget(self.btn_open_logs)
        log_btn_row.addStretch()
        debug_layout.addLayout(log_btn_row)

        stall_row = QHBoxLayout()
        stall_row.addWidget(QLabel(self.tr("Background task timeout (seconds):")))
        self.sb_stall_timeout = QSpinBox()
        self.sb_stall_timeout.setRange(0, 3600)
        inset_spinbox_text(self.sb_stall_timeout)
        self.sb_stall_timeout.setSpecialValueText(self.tr("Off"))
        self.sb_stall_timeout.setToolTip(self.tr(
            "If a background task (e.g. reading Outlook/Thunderbird inbox,"
            " generating documents, downloading an update) reports no"
            " progress for this long, it is abandoned and reported as an"
            " error instead of leaving the progress bar spinning forever."
            " 0 disables the timeout."
        ))
        self.sb_stall_timeout.valueChanged.connect(self._on_stall_timeout_changed)
        stall_row.addWidget(self.sb_stall_timeout)
        stall_row.addStretch()
        debug_layout.addLayout(stall_row)
        stall_hint = QLabel(self.tr("Default: 180 seconds."))
        stall_hint.setObjectName("MutedLabel")
        stall_hint.setWordWrap(True)
        debug_layout.addWidget(stall_hint)

        self.cb_tab_gating = ToggleSwitch(self.tr("Tab gating"))
        self.cb_tab_gating.toggled.connect(self._on_tab_gating_toggled)
        debug_layout.addWidget(self.cb_tab_gating)
        gating_hint = QLabel(
            self.tr("Off: all workflow tabs are always accessible regardless of workflow progress.")
        )
        gating_hint.setObjectName("MutedLabel")
        gating_hint.setWordWrap(True)
        debug_layout.addWidget(gating_hint)

        left_col.addWidget(debug_box)

        # ── Left: Maintenance (hidden unless a one-off action is pending) ──
        # See core/maintenance.py: a code change (e.g. a data migration)
        # flags an action via AppSettings.pending_maintenance_action; this
        # box only appears while one is set, and disappears again (here and
        # on next launch) once the operator runs it.
        self.maintenance_box = QGroupBox(self.tr("Maintenance"))
        maintenance_layout = QVBoxLayout(self.maintenance_box)
        self.lbl_maintenance_desc = QLabel("")
        self.lbl_maintenance_desc.setObjectName("MutedLabel")
        self.lbl_maintenance_desc.setWordWrap(True)
        maintenance_layout.addWidget(self.lbl_maintenance_desc)
        maintenance_btn_row = QHBoxLayout()
        self.btn_run_maintenance = QPushButton("")
        self.btn_run_maintenance.clicked.connect(self._on_run_maintenance_action)
        maintenance_btn_row.addWidget(self.btn_run_maintenance)
        maintenance_btn_row.addStretch()
        maintenance_layout.addLayout(maintenance_btn_row)
        self.maintenance_box.setVisible(False)
        left_col.addWidget(self.maintenance_box)

        left_col.addStretch(1)

        # ── Right: Localization ──────────────────────────────────
        lang_box = QGroupBox(self.tr("Localization"))
        lang_layout = QVBoxLayout(lang_box)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(self.tr("Language:")))
        self.cb_language = QComboBox()
        self.cb_language.addItem("Српски (ћирилица)", "sr")
        self.cb_language.addItem("English", "en")
        self.cb_language.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self.cb_language, stretch=1)
        lang_layout.addLayout(lang_row)
        self.lbl_lang_hint = QLabel(self.tr("Change takes effect on next launch."))
        self.lbl_lang_hint.setObjectName("MutedLabel")
        self.lbl_lang_hint.setVisible(False)
        lang_layout.addWidget(self.lbl_lang_hint)

        right_col.addWidget(lang_box)

        # ── Right: Email ─────────────────────────────────────────
        email_box = QGroupBox(self.tr("Email"))
        email_layout = QVBoxLayout(email_box)

        # E-mail client preference. The combobox lists Auto + every
        # client we detect on this machine; pinning to a missing one
        # is allowed (the dispatcher falls back to whatever IS
        # available at send time + logs a warning), so the operator
        # can configure on a laptop before the target machine has the
        # client installed.
        email_row = QHBoxLayout()
        email_row.addWidget(QLabel(self.tr("Mail client:")))
        self.cb_email_client = QComboBox()
        from biracki_odbor.integrations.email_client import (
            EmailClient as _EC, label as _ec_label,
        )
        for client in (_EC.AUTO, _EC.OUTLOOK, _EC.THUNDERBIRD):
            self.cb_email_client.addItem(_ec_label(client), client.value)
        self.cb_email_client.currentIndexChanged.connect(self._on_email_client_changed)
        email_row.addWidget(self.cb_email_client, stretch=1)
        email_layout.addLayout(email_row)
        self.lbl_email_status = QLabel("")
        self.lbl_email_status.setObjectName("MutedLabel")
        self.lbl_email_status.setWordWrap(True)
        email_layout.addWidget(self.lbl_email_status)

        oik_email_row = QHBoxLayout()
        oik_email_row.addWidget(QLabel(self.tr("OIK email:")))
        self.ed_oik_email = QLineEdit()
        self.ed_oik_email.setPlaceholderText(self.tr("e.g. oik@mionica.rs"))
        self.ed_oik_email.setToolTip(self.tr(
            "Address from which the OIK sends files to parties and to which\n"
            "received applications arrive. When set, email import reads\n"
            "only that account's inbox (faster with multiple accounts)."
        ))
        self.ed_oik_email.editingFinished.connect(self._on_oik_email_changed)
        oik_email_row.addWidget(self.ed_oik_email, stretch=1)
        email_layout.addLayout(oik_email_row)

        nacelnik_email_row = QHBoxLayout()
        nacelnik_email_row.addWidget(QLabel(self.tr("Chief's email:")))
        self.ed_nacelnik_email = QLineEdit()
        self.ed_nacelnik_email.setPlaceholderText(self.tr("e.g. nacelnik@ub.rs"))
        self.ed_nacelnik_email.setToolTip(self.tr(
            "Address used by the Корекције \"send to chief\" flow when"
            " requesting appointments for unfilled slots. Can also be set"
            " there on first send — this field just makes it visible and"
            " editable up front."
        ))
        self.ed_nacelnik_email.editingFinished.connect(self._on_nacelnik_email_changed)
        nacelnik_email_row.addWidget(self.ed_nacelnik_email, stretch=1)
        email_layout.addLayout(nacelnik_email_row)

        right_col.addWidget(email_box)

        # ── Right: Document format ──────────────────────────────
        fmt_box = QGroupBox(self.tr("Document format"))
        fmt_layout = QFormLayout(fmt_box)

        self.sb_header_distance = WheelSafeDoubleSpinBox()
        self.sb_header_distance.setRange(0.0, 5.0)
        self.sb_header_distance.setSingleStep(0.1)
        self.sb_header_distance.setDecimals(1)
        self.sb_header_distance.setSuffix(" cm")
        self.sb_header_distance.valueChanged.connect(self._mark_dirty)
        fmt_layout.addRow(self.tr("Header distance:"), self.sb_header_distance)

        self.sb_footer_distance = WheelSafeDoubleSpinBox()
        self.sb_footer_distance.setRange(0.0, 5.0)
        self.sb_footer_distance.setSingleStep(0.1)
        self.sb_footer_distance.setDecimals(1)
        self.sb_footer_distance.setSuffix(" cm")
        self.sb_footer_distance.valueChanged.connect(self._mark_dirty)
        fmt_layout.addRow(self.tr("Footer distance:"), self.sb_footer_distance)

        # Line spacing and title-block/body-paragraph spacing moved to
        # the generation screens themselves (Phase 3, Измене) — the
        # operator wants to shrink spacing right where they're about to
        # generate and can see the page count, not hunt through here.

        right_col.addWidget(fmt_box)
        right_col.addStretch(1)

        columns_row.addLayout(left_col, stretch=1)
        columns_row.addLayout(right_col, stretch=1)
        sys_page_layout.addLayout(columns_row)
        sys_page_layout.addStretch(1)
        self.inner_tabs.addTab(sys_page, self.tr("3. System"))

        # Banner above, fixed-height dock below (72 px, matched to sidebar's
        # О апликацији item height) — see settings_election.py for the rationale.
        outer.addWidget(self.banner)
        dock = QFrame()
        dock.setObjectName("StickyDock")
        dock.setFixedHeight(72)
        dock_h = QHBoxLayout(dock)
        # See settings_election.py's StickyDock for the rationale — 10 not
        # 14 so the button's natural height (padding+border+Cyrillic line
        # height, ~44px at BODY_PT=14) has headroom within the fixed 72px
        # instead of clipping descenders on ц/р/д.
        dock_h.setContentsMargins(16, 10, 16, 10)
        dock_h.setSpacing(10)
        dock_h.addStretch()
        self.btn_save = QPushButton(self.tr("Save settings"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._save)
        dock_h.addWidget(self.btn_save)
        outer.addWidget(dock)

        # Dirty-flag wiring. _loading suppresses dirty during programmatic
        # repopulation; user edits flip self.dirty True until a save/revert.
        # See main_window's tab-change interception for how this is used.
        self.dirty = False
        self._loading = False
        self._wire_dirty_signals()
        self._load_from_state()
        # Reload when something OTHER than this tab's own Save button
        # changes OIK data — the onboarding wizard and backup-restore both
        # mutate state.oik directly and call save_oik(), but this tab (built
        # once at startup, unlike phase1/2/3 etc.) never re-read state
        # afterwards, so a wizard-entered chairman name / BM list silently
        # never appeared here. Skip if the operator has unsaved edits in
        # progress here so we don't clobber their own in-flight changes.
        state.oik_changed.connect(self._on_oik_changed_externally)
        # First-open intro notice; auto-hides after 5 s.
        self.banner.show_info(self._first_open_note)

    def _on_oik_changed_externally(self) -> None:
        if not self.dirty:
            self._load_from_state()

    # ── Dirty-flag plumbing ────────────────────────────────

    def _mark_dirty(self, *_args, **_kwargs) -> None:
        if not self._loading:
            self.dirty = True

    def _wire_dirty_signals(self) -> None:
        for ed in (
            self.ed_genitive, self.ed_locative, self.ed_full,
            self.ed_ch_title, self.ed_ch_name, self.ed_nacelnik_full_name,
        ):
            ed.textChanged.connect(self._mark_dirty)
        # cb_name (municipality picker): activated fires when the operator
        # picks an item from the dropdown/completer popup; editingFinished
        # (on the internal line edit) fires when they type-then-blur —
        # only the latter can produce text that isn't a real registry
        # entry, so it goes through the same revert-if-unmatched path.
        self.cb_name.activated.connect(self._on_name_activated)
        self.cb_name.lineEdit().editingFinished.connect(self._on_name_edit_finished)
        # bm_table is now a SearchableTable (read-only cells + popup
        # edit dialog). Dirty is set directly in _add/_edit/_remove/
        # _import handlers — no per-cell signal to wire here.
        self.cb_debug.toggled.connect(self._mark_dirty)
        self.cb_vojvodina.toggled.connect(self._mark_dirty)

    def _set_municipality_selection(self, sifra: str) -> None:
        """Programmatically select `sifra` (or clear, if empty/unknown)
        without re-triggering dirty tracking — used by both the picker's
        own handlers and `_load_from_state`."""
        entry = opstine_mod.find_by_sifra(sifra) if sifra else None
        was_loading = self._loading
        self._loading = True
        try:
            if entry is not None:
                self.cb_name.setCurrentIndex(self.cb_name.findData(entry.sifra))
                self.lbl_sifra.setText(entry.sifra)
                self._last_valid_sifra = entry.sifra
            else:
                self.cb_name.setCurrentIndex(-1)
                self.cb_name.lineEdit().setText("")
                self.lbl_sifra.setText("")
                self._last_valid_sifra = ""
        finally:
            self._loading = was_loading

    def _autofill_declension(self) -> None:
        """Suggest genitive/locative forms for the just-picked municipality
        — same rule-based guess (`config.declension`) the first-run Setup
        wizard already offers on a name change (`gui/dialogs/setup_wizard.
        py`), so switching municipality here doesn't leave the previous
        municipality's declined forms behind. The fields stay plain
        editable QLineEdits — this is a starting guess, not a locked
        derived value; the algorithm can be wrong for irregular names,
        same reasoning the wizard's own version already applies."""
        from biracki_odbor.config.declension import place_to_genitive, place_to_locative
        entry = opstine_mod.find_by_sifra(self._last_valid_sifra)
        nom = entry.document_name if entry else self.cb_name.currentText().strip()
        if not nom:
            return
        gen = place_to_genitive(nom)
        self.ed_genitive.setText(gen)
        self.ed_locative.setText((entry.doc_locative if entry else "") or place_to_locative(nom))
        if entry is None:
            return
        # Commission name and chief's title follow the unit type unless
        # the operator already wrote something non-standard.
        full = self.ed_full.text().strip()
        if not full or full.startswith(_STANDARD_FULL_NAME_PREFIXES):
            self.ed_full.setText(default_full_committee_name(entry.vrsta, nom, gen))
        if self.ed_nacelnik_full_name.text().strip() in ("", *NACELNIK_ROLES.values()):
            self.ed_nacelnik_full_name.setText(NACELNIK_ROLES[entry.vrsta])

    def _on_name_activated(self, index: int) -> None:
        sifra = self.cb_name.itemData(index) or ""
        changed = sifra != self._last_valid_sifra
        self._set_municipality_selection(sifra)
        if changed:
            self._autofill_declension()
            self._sync_vojvodina(sifra)
        self._mark_dirty()

    def _sync_vojvodina(self, sifra: str) -> None:
        entry = opstine_mod.find_by_sifra(sifra)
        if entry is not None:
            self.cb_vojvodina.setChecked(entry.is_vojvodina)

    def _on_name_edit_finished(self) -> None:
        if self._loading:
            return
        typed = self.cb_name.currentText().strip()
        entry = opstine_mod.find_by_name(typed)
        if entry is not None:
            if entry.sifra != self._last_valid_sifra:
                self._set_municipality_selection(entry.sifra)
                self._autofill_declension()
                self._sync_vojvodina(entry.sifra)
                self._mark_dirty()
            return
        # Typed text doesn't match any registry entry — revert to the
        # last accepted selection rather than silently keeping free text
        # (the whole point of this picker is that Назив can never again
        # be an unvalidated string).
        self._set_municipality_selection(self._last_valid_sifra)

    def save(self) -> bool:
        """Public entry point used by main_window's unsaved-changes prompt.

        Returns True iff the save succeeded; on failure we leave dirty=True
        so the prompt can be retried.
        """
        try:
            self._save()
        except Exception:  # noqa: BLE001
            return False
        self.dirty = False
        return True

    def revert(self) -> None:
        """Discard widget edits and reload from on-disk state."""
        self._load_from_state()
        self.dirty = False

    # ── State sync ─────────────────────────────────────────

    def _load_from_state(self) -> None:
        # Guard against widget signals flipping dirty=True during a
        # programmatic refill.
        self._loading = True
        try:
            oik = self.state.oik
            sifra = oik.municipality.sifra_opstine
            if not sifra and oik.municipality.name:
                # Migration path for configs saved before this field
                # existed: try to resolve the old free-text name against
                # the registry so upgrading doesn't blank out an already-
                # configured municipality. Exact match only (case/
                # whitespace normalized) — deliberately not a fuzzy or
                # substring match, since that's exactly the risk this
                # picker exists to remove. If it doesn't resolve, the
                # picker starts blank and the operator re-picks once.
                matched = opstine_mod.find_by_name(oik.municipality.name.strip())
                sifra = matched.sifra if matched else ""
            self._set_municipality_selection(sifra)
            self.ed_genitive.setText(oik.municipality.name_genitive)
            self.ed_locative.setText(oik.municipality.name_locative)
            self.ed_website.setText(oik.municipality.website)
            self.ed_full.setText(oik.municipality.full_committee_name)
            self.cb_vojvodina.setChecked(oik.municipality.is_vojvodina)
            self.ed_ch_title.setText(oik.chairman.title)
            self.ed_ch_name.setText(oik.chairman.name)
            self.ed_nacelnik_full_name.setText(oik.nacelnik_full_name)
            self.sb_header_distance.setValue(oik.document_format.header_distance_cm)
            self.sb_footer_distance.setValue(oik.document_format.footer_distance_cm)
            self._bm_rows = []
            for ps in oik.polling_stations:
                self._append_bm_row(ps)
            self._refresh_bm_view()
            # Template upload is in Изборна конфигурација Tab 1.
            # Debug toggle is ours.
            self.cb_debug.blockSignals(True)
            self.cb_debug.setChecked(self.state.app_settings.debug_logging)
            self.cb_debug.blockSignals(False)
            # Email-client preference + availability hint.
            self._reload_email_client_field()
            # OIK email address.
            self.ed_oik_email.blockSignals(True)
            self.ed_oik_email.setText(self.state.app_settings.oik_email)
            self.ed_oik_email.blockSignals(False)
            self.ed_nacelnik_email.blockSignals(True)
            self.ed_nacelnik_email.setText(self.state.app_settings.nacelnik_email)
            self.ed_nacelnik_email.blockSignals(False)
            # Language selection.
            self.cb_language.blockSignals(True)
            idx = self.cb_language.findData(self.state.app_settings.ui_language)
            self.cb_language.setCurrentIndex(max(0, idx))
            self.cb_language.blockSignals(False)
            self.lbl_lang_hint.setVisible(False)
            # Tab gating toggle.
            self.cb_tab_gating.blockSignals(True)
            self.cb_tab_gating.setChecked(not self.state.app_settings.disable_tab_gating)
            self.cb_tab_gating.blockSignals(False)
            # Background-task stall timeout.
            self.sb_stall_timeout.blockSignals(True)
            self.sb_stall_timeout.setValue(self.state.app_settings.worker_stall_timeout_seconds)
            self.sb_stall_timeout.blockSignals(False)
            # Default export/import folder (read-only field, auto-saves on Browse).
            self.ed_files_dir.setText(
                self.state.app_settings.default_files_dir or str(Path.home() / "Documents")
            )
            self._refresh_maintenance_box()
        finally:
            self._loading = False
            self.dirty = False

    def _reload_email_client_field(self) -> None:
        """Sync the email-client combobox to AppSettings + refresh hint."""
        from biracki_odbor.integrations import email_client as ec_mod
        pref = self.state.app_settings.email_client
        self.cb_email_client.blockSignals(True)
        try:
            idx = self.cb_email_client.findData(pref)
            if idx < 0:
                idx = self.cb_email_client.findData("auto")
            self.cb_email_client.setCurrentIndex(max(0, idx))
        finally:
            self.cb_email_client.blockSignals(False)
        # Status hint summarises what's actually detected — operator
        # learns whether their pinned choice will resolve as expected.
        available = ec_mod.available_clients()
        if not available:
            self.lbl_email_status.setText(self.tr(
                "No email client detected on this computer."
                " Send buttons will be hidden."
            ))
        else:
            names = ", ".join(ec_mod.label(c) for c in available)
            self.lbl_email_status.setText(
                self.tr("Detected clients: {names}").format(names=names)
            )

    def _refresh_bm_view(self) -> None:
        """Push `self._bm_rows` into the SearchableTable view."""
        self.bm_table.set_rows([
            (r["bm_number"], r["name"], r["address"], r.get("full_name", ""))
            for r in self._bm_rows
        ])

    def _append_bm_row(self, ps: PollingStation) -> None:
        """Append a record to the parent-owned list. Does NOT refresh
        the view — call _refresh_bm_view() after a batch of appends."""
        next_num = ps.bm_number or (len(self._bm_rows) + 1)
        self._bm_rows.append({
            "bm_number": str(next_num),
            "name": ps.name,
            "address": ps.address,
            # Show whatever's actually stored — including an old,
            # wrong auto-generated value, which the operator can now
            # see and fix (that visibility was the whole point). Only
            # a station with no full_name at all gets today's default.
            "full_name": ps.full_name or default_station_full_name(ps.name, ps.address),
        })

    def _add_bm_row(self) -> None:
        """+ Add polling station — opens an empty edit dialog."""
        next_num = len(self._bm_rows) + 1
        dlg = RowEditDialog(
            self.tr("New polling station"),
            [
                (self.tr("No.:"), "bm_number", str(next_num)),
                (self.tr("Name:"), "name", ""),
                (self.tr("Address:"), "address", ""),
                (self.tr("Full name:"), "full_name", ""),
            ],
            parent=self,
            placeholders={
                "name": self.tr("e.g. PRIMARY SCHOOL"),
                "full_name": self.tr("Leave blank for Name, Address"),
            },
            wrap_keys={"name", "address", "full_name"},
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        self._bm_rows.append({
            "bm_number": v["bm_number"] or str(next_num),
            "name": v["name"],
            "address": v["address"],
            "full_name": v["full_name"],
        })
        self._refresh_bm_view()
        self._mark_dirty()

    def _edit_bm_row(self, idx: int) -> None:
        """Open the edit dialog for the BM at `idx`. Called by the
        SearchableTable's row_activated signal (double-click)."""
        if not (0 <= idx < len(self._bm_rows)):
            return
        cur = self._bm_rows[idx]
        dlg = RowEditDialog(
            self.tr("Edit polling station no. {bm_number}").format(bm_number=cur["bm_number"]),
            [
                (self.tr("No.:"), "bm_number", cur["bm_number"]),
                (self.tr("Name:"), "name", cur["name"]),
                (self.tr("Address:"), "address", cur["address"]),
                (self.tr("Full name:"), "full_name", cur.get("full_name", "")),
            ],
            parent=self,
            placeholders={"full_name": self.tr("Leave blank for Name, Address")},
            wrap_keys={"name", "address", "full_name"},
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        self._bm_rows[idx] = {
            "bm_number": v["bm_number"] or cur["bm_number"],
            "name": v["name"],
            "address": v["address"],
            "full_name": v["full_name"],
        }
        self._refresh_bm_view()
        self._mark_dirty()

    def _remove_selected_bm(self) -> None:
        idx = self.bm_table.selected_original_index()
        if idx is None:
            return
        if not (0 <= idx < len(self._bm_rows)):
            return
        del self._bm_rows[idx]
        self._refresh_bm_view()
        self._mark_dirty()

    # ── BM Excel import/export ─────────────────────────────

    def _import_bm_from_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select bm.xlsx"),
            str(self.state.files_dir("Бирачка места")),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        # Same safety pipeline as popunjeni / template imports — picked
        # file goes through size / zip / macros / OLE / externals checks
        # before we touch it with openpyxl.
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(Path(path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=Path(path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return
        stations, errors = read_bm_sheet(path)
        if errors:
            self.banner.show_error("\n".join(errors))
            return
        if self._bm_rows:
            reply = QMessageBox.question(
                self, self.tr("Replace existing entries"),
                self.tr(
                    "The table already has {n_existing} polling stations."
                    " {n_new} will be loaded from Excel.\n\n"
                    "Replace existing entries with the new ones?"
                ).format(n_existing=len(self._bm_rows), n_new=len(stations)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._bm_rows = []
        for ps in stations:
            self._append_bm_row(ps)
        self._refresh_bm_view()
        self._mark_dirty()
        self.banner.show_ok(
            self.tr("Loaded {n} polling stations. Click 'Save settings' to persist.").format(
                n=len(stations)
            )
        )

    def _export_bm_to_excel(self) -> None:
        stations = self._collect_polling_stations()
        if not stations:
            self.banner.show_warn(self.tr("No polling stations to export."))
            return
        default = str(self.state.files_dir("Бирачка места") / "bm.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save bm.xlsx"), default, self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        try:
            build_bm_workbook(stations, path)
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        self.banner.show_ok(
            self.tr("Exported {n} polling stations to {path}").format(n=len(stations), path=path)
        )

    # ── Систем ─────────────────────────────────────────────

    def _create_shortcut(self) -> None:
        # Frozen .exe: sys.executable IS the app's main exe. Dev mode:
        # sys.executable is python — shortcut would be useless; check for
        # an installed exe sibling to home() and use that instead.
        if getattr(sys, "frozen", False):
            target = Path(sys.executable)
        else:
            candidate = app_paths.home() / "OIK.exe"
            if candidate.exists():
                target = candidate
            else:
                self.lbl_shortcut_status.setText(
                    self.tr("Shortcut requires an installed version of the application.")
                )
                log.info("shortcut request denied: not frozen and no install-dir exe")
                return
        lnk = create_desktop_shortcut(target)
        if lnk is not None:
            self.lbl_shortcut_status.setText(
                self.tr("Shortcut created: {lnk}").format(lnk=lnk)
            )
        else:
            self.lbl_shortcut_status.setText(
                self.tr("Shortcut could not be created. See log for details.")
            )

    def _create_folder_shortcut(self) -> None:
        """Desktop shortcut to the configured default export/import
        folder — distinct .lnk name from _create_shortcut's app
        shortcut so the two don't overwrite each other on the desktop."""
        target = Path(self.state.app_settings.default_files_dir or str(Path.home() / "Documents"))
        if not target.is_dir():
            self.lbl_folder_shortcut_status.setText(
                self.tr("Folder does not exist yet: {path}").format(path=target)
            )
            log.info("folder shortcut request denied: %s does not exist", target)
            return
        lnk = create_desktop_shortcut(target, name=self.tr("OIK folder"))
        if lnk is not None:
            self.lbl_folder_shortcut_status.setText(
                self.tr("Shortcut created: {lnk}").format(lnk=lnk)
            )
        else:
            self.lbl_folder_shortcut_status.setText(
                self.tr("Shortcut could not be created. See log for details.")
            )

    def _refresh_maintenance_box(self) -> None:
        """Show the one-off Maintenance box only while an action is
        pending (see core/maintenance.py). Hidden by default."""
        from biracki_odbor.core import maintenance
        key = self.state.app_settings.pending_maintenance_action
        action = maintenance.get(key) if key else None
        self.maintenance_box.setVisible(action is not None)
        if action is not None:
            self.lbl_maintenance_desc.setText(action.description_sr)
            self.btn_run_maintenance.setText(action.label_sr)

    def _on_run_maintenance_action(self) -> None:
        from biracki_odbor.core import maintenance
        key = self.state.app_settings.pending_maintenance_action
        action = maintenance.get(key)
        if action is None:
            self.maintenance_box.setVisible(False)
            return
        try:
            result = action.run()
        except Exception as e:  # noqa: BLE001 — a failed one-off cleanup must not crash the tab
            log.exception("maintenance action %s failed", key)
            QMessageBox.critical(
                self, self.tr("Action failed"),
                self.tr("Could not complete this action: {e}").format(e=e),
            )
            return
        self.state.app_settings.pending_maintenance_action = ""
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        self.maintenance_box.setVisible(False)
        QMessageBox.information(self, self.tr("Done"), result)
        log.info("maintenance action %s completed: %s", key, result)

    def _on_debug_toggled(self, checked: bool) -> None:
        self.state.app_settings.debug_logging = checked
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        log.info("debug_logging toggled to %s (takes effect on next launch)", checked)

    def _on_tab_gating_toggled(self, checked: bool) -> None:
        self.state.app_settings.disable_tab_gating = not checked
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        log.info("disable_tab_gating set to %s", not checked)

    def _on_stall_timeout_changed(self, value: int) -> None:
        if self._loading:
            return
        self.state.app_settings.worker_stall_timeout_seconds = int(value)
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        log.info("worker_stall_timeout_seconds set to %d", value)

    def _on_browse_files_dir(self) -> None:
        start = self.state.app_settings.default_files_dir or str(Path.home() / "Documents")
        path = QFileDialog.getExistingDirectory(self, self.tr("Select folder"), start)
        if not path:
            return
        old = self.state.app_settings.default_files_dir.strip()
        self.ed_files_dir.setText(path)
        self.state.app_settings.default_files_dir = path
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        log.info("default_files_dir set to %s", path)
        old_path = Path(old) if old else None
        if old_path is not None and old_path.is_dir() and old_path.resolve() != Path(path).resolve():
            self._offer_move_export_files(old_path, Path(path))

    def _offer_move_export_files(self, old_base: Path, new_base: Path) -> None:
        """Offer to relocate previously-exported subfolders (party files,
        decisions, revizija, ...) when the operator points the default
        export folder somewhere else mid-cycle, so files generated
        before the change aren't left behind."""
        subdirs = [p for p in old_base.iterdir() if p.is_dir()]
        if not subdirs:
            return
        if QMessageBox.question(
            self, self.tr("Move existing files?"),
            self.tr(
                "Found {n} folder(s) with previously exported files in the"
                " old location:\n{old}\n\nMove them to the new location?\n{new}"
            ).format(n=len(subdirs), old=old_base, new=new_base),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        ) != QMessageBox.Yes:
            return
        moved = 0
        failed: list[str] = []
        for sub in subdirs:
            dest = new_base / sub.name
            try:
                if dest.exists():
                    shutil.copytree(sub, dest, dirs_exist_ok=True)
                    shutil.rmtree(sub)
                else:
                    shutil.move(str(sub), str(dest))
                moved += 1
            except OSError:
                failed.append(sub.name)
                log.warning("failed moving %s -> %s", sub, dest, exc_info=True)
        if failed:
            QMessageBox.warning(
                self, self.tr("Some folders could not be moved"),
                self.tr("Moved {ok}. Failed: {failed}").format(ok=moved, failed=", ".join(failed)),
            )
        else:
            self.banner.show_ok(
                self.tr("Moved {n} folder(s) to the new location.").format(n=moved)
            )

    def _on_language_changed(self, _index: int) -> None:
        if self._loading:
            return
        value = self.cb_language.currentData()
        if not value:
            return
        self.state.app_settings.ui_language = str(value)
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e))
            return
        self.lbl_lang_hint.setVisible(True)
        log.info("ui_language set to %s (takes effect on next launch)", value)

    def _on_email_client_changed(self, _index: int) -> None:
        """Persist the operator's email-client preference immediately.

        Auto-save (no Сачувај click required) mirrors `_on_debug_toggled`
        — both are system prefs whose effect is felt the next time
        Phase 1 send / backup-email runs, not on Save. Status hint
        refreshes so the operator can confirm the pick was accepted.
        """
        if self._loading:
            return
        value = self.cb_email_client.currentData()
        if not value:
            return
        self.state.app_settings.email_client = str(value)
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e),
            )
            return
        log.info("email_client preference set to %s", value)
        self._reload_email_client_field()

    def _on_oik_email_changed(self) -> None:
        if self._loading:
            return
        value = self.ed_oik_email.text().strip()
        self.state.app_settings.oik_email = value
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e),
            )
            return
        log.info("oik_email set to %r", value)

    def _on_nacelnik_email_changed(self) -> None:
        if self._loading:
            return
        value = self.ed_nacelnik_email.text().strip()
        self.state.app_settings.nacelnik_email = value
        try:
            self.state.save_app_settings()
        except OSError as e:
            QMessageBox.warning(
                self, self.tr("Error"), self.tr("Cannot save settings: {e}").format(e=e),
            )
            return
        log.info("nacelnik_email set to %r", value)

    def _open_logs(self) -> None:
        # app.log is live and continuously written, so there's no
        # "generation finished" event to hook — export on click instead,
        # same end result as the other features (never point the
        # operator at the app's own internal storage).
        src_dir = app_paths.log_dir()
        logs = sorted(src_dir.glob("*.log*")) if src_dir.exists() else []
        if logs:
            self.state.export_generated("Логови", logs)
        path = str(self.state.files_dir("Логови"))
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            QMessageBox.information(self, self.tr("Log folder"), f"{path}\n\n({e})")

    # ── Save ───────────────────────────────────────────────

    def _collect_polling_stations(self) -> list[PollingStation]:
        stations: list[PollingStation] = []
        for r, row in enumerate(self._bm_rows):
            try:
                num = int(row["bm_number"].strip())
            except ValueError:
                num = r + 1
            name = row["name"].strip()
            address = row["address"].strip()
            # The operator's own typed value wins — this field is
            # editable precisely so a wrong auto-generated result can
            # be overridden (see default_station_full_name). Only falls
            # back to the Name+Address default when left blank.
            full_name = row.get("full_name", "").strip() or default_station_full_name(name, address)
            stations.append(PollingStation(
                bm_number=num,
                name=name,
                address=address,
                full_name=full_name,
            ))
        return stations

    def _save(self) -> None:
        picked = opstine_mod.find_by_sifra(self._last_valid_sifra)
        self.state.oik.municipality = Municipality(
            name=picked.document_name if picked else self.cb_name.currentText().strip(),
            sifra_opstine=self._last_valid_sifra,
            name_genitive=self.ed_genitive.text().strip(),
            name_locative=self.ed_locative.text().strip(),
            full_committee_name=self.ed_full.text().strip(),
            is_vojvodina=self.cb_vojvodina.isChecked(),
            website=self.ed_website.text().strip(),
        )
        self.state.oik.chairman = Chairman(
            title=self.ed_ch_title.text().strip() or "ПРЕДСЕДНИК",
            name=self.ed_ch_name.text().strip(),
        )
        self.state.oik.nacelnik_full_name = self.ed_nacelnik_full_name.text().strip()
        # Line spacing and title/body spacing are edited on the generation
        # screens (Phase 3, Измене), not here — carry the existing values
        # forward so saving from this tab doesn't reset them to defaults.
        old_fmt = self.state.oik.document_format
        self.state.oik.document_format = DocumentFormat(
            line_spacing=old_fmt.line_spacing,
            header_distance_cm=self.sb_header_distance.value(),
            footer_distance_cm=self.sb_footer_distance.value(),
            title_before_pt=old_fmt.title_before_pt,
            title_after_pt=old_fmt.title_after_pt,
            body_before_pt=old_fmt.body_before_pt,
            body_after_pt=old_fmt.body_after_pt,
        )
        self.state.oik.polling_stations = self._collect_polling_stations()

        errors = self.state.oik.validate()
        if errors:
            self.banner.show_error(
                self.tr("Settings are incomplete:\n  • ") + "\n  • ".join(errors)
            )
            return
        try:
            self.state.save_oik()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        self.dirty = False
        self.banner.show_ok(self.tr("Settings saved."))
