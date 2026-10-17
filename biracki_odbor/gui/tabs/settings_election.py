"""Изборна конфигурација — per-election settings.

Multi-column responsive layout: two columns when the viewport has ≥1000px
of horizontal room, single column below that. Wrapped in a scroll area
with a 1200px max-width container so the form stays comfortable on both
wide and narrow monitors.

Fields the user used to type that the program now derives:
  - date_genitive (computed from date_full via month declension)
  - year (parsed from date_full)
  - types_upper (uppercase of expanded type strings)

session_date and session_number live in the data model but are edited on
the Phase 3 workflow tab — they change per OIK session, not per cycle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from biracki_odbor.core.phone import normalize as phone_normalize
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.searchable_table import (
    RowEditDialog, SearchableTable, SingleLineEdit,
)

from biracki_odbor import app_paths
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.config import declension
from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
    RikProvision, RikBmEntry, RikPerson, rik_provision_articles,
)
from biracki_odbor.core.models import Allocation, PartyQuota
from biracki_odbor.core import rik_raspodela_import as rik_raspodela_mod
from biracki_odbor.core.rik_xlsx import export_rik_template, import_rik_xlsx
from biracki_odbor.core.template import (
    build_blank_template, build_candidacies_workbook, build_entities_template,
    build_parties_workbook, build_quotas_workbook, read_candidacies_workbook,
    read_entities_sheet, read_parties_sheet, read_quotas_sheet, read_template,
)
from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
from biracki_odbor.gui.worker import start_worker
from biracki_odbor.config.candidacies import (
    Candidate, CandidaciesRegistry, Entity,
    ENTITY_TYPES, LEVEL_KEYS,
)
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.spinbox import hide_spinbox_buttons, inset_spinbox_text
from biracki_odbor.gui.widgets.validators import int_validator, jmbg_validator


_TWO_COL_MIN = 1000


class _QuotaSpinBox(QSpinBox):
    """Numeric-only quota entry — no up/down arrows, no wheel-scroll.

    Both are easy to trigger by accident (a stray scroll while reading
    the page silently changes a legally meaningful count) and add
    nothing for a one-off manually-typed number from the RIK decision.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        hide_spinbox_buttons(self)
        inset_spinbox_text(self, 4)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class _RikBmFields:
    """Holds the 10 QLineEdit widgets for one BM's RIK member + deputy."""
    __slots__ = (
        "bm_number",
        "m_name", "m_jmbg", "m_address", "m_phone", "m_email",
        "d_name", "d_jmbg", "d_address", "d_phone", "d_email",
    )

    def __init__(self, bm_number: int) -> None:
        self.bm_number = bm_number
        self.m_name    = QLineEdit(); self.m_name.setPlaceholderText("Име и презиме")
        self.m_jmbg    = QLineEdit(); self.m_jmbg.setPlaceholderText("ЈМБГ")
        self.m_address = QLineEdit(); self.m_address.setPlaceholderText("Место / адреса")
        self.m_phone   = QLineEdit(); self.m_phone.setPlaceholderText("Телефон")
        self.m_email   = QLineEdit(); self.m_email.setPlaceholderText("Е-пошта")
        self.d_name    = QLineEdit(); self.d_name.setPlaceholderText("Име и презиме")
        self.d_jmbg    = QLineEdit(); self.d_jmbg.setPlaceholderText("ЈМБГ")
        self.d_address = QLineEdit(); self.d_address.setPlaceholderText("Место / адреса")
        self.d_phone   = QLineEdit(); self.d_phone.setPlaceholderText("Телефон")
        self.d_email   = QLineEdit(); self.d_email.setPlaceholderText("Е-пошта")

    def all_editors(self) -> list[QLineEdit]:
        return [
            self.m_name, self.m_jmbg, self.m_address, self.m_phone, self.m_email,
            self.d_name, self.d_jmbg, self.d_address, self.d_phone, self.d_email,
        ]

    def load(self, entry: RikBmEntry) -> None:
        self.m_name.setText(entry.member.name)
        self.m_jmbg.setText(entry.member.jmbg)
        self.m_address.setText(entry.member.address)
        self.m_phone.setText(entry.member.phone)
        self.m_email.setText(entry.member.email)
        self.d_name.setText(entry.deputy.name)
        self.d_jmbg.setText(entry.deputy.jmbg)
        self.d_address.setText(entry.deputy.address)
        self.d_phone.setText(entry.deputy.phone)
        self.d_email.setText(entry.deputy.email)

    def to_entry(self) -> RikBmEntry:
        return RikBmEntry(
            member=RikPerson(
                name=self.m_name.text().strip(),
                jmbg=self.m_jmbg.text().strip(),
                address=self.m_address.text().strip(),
                phone=self.m_phone.text().strip(),
                email=self.m_email.text().strip(),
            ),
            deputy=RikPerson(
                name=self.d_name.text().strip(),
                jmbg=self.d_jmbg.text().strip(),
                address=self.d_address.text().strip(),
                phone=self.d_phone.text().strip(),
                email=self.d_email.text().strip(),
            ),
        )


def _next_election_sunday() -> QDate:
    """Return the first Sunday that is at least 30 days from today.

    Serbian elections are held on Sundays; the legal minimum announcement
    window is 30 days, so this is the earliest legally valid election date.
    """
    d = QDate.currentDate().addDays(30)
    # QDate.dayOfWeek(): 1=Mon … 7=Sun
    days_to_sunday = (7 - d.dayOfWeek()) % 7
    return d.addDays(days_to_sunday)


def _iso_to_qdate(s: str) -> QDate | None:
    """Parse "YYYY-MM-DD" → QDate; return None if unparseable."""
    parts = s.split("-")
    if len(parts) == 3:
        try:
            return QDate(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            pass
    return None


def _qdate_to_iso(d: QDate) -> str:
    return f"{d.year():04d}-{d.month():02d}-{d.day():02d}"


class ElectionSettingsTab(QWidget):
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
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        outer.addWidget(scroll, stretch=1)

        # Centering wrap with a max-width cap so the form is fluid
        # between ~720 px (low-end laptops) and 1600 px (above which
        # ultrawide monitors otherwise stretch text lines past the
        # comfortable reading width). Below 1600 px workspace width
        # the container fills edge to edge; above it, the side
        # stretches absorb the extra space.
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

        # No page title / hint inside the body — the sidebar already
        # labels this page, and the inner-tab strip below becomes the
        # dominant top element of the workspace. The intro copy
        # ("Ове поставке се мењају при свакој расписаној…") fires once
        # at construction via the banner (auto-hides after 5 s) so the
        # user sees the context the first time they land here without
        # it eating permanent vertical space on every visit.
        self.banner = StatusBanner()
        self._first_open_note = self.tr(
            "Election configuration — these settings change with each election year."
            " After changing, re-run Phase 1."
        )

        # Документ card (Бројчани префикс + Правни основ) + текст
        # образложења moved to Фаза 3 (где се и користе). Уреди као JSON
        # уклоњено — JSON није ОИК-овски ниво апстракције.
        self._dates_box = self._build_dates_group()
        self._types_box = self._build_types_group()
        self._rik_box = self._build_rik_group()
        self._password_box = self._build_password_group()
        self._rik_toggle_box = self._build_rik_toggle_group()
        self._party_files_box = self._build_party_files_group()

        # Left-column container — wraps all four left boxes so the grid is
        # always 1 row × 2 cols.  This decouples the two column heights:
        # _rik_box can grow/shrink freely without forcing the left boxes to
        # stretch to match its row span.
        self._left_col = QWidget()
        _lv = QVBoxLayout(self._left_col)
        _lv.setContentsMargins(0, 0, 0, 0)
        _lv.setSpacing(14)
        _lv.addWidget(self._dates_box)
        _lv.addWidget(self._types_box)
        _lv.addWidget(self._password_box)
        _lv.addWidget(self._rik_toggle_box)
        _lv.addWidget(self._party_files_box)
        _lv.addStretch()

        # Filter state for the Листе tab cascade:
        #   level_filter "" → show all entities; otherwise exact level match.
        #   entity_filter "" → show all candidates; otherwise entity_id match.
        self._entity_level_filter: str = ""
        self._entity_filter: str = ""
        self._visible_entity_rows: list[dict] = []
        self._visible_candidate_rows: list[dict] = []

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        self._current_cols = -1

        # ── Inner tabs ───────────────────────────────────────
        # Two visible tabs (+ 1 conditional). Save + banner + dirty-flag
        # plumbing stay outside the tab widget, applying across all tabs.
        self.inner_tabs = QTabWidget()
        self.inner_tabs.setDocumentMode(True)
        self.inner_tabs.setMovable(False)
        self.inner_tabs.setUsesScrollButtons(False)
        root.addWidget(self.inner_tabs, stretch=1)

        # Tab 1 — Изборни циклус: dates + types + password + toggle (left);
        # Одлука РИК-а + Посланичке групе + Шаблон (right).
        izborni_page = QWidget()
        izborni_layout = QVBoxLayout(izborni_page)
        izborni_layout.setContentsMargins(0, 14, 0, 0)
        izborni_layout.addWidget(self._grid_host)
        izborni_layout.addStretch(1)
        self.inner_tabs.addTab(izborni_page, self.tr("1. Election cycle"))

        # Tab 2 — Листе: level picker → electoral lists → candidates.
        # Посланичке групе moved to Tab 1 (inside Одлука РИК-а card).
        self.inner_tabs.addTab(self._build_ucesnici_tab(), self.tr("2. Lists"))

        # Tab 3 — Члан из РИК-а (conditional — visible only when the
        # "Transitional provision active" toggle in Tab 1 is on).
        self._rik_bm_fields: dict[int, _RikBmFields] = {}
        self.inner_tabs.addTab(self._build_rik_member_tab(), self.tr("3. RIK member"))
        self.inner_tabs.setTabVisible(2, False)

        self.state.oik_changed.connect(self._rebuild_rik_bm_cards)
        self.state.oik_changed.connect(self._rebuild_matrix_grid)
        self.state.oik_changed.connect(self._refresh_quota_totals_row)
        self.state.template_changed.connect(self._refresh_template_status)
        self.state.template_changed.connect(self._rebuild_matrix_grid)
        self.sw_rik_active.toggled.connect(self._on_rik_toggled)
        self.sw_rik_active.toggled.connect(self._mark_dirty)
        self.sw_combined_name_header.toggled.connect(self._mark_dirty)

        # Banner lives ABOVE the sticky dock — not inside it — so the
        # dock stays a constant 72 px tall regardless of banner state.
        # That 72 px matches the О апликацији sidebar item's min-height,
        # so the bottom row of the window has a clean horizontal line
        # across sidebar and workspace. When the banner shows, the
        # scroll area shrinks by the banner height; when it hides, the
        # scroll area reclaims that space — the dock never moves.
        outer.addWidget(self.banner)
        dock = QFrame()
        dock.setObjectName("StickyDock")
        dock.setFixedHeight(72)
        dock_h = QHBoxLayout(dock)
        # Vertical margin was 14 — at BODY_PT=14 a QPushButton's natural
        # height (padding + border + Cyrillic line height) comes out to
        # ~44px, exactly the 72-2*14 available, zero headroom. Descenders
        # on ц/р/д clipped at the bottom under normal font-metric
        # variance. 10 reclaims a few px without touching the fixed 72px
        # (tied to the sidebar's О апликацији item height — see above).
        dock_h.setContentsMargins(16, 10, 16, 10)
        dock_h.setSpacing(10)
        # «Уреди као JSON…» removed — JSON wasn't the right level of
        # abstraction for OIK operators. «Уреди текст образложења…»
        # moved to Фаза 3 alongside the Правни основ field (they're
        # both про-документ pieces and live next to where they apply).
        self.btn_new_cycle = QPushButton(self.tr("New election cycle…"))
        self.btn_new_cycle.setObjectName("DestructiveButton")
        self.btn_new_cycle.setToolTip(self.tr(
            "Creates a backup of the current cycle, clears output files,\n"
            "resets election settings (dates, parties, candidacies, RIK\n"
            "provision, lock password) to a blank slate, and assigns a\n"
            "new cycle identifier. OIK/municipality identity is kept."
        ))
        self.btn_new_cycle.clicked.connect(self._on_new_cycle)
        dock_h.addWidget(self.btn_new_cycle)
        dock_h.addStretch()
        self.btn_save = QPushButton(self.tr("Save settings"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._save)
        dock_h.addWidget(self.btn_save)
        outer.addWidget(dock)

        self.state.oik_changed.connect(self._reload_password_field)
        self.state.oik_changed.connect(self._refresh_provincial_visibility)

        # Dirty-flag wiring (see main_window's tab-change interception).
        self.dirty = False
        self._loading = False
        self._wire_dirty_signals()

        self._load_from_state()
        self._relayout(self.width())

        # First-open intro notice. show_info auto-hides after 5 s
        # (banner.py), so it doesn't permanently consume dock space.
        # Fires once per construction — that's once per app launch since
        # MainWindow keeps the page alive across sidebar switches.
        self.banner.show_info(self._first_open_note)

    # ── Dirty-flag plumbing ────────────────────────────────

    def _mark_dirty(self, *_args, **_kwargs) -> None:
        if not self._loading:
            self.dirty = True

    def _wire_dirty_signals(self) -> None:
        self.date_picker.dateChanged.connect(self._mark_dirty)
        self.cutoff_stalni_picker.dateChanged.connect(self._mark_dirty)
        self.cutoff_prosireni_picker.dateChanged.connect(self._mark_dirty)
        self.cutoff_posmatraci_picker.dateChanged.connect(self._mark_dirty)
        for cb in self._type_checks.values():
            cb.toggled.connect(self._mark_dirty)
            cb.toggled.connect(self._refresh_level_selector)
        self.ed_rik_broj.textChanged.connect(self._mark_dirty)
        self.rik_date_picker.dateChanged.connect(self._mark_dirty)
        # number_prefix + legal_basis live on Фаза 3 now (Број решења +
        # Правни основ groups) — they save themselves there on focusOut.
        # Parties table is now a SearchableTable (read-only cells +
        # popup edit dialog). Dirty is set directly in _add/_edit/
        # _remove/_import handlers — no per-cell signal to wire here.
        # ed_password persists immediately to OIK on editingFinished
        # (see _save_password_field), so we don't track it as a settings
        # tab dirty signal — that field is "auto-saved" by design.

    def save(self) -> bool:
        try:
            self._save()
        except Exception:  # noqa: BLE001
            return False
        self.dirty = False
        return True

    def revert(self) -> None:
        self._load_from_state()
        self.dirty = False

    # ── Builders ───────────────────────────────────────────

    def _build_template_group(self) -> CollapsibleSection:
        self._template_section = CollapsibleSection(
            self.tr("Allocation template"),
            self.tr("BM × functions matrix"),
        )

        hint = QLabel(self.tr(
            "The allocation template (Stalni_sastav.xlsx) is supplied by RIK each election"
            " cycle. It contains the party assignment matrix (Raspodela sheet) that drives"
            " Phases 1 and 2. Edit the matrix directly below, or import/export as Excel."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        self.lbl_tpl_status = QLabel("")
        self.lbl_tpl_status.setObjectName("MutedLabel")
        self.lbl_tpl_status.setWordWrap(True)

        btn_import_qa = QPushButton(self.tr("Import"))
        btn_import_qa.clicked.connect(self._import_template_excel)
        self._template_section.add_quick_action(btn_import_qa)

        btns = QHBoxLayout()
        btn_import = QPushButton(self.tr("Import"))
        btn_import.setToolTip(self.tr("Import the Raspodela matrix from an Excel file."))
        btn_import.clicked.connect(self._import_template_excel)
        btns.addWidget(btn_import)

        btn_export_matrix = QPushButton(self.tr("Export"))
        btn_export_matrix.setToolTip(self.tr(
            "Generates a blank Raspodela matrix pre-filled with the polling"
            " stations currently configured in OIK Settings — so BM numbers"
            " always match and Phase 1 never reports “BM not in the list”."
        ))
        btn_export_matrix.clicked.connect(self._export_matrix_template)
        btns.addWidget(btn_export_matrix)

        btns.addStretch()

        self._matrix_grid_host = QWidget()
        self._matrix_grid_layout = QVBoxLayout(self._matrix_grid_host)
        self._matrix_grid_layout.setContentsMargins(0, 0, 0, 0)
        self._matrix_grid: object | None = None

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)
        body_vbox.addWidget(hint)
        body_vbox.addWidget(self.lbl_tpl_status)
        body_vbox.addLayout(btns)
        body_vbox.addWidget(self._matrix_grid_host, stretch=1)
        self._template_section.set_content(body)

        self._refresh_template_status()
        self._rebuild_matrix_grid()
        return self._template_section

    def _import_template_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import Excel"), str(self.state.files_dir("Расподела")),
            self.tr("Excel (*.xlsx)"),
        )
        if not path:
            return
        self._on_template_chosen(path)

    def _import_from_rik_files(self) -> None:
        """Consume RIK's own multi-municipality RASPODELA export (plus,
        optionally, its UKUPNO summary) directly — the whole point being
        the operator never re-types what RIK already sent. Located
        purely by `oik.municipality.sifra_opstine` (set on the OIK
        Settings → General picker); never by name search.

        UKUPNO (parliamentary group names) is picked FIRST, RASPODELA
        (allocation + quotas) second — group names are ready before any
        new group row is created, instead of appearing blank and being
        backfilled a moment later. The actual parsing (both files can be
        large) runs on a background thread via `gui.worker.start_worker`
        with a real progress bar, so the window never freezes — only the
        file dialogs and safety checks below run on the GUI thread,
        since Qt requires that.
        """
        sifra = self.state.oik.municipality.sifra_opstine
        if not sifra:
            self.banner.show_error(self.tr(
                "Select the municipality first (OIK Settings → General"
                " tab → Name), so the correct block can be located in"
                " the RIK file."
            ))
            return

        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg

        ukupno_path, _ = QFileDialog.getOpenFileName(
            self, self.tr(
                "Select the RIK UKUPNO file for official parliamentary"
                " group names (optional — Cancel to skip)"
            ),
            str(self.state.files_dir("Расподела")),
            self.tr("Excel (*.xlsx)"),
        )
        if ukupno_path:
            safety = popunjeni_io.check_file_safety(Path(ukupno_path))
            if not safety.ok:
                self.banner.show_warn(self.tr(
                    "UKUPNO file skipped: {detail}"
                ).format(detail=safety.detail or safety.code))
                ukupno_path = ""

        raspodela_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select the RIK RASPODELA file"),
            str(self.state.files_dir("Расподела")),
            self.tr("Excel (*.xlsx)"),
        )
        if not raspodela_path:
            return
        safety = popunjeni_io.check_file_safety(Path(raspodela_path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=Path(raspodela_path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return

        has_existing = bool(self.state.oik.polling_stations) or bool(self._parties_rows)
        if has_existing:
            reply = QMessageBox.question(
                self, self.tr("Replace existing data"),
                self.tr(
                    "This will replace the current polling-station list and"
                    " allocation matrix, and merge in parliamentary group"
                    " quotas from the RIK file. Continue?"
                ),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.btn_import_rik.setEnabled(False)
        self.rik_import_progress.setVisible(True)
        self.rik_import_progress.setRange(0, 0)
        self.rik_import_progress.setFormat("")

        self._rik_worker, self._rik_thread = start_worker(
            self, rik_raspodela_mod.import_municipality,
            raspodela_path, sifra, ukupno_path=(ukupno_path or None),
        )
        self._rik_worker.progress.connect(self._on_rik_import_progress)
        self._rik_worker.finished.connect(self._on_rik_import_finished)
        self._rik_worker.failed.connect(self._on_rik_import_failed)

    def _on_rik_import_progress(self, label: str, _current: int, _total: int) -> None:
        # Stays in indeterminate/busy mode (range (0, 0), set when the
        # worker was dispatched) rather than showing a numeric X/Y
        # fraction: with only two coarse steps, a static "1/2" that
        # doesn't move for however long the actual parse takes (real
        # RASPODELA files run ~11 000 rows) reads as frozen. The
        # continuously-animated busy bar makes "still working" visible
        # regardless of how long a step takes; the label still says
        # which file is being read.
        self.rik_import_progress.setFormat(label)

    def _rik_import_done(self) -> None:
        self.rik_import_progress.setVisible(False)
        self.btn_import_rik.setEnabled(True)

    def _on_rik_import_failed(self, err: str) -> None:
        self._rik_import_done()
        QMessageBox.critical(self, self.tr("Error"), err)
        self.banner.show_error(self.tr("RIK import failed: {error}").format(error=err))

    def _on_rik_import_finished(self, result) -> None:
        self._rik_import_done()
        if result.errors:
            self.banner.show_error("\n".join(result.errors))
            return
        if not result.stations:
            self.banner.show_error(self.tr(
                "No polling stations found for this municipality in the"
                " selected file."
            ))
            return

        # Polling stations live on OikConstants, not this tab's own
        # buffer — save immediately; OikSettingsTab picks up the change
        # via its existing external-change listener (same mechanism any
        # other cross-tab OIK edit already relies on).
        #
        # RIK's RASPODELA export is a party-allocation matrix, not a
        # polling-station directory — it only ever carries bm_number
        # (see core.rik_raspodela_import._read_allocation_grid), never
        # name/address/full_name. A plain replace therefore wiped out
        # every already-entered BM name/address on every import, with
        # no way for RIK's own data to ever supply a better one — a
        # field report confirmed exactly this ("erasing the saved bm
        # names"). Preserve the existing name/address/full_name for any
        # bm_number already on file; only a genuinely new BM (one RIK
        # reports that wasn't configured before) gets blank ones, same
        # as before.
        existing_by_bm = {s.bm_number: s for s in self.state.oik.polling_stations}
        self.state.oik.polling_stations = [
            existing_by_bm[s.bm_number] if s.bm_number in existing_by_bm else s
            for s in result.stations
        ]
        try:
            self.state.save_oik()
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot save polling stations:\n{e}").format(e=e),
            )
            return

        # Allocation grid — the exact same write path _save_matrix() uses.
        canonical = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
        try:
            build_blank_template(
                canonical, stations=result.stations, allocations=result.allocations,
            )
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot write template:\n{e}").format(e=e),
            )
            return
        self._on_template_chosen(str(canonical), silent=True)

        # Quotas + parliamentary groups are this tab's own live buffers —
        # merge and refresh, but (like every other import on this tab)
        # don't save automatically; the operator still clicks "Save settings".
        self.state.election.party_quotas = {
            **self.state.election.party_quotas, **result.quotas,
        }
        existing_by_abbrev = {r["abbrev"].strip(): r for r in self._parties_rows}
        added = 0
        filled = 0
        for abbrev in result.quotas:
            full_name = result.party_full_names.get(abbrev, "")
            row = existing_by_abbrev.get(abbrev)
            if row is None:
                self._append_party_row(abbrev, full_name)
                added += 1
            elif full_name and not row["full"].strip():
                # Backfill only — a party already known with SOME full
                # name (manually typed, or from an earlier import) keeps
                # it untouched, same as quotas never override a manual
                # edit elsewhere on this tab. But a row that exists with
                # an empty full name (e.g. an earlier RASPODELA-only
                # import, run before a UKUPNO/legend file was ever
                # supplied) must not stay blank forever just because the
                # abbreviation itself was already on file — a field
                # report confirmed "Пуни назив" stayed empty across
                # repeated re-imports even after supplying the file that
                # actually carries the names.
                row["full"] = full_name
                filled += 1
        self._refresh_parties_view()
        self._mark_dirty()

        self.banner.show_ok(self.tr(
            "Imported {n_bm} polling stations, {n_alloc} allocation(s),"
            " and {n_q} parliamentary group quota(s) ({n_new} new,"
            " {n_filled} full name(s) filled in)."
            " Click 'Save settings' to persist the groups/quotas."
        ).format(
            n_bm=len(result.stations), n_alloc=len(result.allocations),
            n_q=len(result.quotas), n_new=added, n_filled=filled,
        ))

    def _rebuild_matrix_grid(self) -> None:
        """(Re)build the embedded matrix grid from current OIK/party/template
        state. Called after OIK/template changes and after saving this tab —
        rebuilding (not patching in place) keeps this simple since row count
        (stations) and dropdown items (parties) can both change independently.
        """
        from biracki_odbor.gui.widgets.matrix_grid_widget import MatrixGridWidget

        while self._matrix_grid_layout.count():
            item = self._matrix_grid_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._matrix_grid = None

        stations = list(self.state.oik.polling_stations)
        # Read the party list from the tab's own live (possibly unsaved)
        # rows, not self.state.election.party_full_names — that only
        # reflects the last Save, so adding a party and never seeing the
        # grid appear (until Save) was a real, reported bug, most visible
        # right after a "New election cycle" reset when the list starts
        # empty and the very first addition is what should reveal the grid.
        party_abbrevs = [
            r["abbrev"].strip() for r in self._parties_rows
            if r["abbrev"].strip() and r["abbrev"].strip() != "_default"
        ]
        if not stations or not party_abbrevs:
            # Locked + collapsed rather than open-with-a-placeholder — the
            # section visibly reads as "not ready yet" instead of looking
            # like a broken/empty feature (field report: "matrix box
            # should remain gray/closed until all of its requirements are
            # filled"). set_expanded() still works while locked (used
            # here), only the operator's own arrow/Hide-Show click is
            # blocked — see CollapsibleSection.set_locked's docstring.
            self._template_section.set_description(self.tr(
                "configure polling stations (OIK Settings) and parliamentary"
                " groups (above) first"
            ))
            self._template_section.set_locked(True)
            self._template_section.set_expanded(False)
            placeholder = QLabel(self.tr(
                "Configure polling stations (OIK Settings) and parliamentary"
                " groups (above) to edit the matrix."
            ))
            placeholder.setObjectName("MutedLabel")
            placeholder.setWordWrap(True)
            self._matrix_grid_layout.addWidget(placeholder)
            return

        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            tp = self.state.template_path()
        except IntegrityMismatchError as e:
            # Passive here — _refresh_template_status() owns the
            # interactive restore dialog for this same template_changed
            # signal, so this method doesn't also pop one (both are
            # connected to it; showing two dialogs back to back is bad UX).
            self._template_section.set_description(self.tr("BM × functions matrix"))
            self._template_section.set_locked(True)
            self._template_section.set_expanded(False)
            placeholder = QLabel(self.tr(
                "{name} was changed outside the application since it was"
                " last verified ({when}). See the banner above to restore it."
            ).format(name=e.path.name, when=e.verified_at))
            placeholder.setObjectName("MutedLabel")
            placeholder.setWordWrap(True)
            self._matrix_grid_layout.addWidget(placeholder)
            return

        self._template_section.set_description(self.tr("BM × functions matrix"))
        self._template_section.set_locked(False)

        existing: list[Allocation] = []
        if tp is not None and Path(tp).exists():
            tpl_data, _report = read_template(tp)
            existing = tpl_data.allocations

        grid = MatrixGridWidget(stations, party_abbrevs, existing, self.state.election.party_quotas, self)
        self._matrix_grid_layout.addWidget(grid)
        self._matrix_grid = grid

    def _save_matrix(self) -> None:
        if self._matrix_grid is None:
            return
        allocations = self._matrix_grid.result_allocations()
        canonical = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
        try:
            build_blank_template(
                canonical, stations=list(self.state.oik.polling_stations), allocations=allocations,
            )
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot write template:\n{e}").format(e=e),
            )
            return
        self._on_template_chosen(str(canonical), silent=True)

    def _export_matrix_template(self) -> None:
        """Export a blank Stalni_sastav.xlsx seeded with the OIK's actual
        BM numbers/names, so the operator (or whoever fills in the party
        allocation) can't drift out of sync with OIK Settings — the
        recurring "BM not in the list" complaint was the generated
        template using a plain 1..N range instead of the real BM numbers.
        """
        default_path = str(self.state.files_dir("Расподела") / "Stalni_sastav.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export matrix template"), default_path, self.tr("Excel (*.xlsx)")
        )
        if not path:
            return
        try:
            build_blank_template(path, stations=list(self.state.oik.polling_stations))
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"), self.tr("Cannot write template:\n{e}").format(e=e),
            )
            return
        self.banner.show_ok(self.tr("Matrix template exported: {path}").format(path=path))
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _refresh_template_status(self) -> None:
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            tp = self.state.template_path()
        except IntegrityMismatchError as e:
            self.lbl_tpl_status.setText(
                self.tr("<span style='color:#9B0000'>{name} changed outside"
                        " the application</span>").format(name=e.path.name)
            )
            from biracki_odbor.gui.dialogs.integrity_dialog import handle_integrity_mismatch

            def _on_resolved() -> None:
                self._refresh_template_status()
                self._rebuild_matrix_grid()

            handle_integrity_mismatch(self, self.banner, e, _on_resolved)
            return
        if tp is not None:
            self.lbl_tpl_status.setText(
                self.tr("Template: {name}").format(name=Path(tp).name)
            )
        else:
            self.lbl_tpl_status.setText(self.tr("No template uploaded yet."))

    def _on_template_chosen(self, path: str, *, silent: bool = False) -> None:
        """`silent=True` is for `_save_matrix()`'s own call — the file it
        just wrote is OUR canonical, just-generated file, not an external
        import, so none of the import-specific user-facing messaging
        applies:
          - BM-mismatch warning: `result_allocations()` only includes
            filled cells, so any BM with no assignments YET (completely
            normal mid-editing — the matrix isn't required to be fully
            filled before saving) would always show up as "missing from
            template", a false alarm on every routine Save.
          - "New parties found" prompt: the grid's dropdowns only ever
            offer already-declared parties, so this can never actually
            fire from a save — but stays guarded for correctness.
          - The "Template imported: N stations, M parties" banner would
            overwrite _save()'s own "Election configuration saved."
            banner on every single save.
        """
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        src = Path(path)
        safety = popunjeni_io.check_file_safety(src)
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid Template"),
                _msg(safety.code, file=src.name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            self.banner.show_error(self.tr("Template rejected — see message."))
            return

        canonical = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
        try:
            if src.resolve() != canonical.resolve():
                shutil.copy2(src, canonical)
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot copy template: {e}").format(e=e),
            )
            return

        # This copy just passed the safety pipeline (or, when called
        # silently from _save_matrix(), was written by our own export
        # logic) — fingerprint it now so later reads can detect any
        # out-of-band change. See core/file_integrity.py.
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(canonical)

        self.state.set_template_path(canonical)

        # Read template for validation — failures are non-fatal warnings.
        tpl_data, report = read_template(canonical)

        # ── BM cross-validation ──────────────────────────────────────
        configured_bms = {s.bm_number for s in self.state.oik.polling_stations}
        template_bms = {a.bm_number for a in tpl_data.allocations}
        extra_in_tpl = sorted(template_bms - configured_bms)
        missing_in_tpl = sorted(configured_bms - template_bms)
        bm_warnings: list[str] = []
        if extra_in_tpl:
            bm_warnings.append(
                self.tr("Template has BMs not in OIK config: {bms}").format(
                    bms=", ".join(str(b) for b in extra_in_tpl)
                )
            )
        if missing_in_tpl:
            bm_warnings.append(
                self.tr("OIK config has BMs missing from template: {bms}").format(
                    bms=", ".join(str(b) for b in missing_in_tpl)
                )
            )
        if bm_warnings and not silent:
            QMessageBox.warning(
                self, self.tr("BM mismatch"),
                self.tr(
                    "The template's polling station numbers do not match OIK"
                    " configuration. Check Поставке ОИК → Бирачка места.\n\n"
                ) + "\n".join(bm_warnings),
            )

        # ── Party abbreviation seeding ───────────────────────────────
        existing_abbrevs = {
            k for k in self.state.election.party_full_names if k != "_default"
        }
        new_abbrevs = sorted(tpl_data.parties - existing_abbrevs)
        if new_abbrevs and not silent:
            reply = QMessageBox.question(
                self,
                self.tr("New parties found"),
                self.tr(
                    "The template contains {n} abbreviation(s) not yet in"
                    " Parliamentary groups:\n\n{abbrevs}\n\n"
                    "Add them to Parliamentary groups? (Full names will be empty"
                    " — fill them in before saving.)"
                ).format(
                    n=len(new_abbrevs),
                    abbrevs=", ".join(new_abbrevs),
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                for abbrev in new_abbrevs:
                    self._append_party_row(abbrev, "", "", "")
                self._refresh_parties_view()
                self._mark_dirty()
                self.banner.show_ok(
                    self.tr(
                        "Template imported. {n} new abbreviation(s) added to"
                        " Parliamentary groups — fill in full names, then save."
                    ).format(n=len(new_abbrevs))
                )
                return

        if silent:
            return
        self.banner.show_ok(
            self.tr("Template imported: {n_bm} polling stations, {n_p} parties.").format(
                n_bm=len(template_bms), n_p=len(tpl_data.parties),
            )
        )

    def _build_dates_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("Election date and deadlines"))
        outer = QVBoxLayout(box)
        outer.setSpacing(10)

        date_form = QFormLayout()
        date_form.setLabelAlignment(Qt.AlignRight)
        self.date_picker = make_date_picker()
        self.date_picker.dateChanged.connect(self._recalculate_cutoffs)
        date_form.addRow(self.tr("Election date:"), self.date_picker)
        outer.addLayout(date_form)

        cutoff_header = QLabel(self.tr("Submission deadlines"))
        cutoff_header.setStyleSheet("font-weight: 600;")
        outer.addWidget(cutoff_header)

        cutoff_hint = QLabel(self.tr(
            "Auto-calculated from the election date — can be changed manually."
        ))
        cutoff_hint.setObjectName("MutedLabel")
        cutoff_hint.setWordWrap(True)
        outer.addWidget(cutoff_hint)

        cutoff_form = QFormLayout()
        cutoff_form.setLabelAlignment(Qt.AlignRight)
        cutoff_form.setSpacing(10)
        cutoff_form.setContentsMargins(0, 2, 0, 0)

        for name, picker_attr, delta_attr in (
            (self.tr("Permanent composition"), "cutoff_stalni_picker",    "_delta_stalni"),
            (self.tr("Extended composition"),  "cutoff_prosireni_picker", "_delta_prosireni"),
            (self.tr("Observers"),             "cutoff_posmatraci_picker","_delta_posmatraci"),
        ):
            lbl_w = QWidget()
            lbl_vbox = QVBoxLayout(lbl_w)
            lbl_vbox.setContentsMargins(0, 0, 4, 0)
            lbl_vbox.setSpacing(1)
            lbl_vbox.addWidget(QLabel(name))
            delta_lbl = QLabel()
            delta_lbl.setObjectName("MutedLabel")
            lbl_vbox.addWidget(delta_lbl)
            setattr(self, delta_attr, delta_lbl)

            picker = make_date_picker()
            picker.dateChanged.connect(self._refresh_cutoff_labels)
            setattr(self, picker_attr, picker)
            cutoff_form.addRow(lbl_w, picker)

        outer.addLayout(cutoff_form)
        return box

    def _build_types_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("Election types"))
        layout = QVBoxLayout(box)
        self._type_checks: dict[str, ToggleSwitch] = {}
        for key in declension.TYPE_KEYS:
            cb = ToggleSwitch(declension.TYPE_LABELS[key])
            self._type_checks[key] = cb
            layout.addWidget(cb)
        muni_hint = QLabel(self.tr(
            "For local elections, the municipality name from OIK Settings is used."
        ))
        muni_hint.setObjectName("MutedLabel")
        muni_hint.setWordWrap(True)
        layout.addWidget(muni_hint)
        return box

    def _build_rik_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("RIK decision"))
        outer = QVBoxLayout(box)
        outer.setSpacing(12)

        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Decision number:")))
        self.ed_rik_broj = QLineEdit()
        self.ed_rik_broj.setPlaceholderText(self.tr("e.g. 02 no. 013-376/23"))
        # Real values are short reference numbers (e.g. "2") — cap the
        # field at ~15 characters instead of stretching to fill the row.
        self.ed_rik_broj.setMaximumWidth(
            self.ed_rik_broj.fontMetrics().horizontalAdvance("0" * 15) + 16
        )
        row.addWidget(self.ed_rik_broj)

        row.addWidget(QLabel(self.tr("Decision date:")))
        self.rik_date_picker = make_date_picker()
        row.addWidget(self.rik_date_picker)
        row.addStretch()

        self.btn_import_rik = QPushButton(self.tr("Import from RIK files…"))
        self.btn_import_rik.setToolTip(self.tr(
            "Consume RIK's own multi-municipality RASPODELA export (and,"
            " optionally, its UKUPNO summary for official parliamentary"
            " group names) directly — locates this municipality's block"
            " by the code selected on the OIK Settings → General tab,"
            " and fills in polling stations, parliamentary groups +"
            " quotas, and the allocation matrix below, all in one step."
        ))
        self.btn_import_rik.clicked.connect(self._import_from_rik_files)
        row.addWidget(self.btn_import_rik)

        outer.addLayout(row)

        self.rik_import_progress = QProgressBar()
        self.rik_import_progress.setVisible(False)
        outer.addWidget(self.rik_import_progress)

        outer.addWidget(self._build_parties_group(), 1)
        outer.addWidget(self._build_quotas_group())
        outer.addWidget(self._build_template_group())
        outer.addStretch()

        return box

    def _build_password_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("File protection for parties"))
        layout = QVBoxLayout(box)
        layout.setSpacing(8)
        row = QHBoxLayout()
        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.Password)
        self.ed_password.editingFinished.connect(self._save_password_field)
        self.btn_show_pw = QPushButton(self.tr("Show"))
        self.btn_show_pw.setCheckable(True)
        self.btn_show_pw.toggled.connect(
            lambda checked: self.ed_password.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password,
            )
        )
        row.addWidget(self.ed_password)
        row.addWidget(self.btn_show_pw)
        layout.addLayout(row)
        warn = QLabel(self.tr(
            "Locks pre-filled cells in party Excel files."
            " Parties do not need this password — they fill in their"
            " designated unlocked cells freely."
            " The field is saved automatically."
        ))
        warn.setObjectName("MutedLabel")
        warn.setWordWrap(True)
        layout.addWidget(warn)
        return box

    def _build_rik_toggle_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("RIK member (transitional provision)"))
        layout = QVBoxLayout(box)
        self.sw_rik_active = ToggleSwitch(self.tr("Transitional provision active"))
        self.sw_rik_active.setToolTip(self.tr(
            "Enable if this is the first election conference of this type"
            " since the Law came into force — RIK appoints an additional member and deputy."
        ))
        layout.addWidget(self.sw_rik_active)
        return box

    def _build_party_files_group(self) -> QGroupBox:
        box = QGroupBox(self.tr("Party Excel files"))
        layout = QVBoxLayout(box)
        self.sw_combined_name_header = ToggleSwitch(
            self.tr("Merge Име/Презиме into one field")
        )
        self.sw_combined_name_header.setToolTip(self.tr(
            "Matches the official form: the party types a full name into"
            " one \"Име и презиме\" box instead of two separate columns."
            " On import, a 2-word name splits into Име/Презиме"
            " automatically; 3+ words can't be split unambiguously and"
            " are flagged for a manual fix in Корекције instead of being"
            " guessed at. Re-run Phase 1 to apply to new party files."
        ))
        layout.addWidget(self.sw_combined_name_header)
        return box

    def _build_rik_member_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 14, 0, 0)
        outer.setSpacing(10)

        # Template + import row (toggle moved to Tab 1 left column)
        top_row = QHBoxLayout()
        top_row.addStretch()
        btn_template = QPushButton(self.tr("Template ↓"))
        btn_template.setToolTip(self.tr("Download Excel template with all polling stations (pre-filled with current data)"))
        btn_template.clicked.connect(self._rik_export_template)
        top_row.addWidget(btn_template)
        btn_import = QPushButton(self.tr("Import ↑"))
        btn_import.setToolTip(self.tr("Import filled Excel template"))
        btn_import.clicked.connect(self._rik_import_xlsx)
        top_row.addWidget(btn_import)
        outer.addLayout(top_row)

        # Articles label (auto-updated from election types)
        self._rik_articles_label = QLabel()
        self._rik_articles_label.setObjectName("MutedLabel")
        self._rik_articles_label.setWordWrap(True)
        outer.addWidget(self._rik_articles_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        # Scrollable BM cards area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._rik_cards_host = QWidget()
        self._rik_cards_layout = QVBoxLayout(self._rik_cards_host)
        self._rik_cards_layout.setSpacing(8)
        self._rik_cards_layout.setContentsMargins(0, 0, 8, 0)
        scroll.setWidget(self._rik_cards_host)
        outer.addWidget(scroll, stretch=1)
        self._rik_scroll = scroll

        # Update articles label when election types change
        self.state.election_changed.connect(self._refresh_rik_articles_label)

        return page

    @log_timing("SettingsElectionTab._refresh_rik_articles_label")
    def _refresh_rik_articles_label(self) -> None:
        types = self.state.election.election.types
        text = rik_provision_articles(types)
        if text:
            self._rik_articles_label.setText(text)
        else:
            self._rik_articles_label.setText(self.tr(
                "(Legal basis will be shown when you select election types in tab 1)"
            ))

    def _on_rik_toggled(self, checked: bool) -> None:
        self.inner_tabs.setTabVisible(2, checked)

    def _rik_export_template(self) -> None:
        default_path = str(self.state.files_dir("Члан РИК-а") / "rik_clanovi.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save template"), default_path, self.tr("Excel (*.xlsx)")
        )
        if not path:
            return
        stations = list(self.state.oik.polling_stations)
        existing: dict[int, RikBmEntry] = {}
        for bm_num, fields in self._rik_bm_fields.items():
            existing[bm_num] = fields.to_entry()
        try:
            export_rik_template(stations, existing, path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot write template:\n{exc}").format(exc=exc))
            return
        try:
            import os
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _rik_import_xlsx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import template"),
            str(self.state.files_dir("Члан РИК-а")), self.tr("Excel (*.xlsx)")
        )
        if not path:
            return
        try:
            members, errors = import_rik_xlsx(path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("Read error"), self.tr("Cannot read file:\n{exc}").format(exc=exc))
            return
        if errors:
            QMessageBox.warning(
                self, self.tr("Import warnings"),
                self.tr("Some rows were not imported:\n\n") + "\n".join(errors),
            )
        for bm_num, entry in members.items():
            if bm_num in self._rik_bm_fields:
                self._rik_bm_fields[bm_num].load(entry)
        self._mark_dirty()
        QMessageBox.information(
            self, self.tr("Import complete"),
            self.tr("Imported {n} polling stations.").format(n=len(members)),
        )

    def _rebuild_rik_bm_cards(self) -> None:
        """Recreate BM cards to match current OIK polling stations."""
        # Clear
        while self._rik_cards_layout.count():
            item = self._rik_cards_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._rik_bm_fields.clear()

        stations = sorted(
            self.state.oik.polling_stations, key=lambda s: s.bm_number
        )
        for station in stations:
            fields = _RikBmFields(station.bm_number)
            card = self._build_rik_bm_card(station, fields)
            self._rik_cards_layout.addWidget(card)
            self._rik_bm_fields[station.bm_number] = fields
            for ed in fields.all_editors():
                ed.textChanged.connect(self._mark_dirty)

        self._rik_cards_layout.addStretch()

    def _build_rik_bm_card(self, station, fields: _RikBmFields) -> QGroupBox:
        title = f"БМ {station.bm_number}"
        if station.name:
            title += f" — {station.name}"
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        def _person_form(label: str, name_ed, jmbg_ed, addr_ed, phone_ed, email_ed) -> QGroupBox:
            grp = QGroupBox(label)
            form = QFormLayout(grp)
            form.setLabelAlignment(Qt.AlignRight)
            name_row = QHBoxLayout()
            name_row.addWidget(name_ed, stretch=3)
            jmbg_label = QLabel(self.tr("JMBG:"))
            jmbg_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            name_row.addWidget(jmbg_label)
            name_row.addWidget(jmbg_ed, stretch=2)
            form.addRow(self.tr("Name:"), name_row)
            contact_row = QHBoxLayout()
            contact_row.addWidget(addr_ed, stretch=3)
            phone_lbl = QLabel(self.tr("Tel.:"))
            phone_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            contact_row.addWidget(phone_lbl)
            contact_row.addWidget(phone_ed, stretch=2)
            email_lbl = QLabel(self.tr("Email:"))
            email_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            contact_row.addWidget(email_lbl)
            contact_row.addWidget(email_ed, stretch=3)
            form.addRow(self.tr("Location / address:"), contact_row)
            return grp

        layout.addWidget(_person_form(
            self.tr("Member"), fields.m_name, fields.m_jmbg, fields.m_address, fields.m_phone, fields.m_email
        ))
        layout.addWidget(_person_form(
            self.tr("Deputy member"), fields.d_name, fields.d_jmbg, fields.d_address, fields.d_phone, fields.d_email
        ))
        return box

    def _build_parties_group(self) -> CollapsibleSection:
        self._parties_section = CollapsibleSection(
            self.tr("Parliamentary groups"),
            self.tr("abbreviations, full names, e-mail"),
        )

        btn_import_qa = QPushButton(self.tr("Import"))
        btn_import_qa.clicked.connect(self._import_parties_from_excel)
        self._parties_section.add_quick_action(btn_import_qa)

        # Content
        self._parties_rows: list[dict[str, str]] = []

        self.parties_table = SearchableTable(
            [self.tr("Short name"), self.tr("Full name"), self.tr("Email"), self.tr("Phone")],
            placeholder=self.tr("Type short or full name, email, phone…"),
        )
        h = self.parties_table.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 110)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.resizeSection(2, 220)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        h.resizeSection(3, 150)
        self.parties_table.row_activated.connect(self._edit_party_row)

        hint = QLabel(self.tr(
            "Short name (e.g. 'SNS') must match exactly what is in the RIK template."
            " Email and phone are optional — used for sending files to parties after Phase 1."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        btns = QHBoxLayout()
        self.btn_add_party = QPushButton(self.tr("Add party"))
        self.btn_rm_party = QPushButton(self.tr("Remove selected"))
        self.btn_rm_party.setObjectName("DangerButton")
        self.btn_import_parties = QPushButton(self.tr("Import"))
        self.btn_import_parties.setToolTip(self.tr(
            "Imports the 'Short name → Full name' map from a standalone Excel file"
            " (e.g. parties.xlsx)."
        ))
        self.btn_export_parties = QPushButton(self.tr("Export"))
        self.btn_export_parties.setToolTip(self.tr(
            "Exports the current party map to a standalone Excel file for editing or sharing."
        ))
        self.btn_add_party.clicked.connect(self._add_party_row)
        self.btn_rm_party.clicked.connect(self._remove_selected_party)
        self.btn_import_parties.clicked.connect(self._import_parties_from_excel)
        self.btn_export_parties.clicked.connect(self._export_parties_to_excel)
        btns.addWidget(self.btn_add_party)
        btns.addWidget(self.btn_rm_party)
        btns.addWidget(self.btn_import_parties)
        btns.addWidget(self.btn_export_parties)
        btns.addStretch()

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)
        body_vbox.addWidget(hint)
        body_vbox.addWidget(self.parties_table)
        body_vbox.addLayout(btns)
        self._parties_section.set_content(body)
        return self._parties_section

    def _build_quotas_group(self) -> CollapsibleSection:
        self._quotas_section = CollapsibleSection(
            self.tr("Seat quotas per group"),
            self.tr("quota per role"),
        )

        btn_import_qa = QPushButton(self.tr("Import"))
        btn_import_qa.clicked.connect(self._import_quotas_from_excel)
        self._quotas_section.add_quick_action(btn_import_qa)

        hint = QLabel(self.tr(
            "Enter the number of seats each parliamentary group was awarded"
            " per role, per the RIK decision. Used to block over-assigning a"
            " group past its quota in the allocation matrix below."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        totals_hint = QLabel(self.tr(
            "Expected totals for the whole municipality — one President and"
            " one Deputy per polling station, four member/deputy-member"
            " seats per station. The sum of the groups' quotas below should"
            " match this row."
        ))
        totals_hint.setObjectName("MutedLabel")
        totals_hint.setWordWrap(True)

        self.quotas_totals_table = QTableWidget(1, 5)
        self.quotas_totals_table.setHorizontalHeaderLabels([
            self.tr("Municipality"), self.tr("President"), self.tr("Deputy"),
            self.tr("Members + deputies"), self.tr("Total"),
        ])
        self.quotas_totals_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.quotas_totals_table.verticalHeader().setVisible(False)
        # An explicit, generous row height + total-height budget — the
        # previous tight setMaximumHeight(64) squeezed the single data
        # row's visible area down to nothing (header stayed visible, the
        # row itself rendered blank). Same class of bug as the QComboBox/
        # QSpinBox cell clipping fixed earlier; compute a budget that
        # comfortably fits header + one row instead of guessing tight.
        self.quotas_totals_table.verticalHeader().setDefaultSectionSize(32)
        self.quotas_totals_table.setMaximumHeight(96)
        th = self.quotas_totals_table.horizontalHeader()
        # Fixed (not Stretch/Interactive) — Stretch made this single-row
        # table balloon out to fill the whole section width for just one
        # municipality name; a fixed, modest width shrinks its footprint
        # and — matched below in the per-group quota table's own "Група"
        # column — keeps both tables' column grid lines aligned so they
        # read as one continuous table, not two mismatched ones.
        for c, width in ((0, 160), (1, 110), (2, 110), (3, 150), (4, 90)):
            th.setSectionResizeMode(c, QHeaderView.Fixed)
            th.resizeSection(c, width)

        self.quotas_table = QTableWidget(0, 5)
        self.quotas_table.setHorizontalHeaderLabels([
            self.tr("Group"), self.tr("President"), self.tr("Deputy"),
            self.tr("Members + deputies"), self.tr("Total"),
        ])
        self.quotas_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.quotas_table.verticalHeader().setVisible(False)
        h = self.quotas_table.horizontalHeader()
        # "Група" matches the totals table's "Општина" column width (160)
        # so the two stacked tables' grid lines line up as one continuous
        # table. "Чл. + Зам. чл." is the widest label so it gets more
        # room, the others are narrower. Fixed (not Interactive) so an
        # operator can't drag a column wide enough to push the numeric
        # columns out of the visible box behind a horizontal scrollbar.
        for c, width in ((0, 160), (1, 110), (2, 110), (3, 150), (4, 90)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            h.resizeSection(c, width)
        self._quota_row_abbrevs: list[str] = []

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)
        body_vbox.addWidget(totals_hint)
        body_vbox.addWidget(self.quotas_totals_table)
        body_vbox.addWidget(hint)
        body_vbox.addWidget(self.quotas_table)

        quota_btns = QHBoxLayout()
        btn_import_quotas = QPushButton(self.tr("Import"))
        btn_import_quotas.setToolTip(self.tr("Import group quotas from a standalone Excel file."))
        btn_import_quotas.clicked.connect(self._import_quotas_from_excel)
        quota_btns.addWidget(btn_import_quotas)
        btn_export_quotas = QPushButton(self.tr("Export"))
        btn_export_quotas.setToolTip(self.tr("Export the current group quotas to a standalone Excel file."))
        btn_export_quotas.clicked.connect(self._export_quotas_to_excel)
        quota_btns.addWidget(btn_export_quotas)
        quota_btns.addStretch()
        body_vbox.addLayout(quota_btns)

        self._quotas_section.set_content(body)
        self._refresh_quota_totals_row()
        self._refresh_quotas_table()
        return self._quotas_section

    def _expected_bucket_totals(self) -> tuple[int, int, int]:
        """(predsednik, zamenik, clan_i_zamenik) expected totals for the
        whole municipality, derived purely from the BM count — one
        President + one Deputy per station, four member/deputy-member
        seats per station.
        """
        n_bm = len(self.state.oik.polling_stations)
        return n_bm, n_bm, n_bm * 4

    def _refresh_quota_totals_row(self) -> None:
        """Expected role totals for the whole municipality — read-only
        reference so the operator can check the groups' quotas below sum
        to this row.
        """
        predsednik, zamenik, clan_i_zamenik = self._expected_bucket_totals()
        values = [
            self.state.oik.municipality.name,
            str(predsednik), str(zamenik), str(clan_i_zamenik),
            str(predsednik + zamenik + clan_i_zamenik),
        ]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if col > 0:
                item.setTextAlignment(Qt.AlignCenter)
            self.quotas_totals_table.setItem(0, col, item)
        # Expected totals changing (e.g. BM count edited) shifts how much
        # is available/capped per group too.
        self._refresh_quota_available_row()

    def _refresh_quotas_table(self) -> None:
        """Rebuild quota rows from the current declared-parties list.

        Row 0 is a read-only "Available" summary (see
        `_refresh_quota_available_row`); party rows start at row 1.
        Called wherever `_refresh_parties_view()` runs so the quota
        table's row set never drifts from the Групе table (add/remove/
        import all flow through here indirectly).
        """
        abbrevs = [
            r["abbrev"].strip() for r in self._parties_rows
            if r["abbrev"].strip() and r["abbrev"].strip() != "_default"
        ]
        quotas = self.state.election.party_quotas
        self._quota_row_abbrevs = abbrevs
        self.quotas_table.setRowCount(len(abbrevs) + 1)

        avail_label = QTableWidgetItem(self.tr("Available"))
        avail_label.setFlags(avail_label.flags() & ~Qt.ItemIsEditable)
        bold = avail_label.font()
        bold.setBold(True)
        avail_label.setFont(bold)
        self.quotas_table.setItem(0, 0, avail_label)
        for col in (1, 2, 3, 4):
            item = QTableWidgetItem("")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(bold)
            self.quotas_table.setItem(0, col, item)

        self._quota_spinboxes: dict[str, list[QSpinBox]] = {
            "predsednik": [], "zamenik": [], "clan_i_zamenik": [],
        }
        for i, abbrev in enumerate(abbrevs):
            row = i + 1
            q = quotas.get(abbrev, PartyQuota())
            item = QTableWidgetItem(abbrev)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.quotas_table.setItem(row, 0, item)

            sb_pred = _QuotaSpinBox()
            sb_zam = _QuotaSpinBox()
            sb_clan = _QuotaSpinBox()
            for sb in (sb_pred, sb_zam, sb_clan):
                sb.setRange(0, 250)
            lbl_total = QLabel(str(q.predsednik + q.zamenik + q.clan_i_zamenik))
            lbl_total.setAlignment(Qt.AlignCenter)

            def _on_change(_v=None, p=sb_pred, z=sb_zam, c=sb_clan, lbl=lbl_total) -> None:
                lbl.setText(str(p.value() + z.value() + c.value()))
                self._refresh_quota_available_row()

            for sb in (sb_pred, sb_zam, sb_clan):
                sb.valueChanged.connect(_on_change)
                sb.valueChanged.connect(self._mark_dirty)

            self.quotas_table.setCellWidget(row, 1, sb_pred)
            self.quotas_table.setCellWidget(row, 2, sb_zam)
            self.quotas_table.setCellWidget(row, 3, sb_clan)
            self.quotas_table.setCellWidget(row, 4, lbl_total)

            # setValue() AFTER setCellWidget(), not before: a spinbox that
            # gets its value while still unparented doesn't reliably repaint
            # once it lands in the table — the value is genuinely there
            # (confirmed: clicking into a "blank" box reveals the number),
            # it just isn't painted until something forces a repaint, which
            # normally only happens on focus-in. Parenting first means the
            # value is set on a widget that's already part of the visible
            # tree, so the first paint already reflects it. Signals blocked
            # here since this is the initial load, not an operator edit —
            # _import_quotas_from_excel() sets values the normal (unblocked)
            # way, where firing _mark_dirty is exactly what should happen.
            for sb, value in ((sb_pred, q.predsednik), (sb_zam, q.zamenik), (sb_clan, q.clan_i_zamenik)):
                sb.blockSignals(True)
                sb.setValue(value)
                sb.blockSignals(False)

            self._quota_spinboxes["predsednik"].append(sb_pred)
            self._quota_spinboxes["zamenik"].append(sb_zam)
            self._quota_spinboxes["clan_i_zamenik"].append(sb_clan)

        self._refresh_quota_available_row()

    def _refresh_quota_available_row(self) -> None:
        """Row 0's read-only "Available" numbers, and the live cap on how
        high each group's spinbox can go — available can never go
        negative, so once a bucket reaches 0 the remaining spinboxes in
        that column simply refuse further input past their current value.
        Lets an operator entering quotas manually see immediately where
        they've over-allocated relative to the municipality's BM-derived
        totals, without waiting for a save/reload.
        """
        if not hasattr(self, "_quota_spinboxes"):
            return  # called before _refresh_quotas_table has built rows yet
        expected = dict(zip(
            ("predsednik", "zamenik", "clan_i_zamenik"), self._expected_bucket_totals(),
        ))

        available: dict[str, int] = {}
        for bucket, spinboxes in self._quota_spinboxes.items():
            total_expected = expected[bucket]
            current_sum = sum(sb.value() for sb in spinboxes)
            available[bucket] = max(0, total_expected - current_sum)
            for sb in spinboxes:
                others_sum = current_sum - sb.value()
                new_max = max(0, total_expected - others_sum)
                if sb.maximum() != new_max:
                    sb.blockSignals(True)
                    sb.setMaximum(new_max)
                    sb.blockSignals(False)

        col_by_bucket = {"predsednik": 1, "zamenik": 2, "clan_i_zamenik": 3}
        for bucket, col in col_by_bucket.items():
            item = self.quotas_table.item(0, col)
            if item is not None:
                item.setText(str(available[bucket]))
        total_item = self.quotas_table.item(0, 4)
        if total_item is not None:
            total_item.setText(str(sum(available.values())))

    def _collect_quotas(self) -> dict[str, PartyQuota]:
        out: dict[str, PartyQuota] = {}
        for i, abbrev in enumerate(self._quota_row_abbrevs):
            row = i + 1
            sb_pred = self.quotas_table.cellWidget(row, 1)
            sb_zam = self.quotas_table.cellWidget(row, 2)
            sb_clan = self.quotas_table.cellWidget(row, 3)
            if sb_pred is None or sb_zam is None or sb_clan is None:
                continue
            out[abbrev] = PartyQuota(
                predsednik=sb_pred.value(), zamenik=sb_zam.value(), clan_i_zamenik=sb_clan.value(),
            )
        return out

    def _import_quotas_from_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select quotas.xlsx"),
            str(self.state.files_dir("Групе")),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        from pathlib import Path as _Path
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(_Path(path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=_Path(path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return
        quotas, errors = read_quotas_sheet(path)
        if errors:
            self.banner.show_error("\n".join(errors))
            return

        # Quota rows are 1:1 with already-declared groups (Групе table) —
        # unlike parties import, this can't create new rows, only fill in
        # numbers for groups that already have one.
        applied = 0
        for i, abbrev in enumerate(self._quota_row_abbrevs):
            q = quotas.get(abbrev)
            if q is None:
                continue
            row = i + 1
            sb_pred = self.quotas_table.cellWidget(row, 1)
            sb_zam = self.quotas_table.cellWidget(row, 2)
            sb_clan = self.quotas_table.cellWidget(row, 3)
            if sb_pred is None or sb_zam is None or sb_clan is None:
                continue
            sb_pred.setValue(q.predsednik)
            sb_zam.setValue(q.zamenik)
            sb_clan.setValue(q.clan_i_zamenik)
            applied += 1

        skipped = sorted(set(quotas) - set(self._quota_row_abbrevs))
        msg = self.tr("Imported quotas for {n} group(s).").format(n=applied)
        if skipped:
            msg += " " + self.tr("Skipped (not a declared group): {names}").format(
                names=", ".join(skipped)
            )
            self.banner.show_warn(msg)
        else:
            self.banner.show_ok(msg)

    def _export_quotas_to_excel(self) -> None:
        quotas = self._collect_quotas()
        if not quotas:
            self.banner.show_warn(self.tr("No quotas to export."))
            return
        default = str(self.state.files_dir("Групе") / "quotas.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save quotas.xlsx"), default, self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        try:
            build_quotas_workbook(quotas, path)
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        self.banner.show_ok(
            self.tr("Exported quotas for {n} group(s) to {path}").format(n=len(quotas), path=path)
        )

    # ── Responsive layout ──────────────────────────────────

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout(event.size().width())

    def _relayout(self, width: int) -> None:
        target = 2 if width >= _TWO_COL_MIN else 1
        if target == self._current_cols:
            return
        self._current_cols = target
        self._grid.removeWidget(self._left_col)
        self._grid.removeWidget(self._rik_box)
        if target == 2:
            # Single-row grid: _left_col (30%) | _rik_box (70%).
            # No row-spanning, so the two columns are height-independent.
            self._grid.addWidget(self._left_col, 0, 0)
            self._grid.addWidget(self._rik_box,  0, 1)
            self._grid.setColumnStretch(0, 3)
            self._grid.setColumnStretch(1, 7)
            self._grid.setRowStretch(0, 1)
            self._grid.setRowStretch(1, 0)
        else:
            self._grid.addWidget(self._left_col, 0, 0)
            self._grid.addWidget(self._rik_box,  1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
            self._grid.setRowStretch(0, 0)
            self._grid.setRowStretch(1, 1)

    def _recalculate_cutoffs(self) -> None:
        """Auto-update cutoff pickers when the election date changes."""
        d = self.date_picker.date()
        for picker, delta in (
            (self.cutoff_stalni_picker, -15),
            (self.cutoff_prosireni_picker, -10),
            (self.cutoff_posmatraci_picker, -2),
        ):
            picker.blockSignals(True)
            picker.setDate(d.addDays(delta))
            picker.blockSignals(False)
        self._refresh_cutoff_labels()

    def _refresh_cutoff_labels(self) -> None:
        """Update the delta sub-labels to show days-before vs. election date."""
        election = self.date_picker.date()
        for delta_lbl, picker in (
            (self._delta_stalni,    self.cutoff_stalni_picker),
            (self._delta_prosireni, self.cutoff_prosireni_picker),
            (self._delta_posmatraci, self.cutoff_posmatraci_picker),
        ):
            n = abs(election.daysTo(picker.date()))
            delta_lbl.setText(self.tr("{n} days before").format(n=n))

    def _compose_rik_text(self) -> str:
        d = self.date_picker.date()
        date_full = declension.format_serbian_date(d.year(), d.month(), d.day())
        broj = self.ed_rik_broj.text().strip()
        rik_d = self.rik_date_picker.date()
        if not broj or not date_full or not rik_d.isValid():
            return ""
        rik_date_full = declension.format_serbian_date(rik_d.year(), rik_d.month(), rik_d.day())
        rik_date_gen = declension.to_genitive(rik_date_full)
        return (
            f"Одлуком Републичке изборне комисије о утврђивању распореда"
            f" места за предлагање чланова и заменика чланова бирачких"
            f" одбора у сталном саставу за спровођење избора расписаних"
            f" за {date_full} {broj} од {rik_date_gen}"
        )

    # ── Load / save ────────────────────────────────────────

    def _load_from_state(self) -> None:
        # Guard against widget signals flipping dirty=True during refill.
        self._loading = True
        try:
            ec = self.state.election
            parsed = declension.parse_serbian_date(ec.election.dates.date_full)
            self.date_picker.blockSignals(True)
            if parsed is not None:
                y, m, d = parsed
                self.date_picker.setDate(QDate(y, m, d))
            else:
                # Empty / unparseable → snap to earliest legal election date
                # (next Sunday ≥ today + 30 days) so the user starts at a
                # valid default rather than today.
                self.date_picker.setDate(_next_election_sunday())
            self.date_picker.blockSignals(False)

            # Cutoff dates: load stored ISO values; fall back to calculated
            # defaults when the field is absent (e.g. pre-cutoff configs).
            election_qdate = self.date_picker.date()
            for picker, stored, delta in (
                (self.cutoff_stalni_picker,    ec.election.dates.cutoff_stalni,    -15),
                (self.cutoff_prosireni_picker, ec.election.dates.cutoff_prosireni, -10),
                (self.cutoff_posmatraci_picker, ec.election.dates.cutoff_posmatraci, -2),
            ):
                q = _iso_to_qdate(stored) if stored else None
                picker.setDate(q if q is not None else election_qdate.addDays(delta))
            self.ed_rik_broj.setText(ec.election.rik_broj)
            q_rik = _iso_to_qdate(ec.election.rik_date) if ec.election.rik_date else None
            if q_rik is not None:
                self.rik_date_picker.setDate(q_rik)
            # number_prefix + legal_basis are owned by Фаза 3.
            # Authorization fields are owned by IzmeneTab (moved there).
            for key, cb in self._type_checks.items():
                cb.setChecked(key in ec.election.types)
            self._refresh_provincial_visibility()
            self._refresh_level_selector()
            self._parties_rows = []
            for k, v in ec.party_full_names.items():
                contact = ec.party_contact(k)
                self._append_party_row(k, v, contact.email, contact.phone)
            self._refresh_parties_view()
            # Candidacies — load entities + candidates from registry.
            self._entity_rows = [e.to_dict() for e in ec.candidacies.entities]
            self._candidate_rows = [c.to_dict() for c in ec.candidacies.candidates]
            self._refresh_entities_view()
            self._refresh_candidates_view()
            self._refresh_cutoff_labels()
            self._reload_password_field()
            self.sw_combined_name_header.blockSignals(True)
            self.sw_combined_name_header.setChecked(ec.combined_name_header)
            self.sw_combined_name_header.blockSignals(False)
            # ── RIK provision ──
            self._rebuild_rik_bm_cards()
            prov = ec.rik_provision
            self.sw_rik_active.blockSignals(True)
            self.sw_rik_active.setChecked(prov.active)
            self.sw_rik_active.blockSignals(False)
            self.inner_tabs.setTabVisible(2, prov.active)
            for bm_num, fields in self._rik_bm_fields.items():
                entry = prov.members.get(bm_num, RikBmEntry())
                fields.load(entry)
            self._refresh_rik_articles_label()
        finally:
            self._loading = False
            self.dirty = False

    def _reload_password_field(self) -> None:
        self.ed_password.setText(self.state.oik.lock_password)

    def _refresh_provincial_visibility(self) -> None:
        is_vojvodina = self.state.oik.municipality.is_vojvodina
        cb = self._type_checks.get("provincial")
        if cb is None:
            return
        cb.setVisible(is_vojvodina)
        if not is_vojvodina and cb.isChecked():
            cb.setChecked(False)

    def _save_password_field(self) -> None:
        new_pw = self.ed_password.text().strip()
        if new_pw == self.state.oik.lock_password:
            return
        self.state.oik.lock_password = new_pw
        try:
            self.state.save_oik()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save password: {e}").format(e=e))

    def _refresh_parties_view(self) -> None:
        """Push `self._parties_rows` into the SearchableTable view."""
        self.parties_table.set_rows([
            (r["abbrev"], r["full"], r["email"], r["phone"])
            for r in self._parties_rows
        ])
        self._parties_section.set_count(len(self._parties_rows))
        self._refresh_quotas_table()
        # The matrix grid's row/dropdown-item state depends on the
        # declared-parties list too — rebuild it every time _parties_rows
        # changes so adding a party makes the grid appear immediately,
        # without requiring a Save first (_rebuild_matrix_grid reads
        # this same live _parties_rows list, not the last-saved config).
        self._rebuild_matrix_grid()

    def _append_party_row(
        self, abbrev: str, full: str, email: str = "", phone: str = "",
    ) -> None:
        """Add a record to the parent-owned list. Does NOT refresh the
        view — call _refresh_parties_view() after a batch of appends."""
        self._parties_rows.append({
            "abbrev": abbrev, "full": full, "email": email, "phone": phone,
        })

    def _add_party_row(self) -> None:
        """+ Add party — opens an empty edit dialog."""
        dlg = RowEditDialog(
            self.tr("New party"),
            [
                (self.tr("Short name:"), "abbrev", ""),
                (self.tr("Full name:"), "full", ""),
                (self.tr("Email:"), "email", ""),
                (self.tr("Phone:"), "phone", ""),
            ],
            parent=self.window(),
            placeholders={"abbrev": self.tr("e.g. SNS"), "email": "stranka@example.rs"},
            wrap_keys={"full"},
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        if not v["abbrev"]:
            self.banner.show_error(self.tr(
                "Short name is required (e.g. 'SNS'). Party not added."
            ))
            return
        self._parties_rows.append({
            "abbrev": v["abbrev"], "full": v["full"],
            "email": v["email"], "phone": v["phone"],
        })
        self._refresh_parties_view()
        self._mark_dirty()

    def _edit_party_row(self, idx: int) -> None:
        """Open the edit dialog for the party at `idx`. Called by the
        SearchableTable's row_activated signal (double-click)."""
        if not (0 <= idx < len(self._parties_rows)):
            self.banner.show_error(
                self.tr("Cannot find party at position {idx}. Try again.").format(idx=idx)
            )
            return
        cur = self._parties_rows[idx]
        dlg = RowEditDialog(
            self.tr("Edit party {abbrev}").format(abbrev=cur["abbrev"] or "?"),
            [
                (self.tr("Short name:"), "abbrev", cur["abbrev"]),
                (self.tr("Full name:"), "full", cur["full"]),
                (self.tr("Email:"), "email", cur["email"]),
                (self.tr("Phone:"), "phone", cur["phone"]),
            ],
            parent=self.window(),
            wrap_keys={"full"},
        )
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        if not v["abbrev"]:
            self.banner.show_error(self.tr(
                "Short name is required. Change not saved."
            ))
            return
        self._parties_rows[idx] = {
            "abbrev": v["abbrev"], "full": v["full"],
            "email": v["email"], "phone": v["phone"],
        }
        self._refresh_parties_view()
        self._mark_dirty()

    def _remove_selected_party(self) -> None:
        idx = self.parties_table.selected_original_index()
        if idx is None:
            return
        if not (0 <= idx < len(self._parties_rows)):
            return
        del self._parties_rows[idx]
        self._refresh_parties_view()
        self._mark_dirty()

    def _collect_parties(self) -> dict[str, str]:
        """Return only the {abbrev: full_name} mapping — the existing
        save path passes this straight into ElectionConfig.party_full_names.
        """
        parties: dict[str, str] = {}
        for r in self._parties_rows:
            k = r["abbrev"].strip()
            if k:
                parties[k] = r["full"].strip()
        # Defensive: the chief's name lives on OikConstants, not here —
        # guard against a stray manually-typed "_default" abbreviation
        # anyway so it never round-trips back into party_full_names.
        parties.pop("_default", None)
        return parties

    def _collect_party_contacts(self) -> dict:
        """Return {abbrev: PartyContact} for rows where email or phone
        is non-empty. Empty contacts are dropped to keep the on-disk
        JSON tidy (an empty PartyContact would serialize to a noisy
        `{"email": "", "phone": ""}` for every party otherwise)."""
        from biracki_odbor.config.election import PartyContact
        out: dict[str, PartyContact] = {}
        for r in self._parties_rows:
            k = r["abbrev"].strip()
            email = r["email"].strip()
            phone = r["phone"].strip()
            if k and (email or phone):
                out[k] = PartyContact(email=email, phone=phone)
        return out

    def _import_parties_from_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select parties.xlsx"),
            str(self.state.files_dir("Групе")),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        # Same safety pipeline as popunjeni / template imports — every
        # ingress that takes a user-supplied .xlsx runs through it.
        from pathlib import Path as _Path
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(_Path(path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=_Path(path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return
        mapping, contacts, errors = read_parties_sheet(path)
        if errors:
            self.banner.show_error("\n".join(errors))
            return
        if self._parties_rows:
            reply = QMessageBox.question(
                self, self.tr("Replace existing entries"),
                self.tr(
                    "The table already has {n_existing} parties."
                    " {n_new} will be loaded from Excel.\n\n"
                    "Replace existing entries with the new ones?"
                ).format(n_existing=len(self._parties_rows), n_new=len(mapping)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._parties_rows = []
        for abbrev, full in mapping.items():
            c = contacts.get(abbrev, {})
            self._append_party_row(
                abbrev, full, c.get("email", ""), c.get("phone", ""),
            )
        self._refresh_parties_view()
        self._mark_dirty()
        self.banner.show_ok(
            self.tr("Loaded {n} parties. Click 'Save settings' to persist.").format(n=len(mapping))
        )

    def _export_parties_to_excel(self) -> None:
        parties = self._collect_parties()
        if not parties:
            self.banner.show_warn(self.tr("No parties to export."))
            return
        default = str(self.state.files_dir("Групе") / "parties.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save parties.xlsx"), default, self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        try:
            build_parties_workbook(parties, path, contacts=self._collect_party_contacts())
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        self.banner.show_ok(
            self.tr("Exported {n} parties to {path}").format(n=len(parties), path=path)
        )

    # ── Candidacies tab (Phase C) ───────────────────────────────────

    # Human-readable labels for the internal vocabulary keys.
    _LEVEL_LABELS: dict[str, str] = {
        "presidential":  "Presidential",
        "parliamentary": "Parliamentary",
        "provincial":    "Provincial",
        "local":         "Local",
    }
    _TYPE_LABELS: dict[str, str] = {
        "party":             "Political party",
        "coalition":         "Coalition",
        "group_of_citizens": "Group of citizens",
    }

    def _level_label(self, key: str) -> str:
        if key == "presidential":
            return QCoreApplication.translate("ElectionSettingsTab", "Presidential")
        if key == "parliamentary":
            return QCoreApplication.translate("ElectionSettingsTab", "Parliamentary")
        if key == "provincial":
            return QCoreApplication.translate("ElectionSettingsTab", "Provincial")
        if key == "local":
            return QCoreApplication.translate("ElectionSettingsTab", "Local")
        return key

    def _type_label(self, key: str) -> str:
        if key == "party":
            return QCoreApplication.translate("ElectionSettingsTab", "Political party")
        if key == "coalition":
            return QCoreApplication.translate("ElectionSettingsTab", "Coalition")
        if key == "group_of_citizens":
            return QCoreApplication.translate("ElectionSettingsTab", "Group of citizens")
        return key

    def _build_ucesnici_tab(self) -> QWidget:
        """Build the Листе tab: level picker → electoral lists → candidates."""
        host = QWidget()
        vbox = QVBoxLayout(host)
        vbox.setContentsMargins(0, 14, 0, 0)
        vbox.setSpacing(14)

        vbox.addWidget(self._build_level_card())         # fixed-height card
        vbox.addWidget(self._build_entities_card(), 1)   # stretch=1: fills when expanded
        vbox.addWidget(self._build_candidates_card(), 1) # stretch=1: fills when expanded
        vbox.addStretch()                                 # absorbs slack when both collapsed

        # Single-click entity row → filter candidates (card 3).
        self.entities_table.table.itemSelectionChanged.connect(
            self._on_entity_selected,
        )
        return host

    def _build_level_card(self) -> QGroupBox:
        """Card 2: election-level picker that drives the entities filter."""
        box = QGroupBox(self.tr("Election level"))
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        lbl = QLabel(self.tr("Show participants for level:"))
        lbl.setObjectName("MutedLabel")
        row.addWidget(lbl)
        self.level_combo = QComboBox()
        self.level_combo.setMinimumWidth(240)
        row.addWidget(self.level_combo)
        row.addStretch()
        layout.addLayout(row)

        hint = QLabel(self.tr(
            "Options correspond to election types confirmed in step 1."
            " Changing the level filters the lists in step 3."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Populate synchronously now; also re-populates on type-checkbox change.
        self._refresh_level_selector()
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        return box

    def _build_entities_card(self) -> CollapsibleSection:
        """Card 2 in Учесници tab: electoral lists table, filtered by the level combo."""
        self._entities_section = CollapsibleSection(
            self.tr("Electoral lists"),
            self.tr("click a row to filter candidates"),
        )

        btn_import_qa = QPushButton(self.tr("Import"))
        btn_import_qa.clicked.connect(self._import_liste_from_excel)
        self._entities_section.add_quick_action(btn_import_qa)

        self._entity_rows: list[dict] = []
        self.entities_table = SearchableTable(
            [
                self.tr("List ID"), self.tr("Name"), self.tr("Type"), self.tr("Level"),
                self.tr("Ord."), self.tr("Linked to"), self.tr("Email"),
            ],
            placeholder=self.tr("Search by ID, name, type, level or email…"),
        )
        h = self.entities_table.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 130)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.resizeSection(2, 160)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        h.resizeSection(3, 130)
        h.setSectionResizeMode(4, QHeaderView.Interactive)
        h.resizeSection(4, 60)
        h.setSectionResizeMode(5, QHeaderView.Interactive)
        h.resizeSection(5, 130)
        h.setSectionResizeMode(6, QHeaderView.Interactive)
        h.resizeSection(6, 180)
        self.entities_table.row_activated.connect(self._edit_entity_row)

        btns = QHBoxLayout()
        self.btn_add_entity = QPushButton(self.tr("Add list"))
        self.btn_rm_entity = QPushButton(self.tr("Remove selected"))
        self.btn_rm_entity.setObjectName("DangerButton")
        self.btn_import_liste = QPushButton(self.tr("Import"))
        self.btn_import_liste.setToolTip(self.tr("Import lists from a standalone Excel file."))
        self.btn_template_liste = QPushButton(self.tr("Generate template…"))
        self.btn_template_liste.setToolTip(self.tr(
            "Generates an Excel template with correct headers and a fill-in example."
        ))
        self.btn_add_entity.clicked.connect(self._add_entity_row)
        self.btn_rm_entity.clicked.connect(self._remove_selected_entity)
        self.btn_import_liste.clicked.connect(self._import_liste_from_excel)
        self.btn_template_liste.clicked.connect(self._generate_liste_template)
        btns.addWidget(self.btn_add_entity)
        btns.addWidget(self.btn_rm_entity)
        btns.addWidget(self.btn_import_liste)
        btns.addWidget(self.btn_template_liste)
        btns.addStretch()

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)
        body_vbox.addWidget(self.entities_table, stretch=1)
        body_vbox.addLayout(btns)
        self._entities_section.set_content(body)
        return self._entities_section

    def _build_candidates_card(self) -> CollapsibleSection:
        """Card 3 in Учесници tab: candidates table, scoped to the selected entity."""
        self._candidates_section = CollapsibleSection(
            self.tr("Candidates"),
            self.tr("filtered by selected list"),
        )

        btn_import_qa = QPushButton(self.tr("Import"))
        btn_import_qa.clicked.connect(self._import_kandidati_from_excel)
        self._candidates_section.add_quick_action(btn_import_qa)

        self._candidate_rows: list[dict] = []
        self.candidates_table = SearchableTable(
            [self.tr("Name"), self.tr("JMBG"), self.tr("List ID")],
            placeholder=self.tr("Search by name, JMBG or list…"),
        )
        ch = self.candidates_table.table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.Interactive)
        ch.resizeSection(1, 140)
        ch.setSectionResizeMode(2, QHeaderView.Interactive)
        ch.resizeSection(2, 140)
        self.candidates_table.row_activated.connect(self._edit_candidate_row)

        btns = QHBoxLayout()
        self.btn_add_candidate = QPushButton(self.tr("Add candidate"))
        self.btn_rm_candidate = QPushButton(self.tr("Remove selected"))
        self.btn_rm_candidate.setObjectName("DangerButton")
        self.btn_import_kandidati = QPushButton(self.tr("Import"))
        self.btn_import_kandidati.setToolTip(self.tr("Import candidates from a standalone Excel file."))
        self.btn_export_kandidati = QPushButton(self.tr("Export"))
        self.btn_export_kandidati.setToolTip(self.tr("Export the current candidate list to a standalone Excel file."))
        self.btn_add_candidate.clicked.connect(self._add_candidate_row)
        self.btn_rm_candidate.clicked.connect(self._remove_selected_candidate)
        self.btn_import_kandidati.clicked.connect(self._import_kandidati_from_excel)
        self.btn_export_kandidati.clicked.connect(self._export_kandidati_to_excel)
        btns.addWidget(self.btn_add_candidate)
        btns.addWidget(self.btn_rm_candidate)
        btns.addWidget(self.btn_import_kandidati)
        btns.addWidget(self.btn_export_kandidati)
        btns.addStretch()

        body = QWidget()
        body_vbox = QVBoxLayout(body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(8)
        body_vbox.addWidget(self.candidates_table, stretch=1)
        body_vbox.addLayout(btns)
        self._candidates_section.set_content(body)
        return self._candidates_section

    # ── Level / entity cascade ──────────────────────────────────────

    def _refresh_level_selector(self, *_args) -> None:
        """Repopulate level_combo from the checked type checkboxes (card 1).

        Called on construction, on every type-checkbox toggle, and from
        _load_from_state. Guards against being called before level_combo
        is built (construction order: _build_types_group runs before
        _build_level_card, so the type checks always exist, but the
        combo is only created once _build_level_card runs).
        """
        if not hasattr(self, "level_combo"):
            return
        prev = self.level_combo.currentData()
        self.level_combo.blockSignals(True)
        self.level_combo.clear()
        self.level_combo.addItem(self.tr("All levels"), "")
        for key in LEVEL_KEYS:
            cb = self._type_checks.get(key)
            if cb is not None and cb.isChecked():
                self.level_combo.addItem(self._level_label(key), key)
        # Restore previous selection when it's still present.
        restored = False
        for i in range(self.level_combo.count()):
            if self.level_combo.itemData(i) == prev:
                self.level_combo.setCurrentIndex(i)
                restored = True
                break
        if not restored:
            self.level_combo.setCurrentIndex(0)
        self.level_combo.blockSignals(False)
        # Propagate — may have unchecked the active level.
        self._on_level_changed()

    def _on_level_changed(self, *_args) -> None:
        """Update entity level filter and refresh cards 3 + 4."""
        if not hasattr(self, "level_combo") or not hasattr(self, "entities_table"):
            return
        self._entity_level_filter = self.level_combo.currentData() or ""
        self._entity_filter = ""
        self._refresh_entities_view()
        self._refresh_candidates_view()

    def _on_entity_selected(self) -> None:
        """Update candidates filter from the selected entity row (card 3 → 4)."""
        idx = self.entities_table.selected_original_index()
        if idx is None or not (0 <= idx < len(self._visible_entity_rows)):
            self._entity_filter = ""
        else:
            self._entity_filter = self._visible_entity_rows[idx].get("entity_id", "")
        self._refresh_candidates_view()

    # ── Entities helpers ────────────────────────────────────────────

    def _entity_row_display(self, r: dict) -> tuple:
        level_lbl = self._level_label(r.get("level", ""))
        type_lbl = self._type_label(r.get("entity_type", ""))
        return (
            r.get("entity_id", ""),
            r.get("name", ""),
            type_lbl,
            level_lbl,
            str(r.get("submission_order", "")),
            r.get("linked_to_entity_id", ""),
            r.get("email", ""),
        )

    def _refresh_entities_view(self) -> None:
        self._visible_entity_rows = [
            r for r in self._entity_rows
            if not self._entity_level_filter
            or r.get("level", "") == self._entity_level_filter
        ]
        self.entities_table.set_rows([
            self._entity_row_display(r) for r in self._visible_entity_rows
        ])
        self._entities_section.set_count(len(self._visible_entity_rows))

    def _entity_dialog(self, title: str, initial: dict | None = None) -> dict | None:
        """Open add/edit dialog for an entity. Returns filled dict or None."""
        d = initial or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(420)
        form = QFormLayout(dlg)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 12)

        ed_id = QLineEdit(d.get("entity_id", ""))
        ed_id.setPlaceholderText(self.tr("e.g. sns-parliamentary"))
        form.addRow(self.tr("List ID:"), ed_id)

        # SingleLineEdit(multiline=True) — unlike party full names
        # (SingleLineEdit(wrap=True), which only visually wraps and
        # otherwise behaves like a single value), election-list names
        # can carry a genuinely meaningful embedded line break — e.g. a
        # coalition's official multi-line layout, copied verbatim. This
        # mode keeps real Enter/paste newlines instead of collapsing
        # them, so what the operator sees while typing is what ends up
        # in Решења/Измене (see core/phase3_docx.py's _add_run_lines,
        # which renders those newlines as real Word line breaks).
        ed_name = SingleLineEdit(d.get("name", ""), multiline=True)
        ed_name.setPlaceholderText(self.tr("Full list name"))
        form.addRow(self.tr("Name:"), ed_name)

        cb_type = QComboBox()
        for key in ENTITY_TYPES:
            cb_type.addItem(self._type_label(key), key)
        cur_type = d.get("entity_type", ENTITY_TYPES[0])
        idx = ENTITY_TYPES.index(cur_type) if cur_type in ENTITY_TYPES else 0
        cb_type.setCurrentIndex(idx)
        form.addRow(self.tr("Type:"), cb_type)

        cb_level = QComboBox()
        active_levels = [k for k in LEVEL_KEYS if self._type_checks.get(k) is not None and self._type_checks[k].isChecked()]
        for key in active_levels:
            cb_level.addItem(self._level_label(key), key)
        cur_level = d.get("level", active_levels[-1] if active_levels else "")
        lidx = active_levels.index(cur_level) if cur_level in active_levels else 0
        cb_level.setCurrentIndex(lidx)
        form.addRow(self.tr("Level:"), cb_level)

        ed_order = QLineEdit(str(d.get("submission_order", "")))
        ed_order.setPlaceholderText(self.tr("Ordinal number on the ballot (e.g. 3)"))
        ed_order.setValidator(int_validator(min_value=0, max_value=9999))
        form.addRow(self.tr("Ordinal no.:"), ed_order)

        # Populate link dropdown from current entity IDs (excluding self).
        own_id = d.get("entity_id", "")
        ed_link = QComboBox()
        ed_link.addItem(self.tr("(none — independent)"), "")
        for r in self._entity_rows:
            rid = r.get("entity_id", "")
            if rid and rid != own_id:
                ed_link.addItem(rid, rid)
        cur_link = d.get("linked_to_entity_id", "")
        link_idx = next(
            (i for i in range(ed_link.count()) if ed_link.itemData(i) == cur_link),
            0,
        )
        ed_link.setCurrentIndex(link_idx)
        form.addRow(self.tr("Linked to:"), ed_link)

        # This list's own address book entry — kept separate from
        # ElectionConfig.party_contacts (стални RIK parties) so a
        # прошиени list and a RIK party can never be emailed using each
        # other's saved address by accident. Used by Phase 1 → Send.
        ed_email = QLineEdit(d.get("email", ""))
        ed_email.setPlaceholderText("lista@example.rs")
        form.addRow(self.tr("Email:"), ed_email)

        ed_phone = QLineEdit(d.get("phone", ""))
        form.addRow(self.tr("Phone:"), ed_phone)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Прихвати")
        btns.button(QDialogButtonBox.Cancel).setText("Откажи")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.Accepted:
            return None

        try:
            order = int(ed_order.text().strip())
        except ValueError:
            order = 0

        return {
            "entity_id": ed_id.text().strip(),
            "name": ed_name.text().strip(),
            "entity_type": cb_type.currentData(),
            "level": cb_level.currentData(),
            "submission_order": order,
            "linked_to_entity_id": ed_link.currentData() or "",
            "email": ed_email.text().strip(),
            "phone": phone_normalize(ed_phone.text()),
        }

    def _add_entity_row(self) -> None:
        pre = {"level": self._entity_level_filter} if self._entity_level_filter else None
        values = self._entity_dialog(self.tr("New list"), initial=pre)
        if not values or not values["entity_id"]:
            return
        # Duplicate ID guard.
        if any(r["entity_id"] == values["entity_id"] for r in self._entity_rows):
            QMessageBox.warning(
                self, self.tr("Existing ID"),
                self.tr("A list with ID '{eid}' already exists."
                        " Edit the existing one or use a different ID.").format(
                    eid=values["entity_id"]
                ),
            )
            return
        self._entity_rows.append(values)
        self._refresh_entities_view()
        self._mark_dirty()

    def _edit_entity_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._visible_entity_rows)):
            return
        cur = self._visible_entity_rows[idx]
        eid_label = cur.get("entity_id", "?")
        values = self._entity_dialog(
            self.tr("Edit list {eid}").format(eid=eid_label), initial=cur,
        )
        if not values or not values["entity_id"]:
            return
        # Locate and update in the full (unfiltered) list by entity_id.
        global_idx = next(
            (i for i, r in enumerate(self._entity_rows)
             if r.get("entity_id") == cur.get("entity_id")),
            None,
        )
        if global_idx is not None:
            self._entity_rows[global_idx] = values
        self._refresh_entities_view()
        self._mark_dirty()

    def _remove_selected_entity(self) -> None:
        idx = self.entities_table.selected_original_index()
        if idx is None or not (0 <= idx < len(self._visible_entity_rows)):
            return
        eid = self._visible_entity_rows[idx].get("entity_id", "")
        linked_cands = [
            r for r in self._candidate_rows
            if r.get("endorsed_by_entity_id") == eid
        ]
        if linked_cands:
            reply = QMessageBox.question(
                self, self.tr("Candidates exist"),
                self.tr(
                    "List '{eid}' is the proposer for {n} candidate(s)."
                    " Remove both the list and linked candidates?"
                ).format(eid=eid, n=len(linked_cands)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self._candidate_rows = [
                r for r in self._candidate_rows
                if r.get("endorsed_by_entity_id") != eid
            ]
            self._refresh_candidates_view()
        self._entity_rows = [
            r for r in self._entity_rows if r.get("entity_id") != eid
        ]
        if self._entity_filter == eid:
            self._entity_filter = ""
        self._refresh_entities_view()
        self._mark_dirty()

    # ── Candidates helpers ──────────────────────────────────────────

    def _refresh_candidates_view(self) -> None:
        self._visible_candidate_rows = [
            r for r in self._candidate_rows
            if not self._entity_filter
            or r.get("endorsed_by_entity_id", "") == self._entity_filter
        ]
        self.candidates_table.set_rows([
            (r.get("name", ""), r.get("jmbg", ""), r.get("endorsed_by_entity_id", ""))
            for r in self._visible_candidate_rows
        ])
        self._candidates_section.set_count(len(self._visible_candidate_rows))

    def _candidate_dialog(self, title: str, initial: dict | None = None) -> dict | None:
        """Open add/edit dialog for a candidate."""
        d = initial or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 12)

        ed_name = QLineEdit(d.get("name", ""))
        ed_name.setPlaceholderText(self.tr("Name of candidate"))
        form.addRow(self.tr("Name:"), ed_name)

        ed_jmbg = QLineEdit(d.get("jmbg", ""))
        ed_jmbg.setPlaceholderText(self.tr("13 digits"))
        ed_jmbg.setValidator(jmbg_validator())
        ed_jmbg.setMaxLength(13)
        form.addRow(self.tr("JMBG:"), ed_jmbg)

        cb_entity = QComboBox()
        cb_entity.addItem(self.tr("(select list)"), "")
        for r in self._entity_rows:
            rid = r.get("entity_id", "")
            rname = r.get("name", "")
            if rid:
                cb_entity.addItem(f"{rid} — {rname}", rid)
        cur_ent = d.get("endorsed_by_entity_id", "")
        ent_idx = next(
            (i for i in range(cb_entity.count()) if cb_entity.itemData(i) == cur_ent),
            0,
        )
        cb_entity.setCurrentIndex(ent_idx)
        form.addRow(self.tr("Proposer:"), cb_entity)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Прихвати")
        btns.button(QDialogButtonBox.Cancel).setText("Откажи")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.Accepted:
            return None
        return {
            "name": ed_name.text().strip(),
            "jmbg": ed_jmbg.text().strip(),
            "endorsed_by_entity_id": cb_entity.currentData() or "",
        }

    def _add_candidate_row(self) -> None:
        values = self._candidate_dialog(self.tr("New candidate"))
        if not values or not values["name"]:
            return
        self._candidate_rows.append(values)
        self._refresh_candidates_view()
        self._mark_dirty()

    def _edit_candidate_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._visible_candidate_rows)):
            return
        cur = self._visible_candidate_rows[idx]
        cand_label = cur.get("name", "?")
        values = self._candidate_dialog(
            self.tr("Edit candidate {name}").format(name=cand_label), initial=cur,
        )
        if not values or not values["name"]:
            return
        # Locate in the full list by (name, jmbg, entity_id) identity.
        global_idx = next(
            (i for i, r in enumerate(self._candidate_rows)
             if r.get("name") == cur.get("name")
             and r.get("jmbg") == cur.get("jmbg")
             and r.get("endorsed_by_entity_id") == cur.get("endorsed_by_entity_id")),
            None,
        )
        if global_idx is not None:
            self._candidate_rows[global_idx] = values
        self._refresh_candidates_view()
        self._mark_dirty()

    def _remove_selected_candidate(self) -> None:
        idx = self.candidates_table.selected_original_index()
        if idx is None or not (0 <= idx < len(self._visible_candidate_rows)):
            return
        cur = self._visible_candidate_rows[idx]
        self._candidate_rows = [
            r for r in self._candidate_rows
            if not (r.get("name") == cur.get("name")
                    and r.get("jmbg") == cur.get("jmbg")
                    and r.get("endorsed_by_entity_id") == cur.get("endorsed_by_entity_id"))
        ]
        self._refresh_candidates_view()
        self._mark_dirty()

    def _collect_candidacies(self) -> CandidaciesRegistry:
        """Build a CandidaciesRegistry from the current UI state."""
        return CandidaciesRegistry(
            entities=[
                Entity(
                    entity_id=r.get("entity_id", ""),
                    name=r.get("name", ""),
                    entity_type=r.get("entity_type", "party"),
                    level=r.get("level", "local"),
                    submission_order=int(r.get("submission_order") or 0),
                    linked_to_entity_id=r.get("linked_to_entity_id", ""),
                    email=r.get("email", ""),
                    phone=r.get("phone", ""),
                )
                for r in self._entity_rows
                if r.get("entity_id")
            ],
            candidates=[
                Candidate(
                    name=r.get("name", ""),
                    jmbg=r.get("jmbg", ""),
                    endorsed_by_entity_id=r.get("endorsed_by_entity_id", ""),
                )
                for r in self._candidate_rows
                if r.get("name")
            ],
        )

    # ── Candidacies Excel I/O ───────────────────────────────────────

    def _import_liste_from_excel(self) -> None:
        """Import electoral lists (entities) from any Excel sheet.

        Reads the first sheet of the chosen file using the lenient
        read_entities_sheet reader — only 'Назив' column is required.
        Offers merge (append, skip duplicate IDs) or full replace.
        Candidates are never touched.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import lists from Excel"),
            str(self.state.files_dir("Листе")),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        from pathlib import Path as _Path
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(_Path(path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=_Path(path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return

        new_entities, errors = read_entities_sheet(
            path, default_level=self._entity_level_filter,
        )
        if not new_entities and errors:
            self.banner.show_error("\n".join(errors))
            return
        if errors:
            QMessageBox.warning(
                self, self.tr("Import warnings"),
                self.tr("Loaded with the following warnings:\n\n") + "\n".join(errors),
            )

        if self._entity_rows:
            dlg = QMessageBox(self)
            dlg.setWindowTitle(self.tr("Existing lists"))
            dlg.setText(
                self.tr("Currently {n_existing} list(s) exist.\n{n_new} list(s) will be loaded from Excel.").format(
                    n_existing=len(self._entity_rows), n_new=len(new_entities)
                )
            )
            dlg.setInformativeText(self.tr(
                "Add new (duplicates by ID are skipped) or replace all?"
            ))
            btn_merge   = dlg.addButton(self.tr("Add new"), QMessageBox.YesRole)
            btn_replace = dlg.addButton(self.tr("Replace all"), QMessageBox.DestructiveRole)
            dlg.addButton(self.tr("Cancel"), QMessageBox.RejectRole)
            dlg.exec()
            clicked = dlg.clickedButton()
            if clicked is btn_merge:
                # Merge: append rows whose entity_id is not already present.
                existing_ids = {r.get("entity_id", "") for r in self._entity_rows}
                added = 0
                for e in new_entities:
                    if e.entity_id not in existing_ids:
                        self._entity_rows.append(e.to_dict())
                        existing_ids.add(e.entity_id)
                        added += 1
                skipped = len(new_entities) - added
                msg = self.tr("Added {n} list(s).").format(n=added)
                if skipped:
                    msg += " " + self.tr("Skipped {n} duplicate(s) by ID.").format(n=skipped)
            elif clicked is btn_replace:
                # Replace.
                self._entity_rows = [e.to_dict() for e in new_entities]
                msg = self.tr("Replaced — loaded {n} list(s).").format(n=len(self._entity_rows))
            else:
                return
        else:
            self._entity_rows = [e.to_dict() for e in new_entities]
            msg = self.tr("Loaded {n} list(s).").format(n=len(self._entity_rows))

        self._refresh_entities_view()
        self._mark_dirty()
        self.banner.show_ok(msg + " " + self.tr("Click 'Save settings' to persist."))

    def _generate_liste_template(self) -> None:
        default = str(self.state.files_dir("Листе") / "liste_sablon.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save lists template"), default, self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        active_levels = [
            k for k in LEVEL_KEYS
            if self._type_checks.get(k) is not None and self._type_checks[k].isChecked()
        ]
        try:
            build_entities_template(
                path,
                registry=self._collect_candidacies(),
                available_levels=active_levels or None,
                show_linked_column=len(active_levels) > 1,
            )
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save template: {e}").format(e=e))
            return
        self.banner.show_ok(self.tr("Template saved: {path}").format(path=path))
        try:
            import os as _os
            _os.startfile(path)
        except Exception:  # noqa: BLE001
            pass

    def _import_kandidati_from_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import candidacies from Excel"),
            str(self.state.files_dir("Листе")),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        from pathlib import Path as _Path
        from biracki_odbor.core import popunjeni_io
        from biracki_odbor.validation.reports import message as _msg
        safety = popunjeni_io.check_file_safety(_Path(path))
        if not safety.ok:
            QMessageBox.warning(
                self, self.tr("Invalid file"),
                _msg(safety.code, file=_Path(path).name)
                + (f"\n\nDetail: {safety.detail}" if safety.detail else ""),
            )
            return
        registry, errors = read_candidacies_workbook(path)
        if errors:
            QMessageBox.warning(
                self, self.tr("Import warnings"),
                self.tr("Loaded with the following warnings:\n\n") + "\n".join(errors),
            )

        if self._entity_rows or self._candidate_rows:
            # Field report: this was Replace-or-Cancel only, so importing
            # a second individual list's file (its own list + candidates,
            # generated per the realistic "one file per list" workflow)
            # wiped out whatever had already been imported -- only the
            # last file survived. Offer the same Add-new/Replace-all
            # choice the entities-only "Увези листе" import already has.
            dlg = QMessageBox(self)
            dlg.setWindowTitle(self.tr("Existing entries"))
            dlg.setText(
                self.tr(
                    "Currently {n_e_existing} list(s) and {n_c_existing} candidate(s) exist.\n"
                    "{n_e} list(s) and {n_c} candidate(s) will be loaded from Excel."
                ).format(
                    n_e_existing=len(self._entity_rows), n_c_existing=len(self._candidate_rows),
                    n_e=len(registry.entities), n_c=len(registry.candidates),
                )
            )
            dlg.setInformativeText(self.tr(
                "Add new (duplicates by ID/JMBG are skipped) or replace all?"
            ))
            btn_merge = dlg.addButton(self.tr("Add new"), QMessageBox.YesRole)
            btn_replace = dlg.addButton(self.tr("Replace all"), QMessageBox.DestructiveRole)
            dlg.addButton(self.tr("Cancel"), QMessageBox.RejectRole)
            dlg.exec()
            clicked = dlg.clickedButton()
            if clicked is btn_merge:
                existing_entity_ids = {r.get("entity_id", "") for r in self._entity_rows}
                added_e = 0
                for e in registry.entities:
                    if e.entity_id not in existing_entity_ids:
                        self._entity_rows.append(e.to_dict())
                        existing_entity_ids.add(e.entity_id)
                        added_e += 1
                existing_jmbgs = {r.get("jmbg", "") for r in self._candidate_rows}
                added_c = 0
                for c in registry.candidates:
                    if not c.jmbg or c.jmbg not in existing_jmbgs:
                        self._candidate_rows.append(c.to_dict())
                        existing_jmbgs.add(c.jmbg)
                        added_c += 1
                msg = self.tr("Added {n_e} list(s) and {n_c} candidate(s).").format(
                    n_e=added_e, n_c=added_c,
                )
            elif clicked is btn_replace:
                self._entity_rows = [e.to_dict() for e in registry.entities]
                self._candidate_rows = [c.to_dict() for c in registry.candidates]
                msg = self.tr("Replaced — loaded {n_e} list(s) and {n_c} candidate(s).").format(
                    n_e=len(self._entity_rows), n_c=len(self._candidate_rows),
                )
            else:
                return
        else:
            self._entity_rows = [e.to_dict() for e in registry.entities]
            self._candidate_rows = [c.to_dict() for c in registry.candidates]
            msg = self.tr("Loaded {n_e} list(s) and {n_c} candidate(s).").format(
                n_e=len(self._entity_rows), n_c=len(self._candidate_rows),
            )

        self._refresh_entities_view()
        self._refresh_candidates_view()
        self._mark_dirty()
        self.banner.show_ok(msg)

    def _export_kandidati_to_excel(self) -> None:
        registry = self._collect_candidacies()
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export candidacies to Excel"),
            str(self.state.files_dir("Листе") / "kandidati.xlsx"),
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        try:
            build_candidacies_workbook(registry, path)
        except Exception as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        n_e = len(registry.entities)
        n_c = len(registry.candidates)
        self.banner.show_ok(
            self.tr("Exported {n_e} list(s) and {n_c} candidate(s) to {path}").format(
                n_e=n_e, n_c=n_c, path=path
            )
        )

    def _build_election(self) -> ElectionConfig:
        types_keys = [k for k in declension.TYPE_KEYS if self._type_checks[k].isChecked()]
        parties = self._collect_parties()
        contacts = self._collect_party_contacts()
        # Preserve session_date, session_number, subbroj_* — all owned
        # by Phase 3. Same for document.number_prefix + legal_basis —
        # Phase 3 saves them directly, this builder must not blank them.
        old = self.state.election.election.dates
        old_doc = self.state.election.document
        d = self.date_picker.date()
        date_full = declension.format_serbian_date(d.year(), d.month(), d.day())
        return ElectionConfig(
            election=ElectionInfo(
                dates=ElectionDates(
                    date_full=date_full,
                    session_date=old.session_date,
                    session_number=old.session_number,
                    session_date_prosireni=old.session_date_prosireni,
                    session_number_prosireni=old.session_number_prosireni,
                    subbroj_start=old.subbroj_start,
                    subbroj_separator=old.subbroj_separator,
                    subbroj_start_prosireni=old.subbroj_start_prosireni,
                    cutoff_stalni=_qdate_to_iso(self.cutoff_stalni_picker.date()),
                    cutoff_prosireni=_qdate_to_iso(self.cutoff_prosireni_picker.date()),
                    cutoff_posmatraci=_qdate_to_iso(self.cutoff_posmatraci_picker.date()),
                ),
                types=types_keys,
                rik_decision=self._compose_rik_text() or self.state.election.election.rik_decision,
                rik_broj=self.ed_rik_broj.text().strip(),
                rik_date=_qdate_to_iso(self.rik_date_picker.date()),
            ),
            document=DocumentInfo(
                number_prefix=old_doc.number_prefix,
                number_prefix_prosireni=old_doc.number_prefix_prosireni,
                legal_basis=old_doc.legal_basis,
                legal_basis_prosireni=old_doc.legal_basis_prosireni,
                # Authorization fields: UI lives in IzmeneTab, but the
                # setting applies to every resenje type — preserve as-is.
                authorization_number=old_doc.authorization_number,
                authorization_date=old_doc.authorization_date,
                authorized_name=old_doc.authorized_name,
                authorized_role=old_doc.authorized_role,
                izmena_legal_basis_stalni=old_doc.izmena_legal_basis_stalni,
                izmena_legal_basis_prosireni=old_doc.izmena_legal_basis_prosireni,
                use_authorization=old_doc.use_authorization,
            ),
            party_full_names=parties,
            party_contacts=contacts,
            party_quotas=self._collect_quotas(),
            # Preserve the existing election UUID. Without this, every
            # Election Settings save would blank the field and election.save
            # would lazily regenerate a new UUID — invalidating popunjeni
            # cache and Phase 1 markers across sessions. (Found in the
            # 2026-05-26 field log where every session showed an
            # election_uuid mismatch on cache load.)
            election_uuid=self.state.election.election_uuid,
            # Candidacies — built from the tab's current UI state.
            candidacies=self._collect_candidacies(),
            combined_name_header=self.sw_combined_name_header.isChecked(),
            # RIK provision
            rik_provision=RikProvision(
                active=self.sw_rik_active.isChecked(),
                members={
                    bm_num: entry
                    for bm_num, fields in self._rik_bm_fields.items()
                    for entry in [fields.to_entry()]
                    if not entry.member.is_empty or not entry.deputy.is_empty
                },
            ),
        )

    def _save(self) -> None:
        new_ec = self._build_election()
        errs = new_ec.validate()
        if errs:
            self.banner.show_error(
                self.tr("Configuration is incomplete:\n  • ") + "\n  • ".join(errs)
            )
            return
        self.state._election = new_ec  # noqa: SLF001 — by design
        try:
            self.state.save_election()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {e}").format(e=e))
            return
        self.dirty = False
        self.banner.show_ok(self.tr("Election configuration saved."))
        # Persist the matrix grid's current edits too — this used to be a
        # separate "Сачувај матрицу" action only, easy to forget and
        # silently lose grid assignments when the operator only clicked
        # the main Save button. _save_matrix() also rebuilds the grid
        # (via the template_changed signal it triggers), picking up any
        # parties/quotas that just changed.
        self._save_matrix()

    def _on_new_cycle(self) -> None:
        """Backup current cycle, reset all election-cycle settings to a
        blank slate, assign a new UUID, clear all output dirs.

        OIK/municipality identity (config/oik.py — name, address, seal,
        nacelnik_full_name, etc.) is NOT touched here; it doesn't change
        between cycles. Everything in ElectionConfig does (per that
        module's own docstring: "Changes every election cycle") — dates,
        party list + quotas + contacts, candidacies, RIK provision —
        plus the OIK lock password specifically, which the operator
        asked to also reset so a new cycle doesn't silently inherit the
        old one's password.
        """
        import uuid

        ans = QMessageBox.question(
            self,
            self.tr("New election cycle"),
            self.tr(
                "This will:\n"
                "  1. Save a backup of the current cycle\n"
                "  2. Delete all output files (parties, submitted, summary tables, decisions)\n"
                "  3. Reset election settings (dates, parties, candidacies,\n"
                "     RIK provision, lock password) to a blank slate\n"
                "  4. Assign a new cycle identifier\n\n"
                "OIK/municipality identity is kept. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if ans != QMessageBox.Yes:
            return

        from biracki_odbor.gui.dialogs.backup_flow import run_backup_flow
        status = run_backup_flow(self)
        if status is None:
            return  # operator cancelled backup — do not proceed

        from biracki_odbor.core.workflow import PROSIRENI_SPEC

        def _rmglob(directory, pattern: str) -> None:
            if directory.exists():
                for f in directory.glob(pattern):
                    try:
                        f.unlink()
                    except OSError:
                        pass

        # Clear stalni outputs
        _rmglob(app_paths.stranke_dir(), "*.xlsx")
        _rmglob(app_paths.popunjeni_dir(), "*.xlsx")
        master = app_paths.master_path()
        if master.exists():
            try:
                master.unlink()
            except OSError:
                pass
        _rmglob(app_paths.resenja_dir(), "БМ_*.docx")
        # The chief's takeover template is per-cycle output too — left
        # alone it would silently carry an old cycle's empty-slot list
        # into the new one (field report: "old nacelnik exported table
        # was not removed/cleared").
        nacelnik_tpl = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        if nacelnik_tpl.exists():
            try:
                nacelnik_tpl.unlink()
            except OSError:
                pass

        # Clear prosireni outputs
        _rmglob(app_paths.stranke_dir_for(PROSIRENI_SPEC), "*.xlsx")
        _rmglob(app_paths.popunjeni_dir_for(PROSIRENI_SPEC), "*.xlsx")
        master_p = app_paths.master_path_for(PROSIRENI_SPEC)
        if master_p.exists():
            try:
                master_p.unlink()
            except OSError:
                pass
        _rmglob(app_paths.resenja_dir_for(PROSIRENI_SPEC), "*.docx")

        # Clear the Шаблон за расподелу seed template's allocations too —
        # they're the previous cycle's party assignments, election-cycle
        # data same as everything else reset here. Left alone, re-adding
        # a party with the same abbreviation later would resurface these
        # as "stale" (red) entries in the matrix grid (field report: "the
        # matrix shows the old election cycle data as red"). Overwrite in
        # place — same path, current polling stations, no allocations —
        # rather than deleting, so the path pointer/other sheets survive.
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            tpl_path = self.state.template_path()
        except IntegrityMismatchError:
            # About to overwrite it wholesale anyway — a stale integrity
            # record on the file we're blanking isn't worth blocking the
            # cycle reset over. Treat like "no template" for this step.
            tpl_path = None
        if tpl_path is not None and Path(tpl_path).exists():
            try:
                build_blank_template(
                    tpl_path, stations=list(self.state.oik.polling_stations),
                )
                from biracki_odbor.core import file_integrity
                file_integrity.record_verified(tpl_path)
            except OSError:
                pass

        # Replace the whole election config with a blank slate — every
        # field on it is election-cycle-specific (see ElectionConfig's
        # own docstring). A fresh UUID also invalidates generation_log
        # and popunjeni_cache (both are UUID-keyed; mismatched UUID →
        # fresh state on next load).
        from biracki_odbor.config.election import ElectionConfig

        new_ec = ElectionConfig()
        new_ec.election_uuid = uuid.uuid4().hex
        self.state._election = new_ec  # noqa: SLF001 — by design, see _save()
        try:
            self.state.save_election()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save reset settings: {e}").format(e=e))
            return

        # Reset the lock password back to the shared default.
        from biracki_odbor.config.oik import DEFAULT_LOCK_PASSWORD

        self.state.oik.lock_password = DEFAULT_LOCK_PASSWORD
        try:
            self.state.save_oik()
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot reset password: {e}").format(e=e))
            return

        # Reload the (now UUID-mismatched → fresh) generation log and broadcast.
        self.state.reload_generation_log()

        # Refresh this tab's own form — election_changed isn't wired to a
        # full reload here (only a couple of narrow label refreshers are),
        # so without this the fields would keep showing the old cycle's
        # values even though the underlying data is already blank.
        self._load_from_state()

        self.banner.show_ok(
            self.tr("New election cycle started. Backup: {status}").format(status=status)
        )

    # `_edit_obrazlozenje` moved to Phase 3 (lives where Правни основ
    # + Бројчани префикс live now). `_edit_json` + `_JsonDialog` removed
    # — JSON wasn't the right abstraction for OIK operators.
