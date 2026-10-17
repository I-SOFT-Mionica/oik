"""Фаза 2.5 — Корекције.

Two inner tabs:
  • Конфликти — list of cards, one per duplicate JMBG.
  • Сви чланови — searchable table of every aggregated slot;
    double-click to edit or replace (illness / withdrawal).

All edits go through CorrectionsState so they hit the audit log.
The master spreadsheet is rewritten on every "Сачувај".
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from biracki_odbor.core.phone import normalize as phone_normalize
from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

from biracki_odbor import app_paths
from biracki_odbor.config.declension import (
    DEFAULT_PREPOSITION, load_overrides, load_prepositions,
    normalize_place_name, place_preposition, place_to_genitive,
    set_user_override, set_user_preposition,
)
from biracki_odbor.core.corrections import (
    CorrectionsState, NacelnikTakeoverNotStartedError, append_nacelnik_takeover,
    cutoff_passed, detect_conflicts, errors_by_jmbg,
)
from biracki_odbor.core.izmene_docx import CHAIRMAN_LAPSE_REASONS
from biracki_odbor.core.master_io import export_master_xlsx, read_master, write_master
from biracki_odbor.core.models import FUNCTIONS, Person
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets import validators
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.collapsible_section import CollapsibleSection
from biracki_odbor.gui.widgets.conflict_card import ConflictCard
from biracki_odbor.logging_setup import log_timing


class CorrectionsTab(QWidget):
    def __init__(self, state: AppState, spec=None) -> None:
        super().__init__()
        self.state = state
        self._spec = spec
        self._persons: list[Person] = []
        self._corrections: CorrectionsState | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel(self.tr("Corrections"))
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        hint = QLabel(self.tr(
            "Resolve conflicts (same person from multiple parties),"
            " replacements due to illness/withdrawal, and minor data corrections."
            " Every change is automatically logged to corrections.log."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        if spec is None:
            self.lbl_cutoff = QLabel()
            self.lbl_cutoff.setObjectName("MutedLabel")
            self.lbl_cutoff.setWordWrap(True)
            root.addWidget(self.lbl_cutoff)
        else:
            self.lbl_cutoff = None

        self.banner = StatusBanner()
        root.addWidget(self.banner)

        # Nacelnik-appointment section — base-tab level (visible
        # regardless of which inner subtab is active), collapsed by
        # default so it doesn't distract from the normal correction
        # workflow, and LOCKED until the hard-stop button (below) is
        # clicked. Only exists for the stalni workflow (spec is None) —
        # prošireni has no legal nacelnik-appointment path. Must be
        # created before _MembersPanel(self), which adds its nacelnik
        # buttons into this section's content instead of its own layout.
        if spec is None:
            self._nacelnik_section = CollapsibleSection(
                self.tr("Chief-of-municipality appointment"),
                initially_expanded=False,
            )
            self._nacelnik_section.set_locked(True)

            # Nacelnik hard-stop — a deliberate, explicit operator
            # decision that submissions are closed, modeled on
            # "Предато РИК-у" (phase3.py). NOT derived from
            # cutoff_stalni alone — the date only gates when this
            # button unlocks, the click itself is the actual legal
            # event. A quick-action so it's reachable right from the
            # section's header while the section is locked/collapsed —
            # the operator shouldn't need to open the box to find it.
            self.btn_nacelnik_takeover = QPushButton(self.tr("Stop accepting submissions"))
            self.btn_nacelnik_takeover.setObjectName("DestructiveButton")
            self.btn_nacelnik_takeover.setToolTip(self.tr(
                "Declares party submissions closed and gives the chief"
                " authority to fill the remaining empty slots. Generates"
                " the chief's Excel template once (from slots empty right"
                " now) and blocks further party-file imports in Phase 2."
                " A deliberate decision, not automatic — the submission"
                " deadline only controls when this button unlocks."
            ))
            self.btn_nacelnik_takeover.clicked.connect(self._on_nacelnik_takeover)
            self._nacelnik_section.add_quick_action(self.btn_nacelnik_takeover)

            # Revert is also a quick-action, not body content — the
            # section stays collapsed by default even after unlocking
            # (no forced auto-expand, so a manually-collapsed box
            # doesn't keep popping back open), so anything the operator
            # needs to reach without opening the box has to live in the
            # header. Mutually exclusive with the takeover button via
            # _update_nacelnik_takeover_ui's visibility toggling.
            self.btn_nacelnik_takeover_revert = QPushButton(self.tr("Reopen submissions"))
            self.btn_nacelnik_takeover_revert.setVisible(False)
            self.btn_nacelnik_takeover_revert.clicked.connect(self._on_nacelnik_takeover_revert)
            self._nacelnik_section.add_quick_action(self.btn_nacelnik_takeover_revert)

            root.addWidget(self._nacelnik_section)
        else:
            self._nacelnik_section = None
            self.btn_nacelnik_takeover = None
            self.btn_nacelnik_takeover_revert = None

        # Inner tabs
        self.inner = QTabWidget()
        root.addWidget(self.inner, stretch=1)

        # Конфликти panel
        self.conflicts_panel = _ConflictsPanel(self)
        self.inner.addTab(self.conflicts_panel, self.tr("Conflicts (0)"))

        # All members panel
        self.members_panel = _MembersPanel(self)
        self.inner.addTab(self.members_panel, self.tr("All members"))

        # Place declension panel
        self.places_panel = _PlacesPanel(self)
        self.inner.addTab(self.places_panel, self.tr("Place declension"))

        # Status panel
        self.summary_panel = _SummaryPanel(self)
        self.inner.addTab(self.summary_panel, self.tr("Status"))

        # Action bar — bottom-anchored, matching the Tab 1/Tab 2 convention
        # (Phase1Tab/Phase2Tab both put their action buttons in a row at
        # the very bottom of the page, not above the main content).
        bar = QHBoxLayout()
        self.btn_reload = QPushButton(self.tr("Refresh"))
        self.btn_reload.setToolTip(self.tr(
            "Reload from the consolidated table on disk — conflicts, all"
            " members, place declension, and status all refresh to match."
        ))
        self.btn_reload.clicked.connect(self.reload_from_master)
        bar.addWidget(self.btn_reload)
        if spec is None:
            self.btn_audit = QPushButton(self.tr("Revision report"))
            self.btn_audit.setToolTip(self.tr(
                "Creates Word documents with a list of files used per party"
                " (with Outlook received timestamp) and all manual changes."
            ))
            self.btn_audit.clicked.connect(self._on_generate_audit)
            bar.addWidget(self.btn_audit)
        else:
            self.btn_audit = None
        bar.addStretch()
        self.btn_export_master = QPushButton(self.tr("Export"))
        self.btn_export_master.setToolTip(self.tr(
            "Saves a copy of the consolidated table to a path you choose."
            " The working copy in master/ is left untouched."
        ))
        self.btn_export_master.clicked.connect(self._export_master)
        bar.addWidget(self.btn_export_master)
        self.btn_save = QPushButton(self.tr("Save changes to consolidated table"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._save)
        bar.addWidget(self.btn_save)
        root.addLayout(bar)

        # React to Phase 2 finishing — reload the master AND pick up the
        # fresh ValidationReport so the members panel can mark error rows.
        if spec is None:
            state.master_changed.connect(self.reload_from_master)
            state.phase2_report_changed.connect(self._refresh_error_report)
            state.election_changed.connect(self._refresh_cutoff_label)
            state.election_changed.connect(self._update_nacelnik_takeover_ui)
            state.generation_log_changed.connect(self._update_nacelnik_takeover_ui)
        else:
            state.prosireni_master_changed.connect(self.reload_from_master)

        self.reload_from_master()
        if spec is None:
            self._refresh_cutoff_label()
            self._update_nacelnik_takeover_ui()

    # ── Spec-aware path helpers ────────────────────────────

    def _master_path(self):
        if self._spec is None:
            return app_paths.master_path()
        return app_paths.master_path_for(self._spec)

    def _log_path(self):
        if self._spec is None:
            return app_paths.corrections_log_path()
        return app_paths.corrections_log_path_for(self._spec)

    def _audit_dir(self):
        if self._spec is None:
            return app_paths.audit_dir()
        return app_paths.audit_dir_for(self._spec)

    def _other_workflow_persons(self) -> list[Person]:
        """Live-read the OTHER workflow's filled persons from the shared
        committee DB (same file either spec resolves to — see
        app_paths.master_path_for), for cross-workflow conflict
        detection in _refresh_all. Swallows read errors the same way a
        not-yet-aggregated other workflow naturally would (empty list,
        not a dialog interrupting THIS workflow's own reload)."""
        from biracki_odbor.core.workflow import PROSIRENI_SPEC
        other_spec = PROSIRENI_SPEC if self._spec is None else None
        try:
            return read_master(self._master_path(), spec=other_spec)
        except Exception:  # noqa: BLE001
            return []

    @log_timing("CorrectionsTab._refresh_cutoff_label")
    def _refresh_cutoff_label(self) -> None:
        if self.lbl_cutoff is None:
            return
        cutoff = self.state.election.election.dates.cutoff_stalni
        if cutoff:
            self.lbl_cutoff.setText(
                self.tr(
                    "Submission deadline for regular composition: <b>{cutoff}</b>."
                    " After that date, empty slots are filled by the chief."
                ).format(cutoff=cutoff)
            )
        else:
            self.lbl_cutoff.setText("")

    def _refresh_nacelnik_gate(self) -> None:
        """Update the nacelnik section's lock-state hint text + button
        states. Called whenever the takeover flag or ElectionConfig
        changes — see `_update_nacelnik_takeover_ui`."""
        if self._nacelnik_section is None:
            return
        wl = self.state.generation_log.workflow("stalni")
        active = wl.nacelnik_takeover_started()
        cutoff = self.state.election.election.dates.cutoff_stalni
        if active:
            self._nacelnik_section.set_description(
                self.tr("Unlocked — submissions closed by the operator (deadline was {cutoff}).").format(cutoff=cutoff or "—")
            )
        elif cutoff_passed(cutoff):
            self._nacelnik_section.set_description(
                self.tr("Deadline ({cutoff}) has passed — click 'Stop accepting submissions' above to unlock.").format(cutoff=cutoff)
            )
        elif cutoff:
            self._nacelnik_section.set_description(
                self.tr("Locked until {cutoff} — the chief has no authority to fill slots before then.").format(cutoff=cutoff)
            )
        else:
            self._nacelnik_section.set_description(
                self.tr("Locked — set the submission deadline (cutoff_stalni) in Election Settings first.")
            )
        self.members_panel._refresh_button_states()  # noqa: SLF001 — sibling widget, same tab

    @log_timing("CorrectionsTab._update_nacelnik_takeover_ui")
    def _update_nacelnik_takeover_ui(self) -> None:
        """Sync the Stop-accepting / Reopen buttons and the section's
        lock state with the current workflow state.

        Also the single place that keeps `CorrectionsState.nacelnik_takeover_active`
        (cached at `reload_from_master()` time) in sync — this method
        runs on every `generation_log_changed`, so it's the one spot
        guaranteed to see every takeover/revert, regardless of source."""
        if self._nacelnik_section is None:
            return
        wl = self.state.generation_log.workflow("stalni")
        active = wl.nacelnik_takeover_started()
        if self._corrections is not None:
            self._corrections.nacelnik_takeover_active = active
        cutoff = self.state.election.election.dates.cutoff_stalni
        self.btn_nacelnik_takeover.setVisible(not active)
        self.btn_nacelnik_takeover.setEnabled(not active and cutoff_passed(cutoff))
        self.btn_nacelnik_takeover_revert.setVisible(active and wl.nacelnik_appointments == 0)
        self._nacelnik_section.set_locked(not active)
        self._refresh_nacelnik_gate()

    def _on_nacelnik_takeover(self) -> None:
        if self._corrections is None:
            QMessageBox.warning(
                self, self.tr("No data"),
                self.tr("Consolidated table does not exist. Run Phase 2 first."),
            )
            return
        empty = [p for p in self._corrections.persons if not p.is_filled]
        # Field report: demo mode's "one BM only" limit (generate_party_files)
        # only ever restricted what parties could submit -- the chief's
        # takeover pulled straight from the master's full empty-slot list,
        # so a demo user could hand everything else to the chief and get
        # fully-populated resenja for every BM in the municipality without
        # a license. Same demo-BM computation as generate_party_files
        # (lowest bm_number) so both paths agree on which BM demo covers.
        if self.state.license.is_demo and self.state.oik.polling_stations:
            demo_bm = min(s.bm_number for s in self.state.oik.polling_stations)
            empty = [p for p in empty if p.bm_number == demo_bm]
        if not empty:
            QMessageBox.information(
                self, self.tr("No empty slots"),
                self.tr("All slots are filled — nothing for the chief to take over."),
            )
            return

        from biracki_odbor.gui.dialogs.confirm_dialog import confirm_with_toggle
        confirmed = confirm_with_toggle(
            self,
            title=self.tr("Stop accepting submissions"),
            text=self.tr(
                "By checking this action you confirm that party submissions"
                " are closed for this cycle.\n\n"
                "After this step:\n"
                "  • The chief's Excel template is generated once, from the"
                " {n} slot(s) still empty right now.\n"
                "  • Phase 2 will no longer accept new party-file imports.\n"
                "  • The chief-appointment section below unlocks.\n\n"
                "This action is reversible only until the first appointment is made."
            ).format(n=len(empty)),
            toggle_text=self.tr("I understand — submissions are closed"),
            confirm_text=self.tr("Confirm"),
            cancel_text=self.tr("Cancel"),
        )
        if not confirmed:
            return

        from biracki_odbor.core.nacelnik_xlsx import export_nacelnik_template
        from biracki_odbor.core.models import PollingStation as _PS
        bm_map: dict[int, _PS] = {
            s.bm_number: s for s in self.state.oik.polling_stations
        }
        password = self.state.oik.lock_password or ""
        internal_path = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        try:
            export_nacelnik_template(
                empty, bm_map, internal_path, password=password,
                election=self.state.election,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Template generation failed:\n{error}").format(error=exc),
            )
            return  # nothing committed — operator can retry

        # Written exactly once, here, at takeover time — Export/Send just
        # re-use this same file from then on (see _on_nacelnik_export /
        # _on_nacelnik_send_email). Fingerprint it now so those re-uses
        # can detect any out-of-band change. See core/file_integrity.py.
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(internal_path)

        wl = self.state.generation_log.workflow("stalni")
        wl.start_nacelnik_takeover()
        self.state.save_generation_log()
        self.state.export_generated("Начелник", [internal_path])
        append_nacelnik_takeover(self._log_path(), "stalni")

        # Deliberately NOT auto-expanded: the section's quick-action row
        # (which now shows "Reopen submissions" instead of "Stop
        # accepting submissions") only appears while collapsed — forcing
        # it open here would immediately hide that. The operator expands
        # it themselves (now unlocked) when ready to actually appoint.
        self._update_nacelnik_takeover_ui()
        self.banner.show_ok(
            self.tr("Submissions closed. Chief's template generated ({n} slot(s)).").format(n=len(empty))
        )

    def _on_nacelnik_takeover_revert(self) -> None:
        wl = self.state.generation_log.workflow("stalni")
        if wl.nacelnik_appointments > 0:
            QMessageBox.warning(
                self, self.tr("Cannot reopen"),
                self.tr(
                    "The chief has already appointed at least one member."
                    " Submissions cannot be reopened."
                ),
            )
            return
        if QMessageBox.question(
            self, self.tr("Reopen submissions"),
            self.tr(
                "Do you want to reopen party submissions?\n\n"
                "Phase 2 imports will become available again."
            ),
        ) != QMessageBox.StandardButton.Yes:
            return
        wl.revert_nacelnik_takeover()
        self.state.save_generation_log()
        self._update_nacelnik_takeover_ui()
        self.banner.show_ok(self.tr("Submissions reopened."))

    # ── Data lifecycle ─────────────────────────────────────

    def set_search(self, jmbg: str) -> None:
        """Switch to All members panel and prefill the search with jmbg."""
        self.inner.setCurrentWidget(self.members_panel)
        self.members_panel.ed_search.setText(jmbg)
        self.members_panel.ed_search.setFocus()

    @log_timing("CorrectionsTab.reload_from_master")
    def reload_from_master(self) -> None:
        master = self._master_path()
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            self._persons = read_master(master, verify=True, spec=self._spec)
        except IntegrityMismatchError as e:
            self._persons = []
            self._corrections = None
            self.btn_export_master.setEnabled(False)
            self.conflicts_panel.set_conflicts([])
            self.members_panel.set_persons([])
            self.members_panel.set_error_report(None)
            self.summary_panel.set_persons([])
            from biracki_odbor.gui.dialogs.integrity_dialog import handle_integrity_mismatch
            handle_integrity_mismatch(self, self.banner, e, self.reload_from_master)
            return
        # `master` is a shared committee DB spanning both workflows now, so
        # its own existence no longer implies THIS workflow has any rows —
        # check the actual result instead (used to check master.exists()).
        self.btn_export_master.setEnabled(bool(self._persons))
        if not self._persons:
            self._corrections = None
            self.banner.show_warn(self.tr("Consolidated table does not exist. Run Phase 2."))
            self.conflicts_panel.set_conflicts([])
            self.members_panel.set_persons([])
            self.members_panel.set_error_report(None)
            self.summary_panel.set_persons([])
            return
        self._corrections = CorrectionsState(
            persons=self._persons, log_path=self._log_path(),
            nacelnik_takeover_active=(
                self._spec is None
                and self.state.generation_log.workflow("stalni").nacelnik_takeover_started()
            ),
            nacelnik_gate_enabled=self._spec is None,
        )
        self._refresh_all()
        self.banner.show_ok(
            self.tr("Loaded {n} entries from the consolidated table.").format(n=len(self._persons))
        )

    def _refresh_all(self) -> None:
        from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
        other_label = STALNI_SPEC.name_sr if self._spec is not None else PROSIRENI_SPEC.name_sr
        conflicts = detect_conflicts(
            self._persons,
            other_workflow_persons=self._other_workflow_persons(),
            election_uuid=self.state.election.election_uuid,
            other_workflow_label=other_label,
        )
        self.conflicts_panel.set_conflicts(conflicts)
        self.inner.setTabText(0, self.tr("Conflicts ({n})").format(n=len(conflicts)))
        self.members_panel.set_persons(self._persons)
        self.places_panel.set_persons(self._persons)
        self.summary_panel.set_persons(self._persons)
        # Re-apply the latest Phase 2 report (if any) so the row
        # marking survives reload_from_master cycles.
        self._refresh_error_report()

    def _refresh_error_report(self) -> None:
        self.members_panel.set_error_report(self.state.last_phase2_report)

    def _export_master(self) -> None:
        """Export the working master to an operator-chosen `.xlsx` path —
        same safer-than-opening-directly pattern as Phase2Tab._export_master.
        The internal committee.db stays the single source of truth; there's
        no xlsx file left to raw-copy, so this builds a fresh export instead.
        """
        from datetime import datetime
        persons = read_master(self._master_path(), spec=self._spec)
        if not persons:
            QMessageBox.warning(
                self, self.tr("Export"),
                self.tr("Consolidated table does not exist. Run Phase 2."),
            )
            return
        muni = (self.state.oik.municipality.name or "OIK").replace(" ", "_")
        date_part = datetime.now().strftime("%Y-%m-%d")
        default_name = f"Consolidated_{muni}_{date_part}.xlsx"
        default_path = str(self.state.files_dir("Извештаји") / default_name)
        chosen, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export consolidated table"), default_path,
            self.tr("Excel files (*.xlsx)"),
        )
        if not chosen:
            return
        try:
            export_master_xlsx(persons, self.state.oik, chosen, spec=self._spec)
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Export failed"),
                self.tr("Cannot write export: {error}").format(error=e),
            )
            return
        self.banner.show_ok(self.tr("Consolidated table exported to: {path}").format(path=chosen))

    # ── Public ops used by panels ──────────────────────────

    @property
    def corrections(self) -> CorrectionsState | None:
        return self._corrections

    def after_mutation(self) -> None:
        self._refresh_all()

    def _save(self) -> None:
        if not self._persons:
            self.banner.show_warn(self.tr("No data to save."))
            return
        # Capture events before the master_changed signal triggers
        # reload_from_master, which resets self._corrections.events.
        saved_events = list(self._corrections.events) if self._corrections else []
        try:
            write_master(self._persons, self.state.oik, self._master_path(), verify=True, spec=self._spec)
        except OSError as e:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Cannot save: {error}").format(error=e))
            return
        # Emit the correct signal for this workflow (prosireni was always
        # emitting master_changed which reloaded the wrong tab).
        if self._spec is None:
            self.state.master_changed.emit()
        else:
            self.state.prosireni_master_changed.emit()
        slug = "prosireni" if self._spec is not None else "stalni"
        gl = self.state.generation_log
        if gl.is_izmena_mode(slug) and saved_events:
            paths = self._auto_generate_izmene(slug, saved_events)
            if paths:
                names = ", ".join(p.name for p in paths[:3])
                if len(paths) > 3:
                    names += f" (+ {len(paths) - 3} др.)"
                self.banner.show_ok(self.tr("Saved. Amendment decisions generated: {names}").format(names=names))
                return
        self.banner.show_ok(self.tr("Changes written to the consolidated table."))

    def _cutoff_date(self, slug: str) -> str:
        ec = self.state.election
        if slug == "prosireni":
            return ec.election.dates.cutoff_prosireni
        return ec.election.dates.cutoff_stalni

    def _auto_generate_izmene(self, slug: str, events: list) -> list:
        import logging as _log
        from biracki_odbor.core.izmene_docx import (
            IzmenaSpec, events_to_izmena_records, generate_izmena,
            group_records_by_variant,
        )
        from biracki_odbor.core.phase3_docx import format_broj
        from biracki_odbor.config.declension import format_serbian_date, to_genitive
        from datetime import date as _date

        ec = self.state.election
        oik = self.state.oik
        gl = self.state.generation_log
        wl = gl.workflow(slug)

        by_bm = events_to_izmena_records(events)
        if not by_bm:
            return []

        bm_numbers_sorted = sorted(ps.bm_number for ps in oik.polling_stations)
        today = _date.today()
        issue_date = to_genitive(format_serbian_date(today.year, today.month, today.day))
        phase_spec = self._spec  # None for stalni, PROSIRENI_SPEC for prosireni
        # Прошиpени decisions are adopted at their own OIK session — read
        # its own session_date_prosireni, not stalni's session_date, so
        # the auto-generated Решење о изменама cites the right original
        # decision date (same field-selection bug class as format_broj above).
        session_date_field = getattr(phase_spec, "session_date_field", "session_date")
        original_date = (
            getattr(ec.election.dates, session_date_field, "") or ec.election.dates.session_date
        )
        output_dir = app_paths.izmene_dir()

        generated = []
        for bm_number, records in sorted(by_bm.items()):
            try:
                bm_offset = bm_numbers_sorted.index(bm_number)
            except ValueError:
                bm_offset = 0
            original_broj_line = format_broj(ec, bm_number, bm_offset, spec=phase_spec)
            original_broj = original_broj_line.removeprefix("Број: ")

            station = oik.station_by_bm(bm_number)
            bm_name = ""
            if station:
                full = getattr(station, "full_name", None) or station.name
                bm_name = full.upper()

            # The generic replacement, same-person correction, and
            # чл. 41. ст. 2. chairman-lapse tracks have different legal
            # basis/образложење and can never share one document — each
            # group below becomes its own amendment with its own ordinal.
            for group in group_records_by_variant(records):
                amendment_index = wl.next_amendment_index(bm_number)
                spec_obj = IzmenaSpec(
                    bm_number=bm_number,
                    bm_name=bm_name,
                    original_broj=original_broj,
                    original_date=original_date,
                    amendment_index=amendment_index,
                    amendment_counter=amendment_index,
                    issue_date=issue_date,
                    records=group,
                    slug=slug,
                )
                try:
                    path = generate_izmena(spec_obj, oik, ec, output_dir)
                    wl.record_izmena(bm_number)
                    generated.append(path)
                except Exception:
                    _log.getLogger(__name__).exception(
                        "Auto-generate izmena failed for BM %s", bm_number
                    )

        if generated:
            self.state.save_generation_log()
        return generated

    def _on_generate_audit(self) -> None:
        """Generate the combined + per-party audit documents.

        Runs synchronously — the generator is fast (one .docx per
        party, plus the combined; even with 50 parties it finishes
        in <2 s in practice). If profiling shows it gets slow we can
        port to the same `start_worker` pattern Phase 3 uses.
        """
        if not self._persons:
            self.banner.show_warn(self.tr("No data for report. Run Phase 2 first."))
            return
        from biracki_odbor.core.accountability_log import (
            generate_accountability_log,
        )
        audit = self._audit_dir()
        try:
            result = generate_accountability_log(
                self._persons,
                self.state.oik,
                self.state.election,
                audit,
            )
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot save audit documents: {error}").format(error=e),
            )
            return
        n = len(result.files_written)
        export_dir = self.state.files_dir("Ревизија")
        self.state.export_generated("Ревизија", result.files_written)
        self.banner.show_ok(
            self.tr("Saved {n} audit document(s) to {audit}.").format(n=n, audit=export_dir)
        )
        # Convenience: pop the export folder open so the operator can
        # review immediately. Same pattern as Phase 3.
        reply = QMessageBox.question(
            self, self.tr("Audit trail"),
            self.tr("Saved {n} document(s) to folder:\n{audit}\n\nOpen folder?").format(n=n, audit=export_dir),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            import os
            import subprocess
            try:
                if os.name == "nt":
                    os.startfile(str(export_dir))  # noqa: S606
                else:
                    subprocess.Popen(["xdg-open", str(export_dir)])
            except OSError:
                pass


# ── Inner panels ──────────────────────────────────────────


class _ConflictsPanel(QWidget):
    def __init__(self, tab: CorrectionsTab) -> None:
        super().__init__()
        self.tab = tab
        self._all_conflicts: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.tr("Search:")))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(self.tr("JMBG or name…"))
        self.ed_search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.ed_search, stretch=1)
        root.addLayout(search_row)

        self.empty_label = QLabel(
            self.tr("No conflicts. Every person is unique by JMBG.")
        )
        self.empty_label.setObjectName("OkLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(12)
        self.container_layout.addStretch()
        scroll.setWidget(self.container)
        root.addWidget(scroll, stretch=1)

    def set_conflicts(self, conflicts: list) -> None:
        self._all_conflicts = conflicts
        self.ed_search.clear()
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.ed_search.text().strip().lower()
        filtered = [
            c for c in self._all_conflicts
            if not needle
            or needle in c.jmbg.lower()
            or needle in c.name.lower()
        ]
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.empty_label.setVisible(not self._all_conflicts)
        for c in filtered:
            card = ConflictCard(c)
            card.resolved.connect(self._on_resolved)
            card.slot_removed.connect(self._on_slot_removed)
            card.removed_both.connect(self._on_removed_both)
            self.container_layout.insertWidget(
                self.container_layout.count() - 1, card
            )

    def _on_resolved(self, conflict, keep_slot_key: tuple[int, str], note: str) -> None:
        if self.tab.corrections is None:
            return
        self.tab.corrections.resolve_conflict(
            conflict, keep_slot_key=keep_slot_key, note=note,
        )
        bm, func = keep_slot_key
        self.tab.banner.show_ok(
            self.tr("Conflict resolved — kept slot BM {bm}, {func}. Click 'Save changes to consolidated table' to write.").format(bm=bm, func=func)
        )
        self.tab.after_mutation()

    def _on_slot_removed(self, conflict, slot_key: tuple[int, str], note: str) -> None:
        if self.tab.corrections is None:
            return
        self.tab.corrections.remove_one_slot(conflict, slot_key, note=note)
        bm, func = slot_key
        self.tab.banner.show_ok(
            self.tr("Slot BM {bm}, {func} cleared. Click 'Save changes to consolidated table' to write.").format(bm=bm, func=func)
        )
        self.tab.after_mutation()

    def _on_removed_both(self, conflict, note: str) -> None:
        if self.tab.corrections is None:
            return
        self.tab.corrections.remove_from_all(conflict, note=note)
        self.tab.banner.show_ok(
            self.tr("Person (JMBG {jmbg}) removed from all parties. Click 'Save changes to consolidated table' to write.").format(jmbg=conflict.jmbg)
        )
        self.tab.after_mutation()


class _MembersPanel(QWidget):
    HEADERS = [
        "BM", "Function", "Party", "First name", "Last name", "JMBG",
        "Place", "Phone", "Email",
    ]

    def __init__(self, tab: CorrectionsTab) -> None:
        super().__init__()
        self.tab = tab
        self._persons: list[Person] = []
        # JMBG → list[Issue] index built from the last Phase 2 report.
        # Empty when there's no report yet (fresh app launch with a
        # pre-existing master) — every person renders normally.
        self._errors_by_jmbg: dict[str, list] = {}
        # When True, the filter drops every row that doesn't have at
        # least one matching error. Toggled by the «Само грешке»
        # checkbox; off by default so the operator's first sight of
        # the tab is still the full roster.
        self._errors_only: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Search bar + errors-only toggle. Both feed `_apply_filter`.
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.tr("Search:")))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(
            self.tr("Type name, JMBG or list…") if tab._spec is not None
            else self.tr("Type name, JMBG or party…")
        )
        self.ed_search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.ed_search, stretch=1)
        self.cb_errors_only = ToggleSwitch(self.tr("Errors only"))
        self.cb_errors_only.setToolTip(self.tr(
            "Show only rows whose JMBG has an error from the last"
            " Phase 2 run (e.g. invalid MOD 11, duplicate, wrong format)."
        ))
        self.cb_errors_only.toggled.connect(self._on_errors_only_toggled)
        search_row.addWidget(self.cb_errors_only)
        root.addLayout(search_row)

        # Table
        # "Party" column: stalni's `party` field holds a party abbreviation,
        # but the SAME field on a prosireni Person holds a canonical
        # entity_id (a "list", not a party) -- see
        # core/prosireni_allocation.py's build_prosireni_allocation
        # docstring. Label the column to match what it actually contains.
        party_col_label = (
            QCoreApplication.translate("_MembersPanel", "List")
            if tab._spec is not None
            else QCoreApplication.translate("_MembersPanel", "Party")
        )
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([
            QCoreApplication.translate("_MembersPanel", "BM"),
            QCoreApplication.translate("_MembersPanel", "Function"),
            party_col_label,
            QCoreApplication.translate("_MembersPanel", "First name"),
            QCoreApplication.translate("_MembersPanel", "Last name"),
            QCoreApplication.translate("_MembersPanel", "JMBG"),
            QCoreApplication.translate("_MembersPanel", "Place"),
            QCoreApplication.translate("_MembersPanel", "Phone"),
            QCoreApplication.translate("_MembersPanel", "Email"),
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        h.resizeSection(0, 50)
        h.resizeSection(1, 150)
        h.resizeSection(2, 100)
        h.resizeSection(3, 120)
        h.resizeSection(4, 140)
        h.resizeSection(5, 140)
        h.resizeSection(6, 140)
        h.resizeSection(7, 130)  # Телефон
        h.resizeSection(8, 200)  # Е-пошта — wider; common content is long
        self.table.doubleClicked.connect(self._on_edit)
        root.addWidget(self.table, stretch=1)

        # Action row — Edit/Replace/Clear only. Nacelnik-related actions
        # live in CorrectionsTab's base-tab-level nacelnik section (§21)
        # so they're visible/reachable regardless of the active subtab —
        # see below.
        btns = QHBoxLayout()
        self.btn_edit = QPushButton(self.tr("Edit"))
        self.btn_edit.setToolTip(self.tr("Edit selected (Enter)"))
        self.btn_edit.clicked.connect(self._on_edit)
        btns.addWidget(self.btn_edit)
        self.btn_replace = QPushButton(self.tr("Replace"))
        self.btn_replace.setToolTip(self.tr("Replace (illness/withdrawal)"))
        self.btn_replace.clicked.connect(self._on_replace)
        btns.addWidget(self.btn_replace)
        self.btn_clear = QPushButton(self.tr("Clear slot"))
        self.btn_clear.setObjectName("DangerButton")
        self.btn_clear.clicked.connect(self._on_clear)
        btns.addWidget(self.btn_clear)
        btns.addStretch()
        root.addLayout(btns)

        # Načelnik appointment — fills the EMPTY slot the operator
        # selected (in this panel's table) with the name they enter,
        # writes a NACELNIK_APPOINTMENT event to corrections.log so the
        # audit trail clearly separates this from regular party-side
        # edits. Phase 3's empty-slot gate (A5.2) unblocks once every
        # empty slot has been appointed or otherwise filled. Also gated
        # by cutoff_stalni (§21) — see `_refresh_button_states`.
        self.btn_nacelnik = QPushButton(self.tr("Appoint"))
        self.btn_nacelnik.setToolTip(self.tr(
            "Appointed by the chief of municipality. Fills an empty slot"
            " by chief-of-municipality appointment. Clearly logged in"
            " corrections.log and audit trail."
        ))
        self.btn_nacelnik.clicked.connect(self._on_nacelnik_appoint)

        # Excel batch workflow — export blank template for all empty
        # slots; načelnik fills it and returns the file for import. Only
        # built when this panel belongs to the stalni workflow (spec is
        # None); prošireni has no načelnik appointment path.
        if tab._spec is None:
            nacelnik_row = QHBoxLayout()
            nacelnik_row.addWidget(self.btn_nacelnik)
            nacelnik_row.addStretch()

            excel_row = QHBoxLayout()
            self.btn_nacelnik_export = QPushButton(self.tr("Export"))
            self.btn_nacelnik_export.setToolTip(self.tr(
                "Export chief template. Exports an Excel file with all"
                " EMPTY slots. The chief fills it in and returns it for import."
            ))
            self.btn_nacelnik_export.clicked.connect(self._on_nacelnik_export)
            excel_row.addWidget(self.btn_nacelnik_export)

            self.btn_nacelnik_send = QPushButton(self.tr("Send"))
            self.btn_nacelnik_send.setToolTip(self.tr(
                "Send to chief by email. Sends the Excel template to the"
                " chief by email. Opens a draft in the configured email client."
            ))
            self.btn_nacelnik_send.clicked.connect(self._on_nacelnik_send_email)
            excel_row.addWidget(self.btn_nacelnik_send)

            self.btn_nacelnik_inbox = QPushButton(self.tr("Receive"))
            self.btn_nacelnik_inbox.setToolTip(self.tr(
                "Fetch reply from inbox. Searches the inbox for Excel files"
                " from the chief and offers them for import."
            ))
            self.btn_nacelnik_inbox.clicked.connect(self._on_nacelnik_inbox)
            excel_row.addWidget(self.btn_nacelnik_inbox)

            self.btn_nacelnik_import = QPushButton(self.tr("Import"))
            self.btn_nacelnik_import.setToolTip(self.tr(
                "Import completed template. Imports a completed Excel file"
                " from disk. All slots must be filled — an incomplete file"
                " will be rejected."
            ))
            self.btn_nacelnik_import.clicked.connect(self._on_nacelnik_import)
            excel_row.addWidget(self.btn_nacelnik_import)
            excel_row.addStretch()

            nacelnik_body = QWidget()
            nacelnik_body_vbox = QVBoxLayout(nacelnik_body)
            nacelnik_body_vbox.setContentsMargins(0, 0, 0, 0)
            nacelnik_body_vbox.setSpacing(8)
            nacelnik_body_vbox.addLayout(nacelnik_row)
            nacelnik_body_vbox.addLayout(excel_row)
            tab._nacelnik_section.set_content(nacelnik_body)
        else:
            # Existing (if arguably accidental) prošireni behavior: the
            # single appoint button stays reachable here since there's
            # no nacelnik section for prošireni — unchanged from before.
            btns.insertWidget(2, self.btn_nacelnik)
            self.btn_nacelnik_export = None
            self.btn_nacelnik_send = None
            self.btn_nacelnik_inbox = None
            self.btn_nacelnik_import = None

        # Enable/disable the Načelnik button live based on selection —
        # the action only makes sense for an empty slot.
        self.table.itemSelectionChanged.connect(self._refresh_button_states)
        self._refresh_button_states()

    def set_persons(self, persons: list[Person]) -> None:
        self._persons = persons
        self._apply_filter()

    def set_error_report(self, report) -> None:
        """Bind a Phase 2 ValidationReport to the table for row marking.

        Builds a `jmbg → list[Issue]` index. Persons whose JMBG appears
        on that index render with a light error background + a tooltip
        listing the offending messages. Pass `None` (or a report with
        an empty issues list) to clear the marks — used when the
        operator hasn't run Phase 2 in this session yet, or runs it
        again with a clean roster.

        Today only JMBG-keyed issues participate. Codes whose `detail`
        isn't a JMBG (NAME_EMPTY, PHONE_TOO_SHORT, …) still appear in
        Phase 2's error table; the marking here is the "find row in
        the master" subset.
        """
        self._errors_by_jmbg = errors_by_jmbg(report)
        self._apply_filter()

    def _on_errors_only_toggled(self, checked: bool) -> None:
        self._errors_only = checked
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.ed_search.text().strip().lower()
        # Pre-filter and pre-allocate so we avoid 8 layout passes × N rows.
        # setUpdatesEnabled(False) batches the repaint at the end.
        rows: list[tuple[int, Person]] = []
        for idx, p in enumerate(self._persons):
            if self._errors_only and p.jmbg not in self._errors_by_jmbg:
                continue
            hay = (
                f"{p.first_name} {p.last_name} {p.jmbg} {p.party}"
                f" {p.function} {p.email}".lower()
            )
            if needle and needle not in hay:
                continue
            rows.append((idx, p))

        # Solid-but-light error background, opacity-tinted via QColor's
        # 4th alpha arg so alternating-row colours still bleed through.
        # Light coral / salmon is conventional for "problem here"
        # without being aggressive; matches the StatusBanner error tone.
        error_bg = QColor(255, 224, 224)

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for ridx, (orig_idx, p) in enumerate(rows):
                cells = (
                    str(p.bm_number), p.function, p.party,
                    p.first_name, p.last_name, p.jmbg, p.mesto,
                    p.telefon, p.email,
                )
                row_errors = self._errors_by_jmbg.get(p.jmbg, [])
                tooltip = (
                    "\n".join(i.message_sr for i in row_errors)
                    if row_errors else ""
                )
                for cidx, val in enumerate(cells):
                    item = QTableWidgetItem(val)
                    if row_errors:
                        item.setBackground(error_bg)
                        if tooltip:
                            item.setToolTip(tooltip)
                    self.table.setItem(ridx, cidx, item)
                self.table.item(ridx, 0).setData(Qt.UserRole, orig_idx)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def _selected_person(self) -> Person | None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return None
        row = next(iter(rows))
        idx = self.table.item(row, 0).data(Qt.UserRole)
        if idx is None:
            return None
        return self._persons[idx]

    def _on_edit(self) -> None:
        p = self._selected_person()
        if p is None or self.tab.corrections is None:
            return
        dlg = _PersonEditDialog(p, mode="edit", spec=self.tab._spec, parent=self,
                                other_workflow=self.tab._other_workflow_persons())
        if dlg.exec() == QDialog.Accepted:
            self.tab.corrections.edit_member(
                p.bm_number, p.function, dlg.values(), note=dlg.note(),
                other_bm=dlg.other_bm(), other_municipality=dlg.other_municipality(),
                other_decision_broj=dlg.other_decision_broj(),
            )
            self.tab.after_mutation()

    def _on_replace(self) -> None:
        p = self._selected_person()
        if p is None or self.tab.corrections is None:
            return
        dlg = _PersonEditDialog(p, mode="replace", spec=self.tab._spec, parent=self,
                                other_workflow=self.tab._other_workflow_persons())
        if dlg.exec() == QDialog.Accepted:
            self.tab.corrections.replace_member(
                p.bm_number, p.function, dlg.values(),
                note=dlg.note() or "Замена",
                other_bm=dlg.other_bm(), other_municipality=dlg.other_municipality(),
                other_decision_broj=dlg.other_decision_broj(),
            )
            self.tab.after_mutation()

    def _on_nacelnik_appoint(self) -> None:
        """Fill the selected EMPTY slot with a načelnik appointment.

        Opens the same person edit dialog used for regular edits,
        runs through `appoint_by_nacelnik` which tags the audit event
        type as `nacelnik_appointment` and prefixes the note with
        «Именовао начелник». The Phase 3 empty-slot gate (A5.2)
        updates as soon as `tab.after_mutation` cascades through.
        """
        p = self._selected_person()
        if p is None or self.tab.corrections is None:
            return
        if p.is_filled:
            QMessageBox.information(
                self, self.tr("Slot is not empty"),
                self.tr("The slot is already filled. Use 'Edit selected' or 'Replace' to change an existing person."),
            )
            return
        dlg = _PersonEditDialog(p, mode="edit", spec=self.tab._spec, parent=self,
                                other_workflow=self.tab._other_workflow_persons())
        dlg.setWindowTitle(self.tr("Appointment by chief"))
        if dlg.exec() == QDialog.Accepted:
            try:
                self.tab.corrections.appoint_by_nacelnik(
                    p.bm_number, p.function, dlg.values(), note=dlg.note(),
                    other_bm=dlg.other_bm(), other_municipality=dlg.other_municipality(),
                    other_decision_broj=dlg.other_decision_broj(),
                )
            except NacelnikTakeoverNotStartedError:
                # Defense-in-depth — the button is already disabled
                # until takeover, so this should be unreachable in
                # normal use; only guards against a stale UI state.
                QMessageBox.warning(
                    self, self.tr("Submissions not closed yet"),
                    self.tr(
                        "The chief has no authority to fill slots yet —"
                        " click 'Stop accepting submissions' first."
                    ),
                )
                return
            wl = self.tab.state.generation_log.workflow("stalni")
            wl.record_nacelnik_appointment()
            self.tab.state.save_generation_log()
            self.tab.after_mutation()

    def _regenerate_nacelnik_template(self) -> Path | None:
        """(Re)write nacelnik_sablion.xlsx from whatever is STILL empty
        right now, using the current export_nacelnik_template() code.

        Field report: the old "generate once at takeover time, Export/
        Send just re-copy that same file forever" design meant a chief
        template generated before some later improvement to the
        generator itself (JMBG red/green validation, capitalization/
        email checks, ...) stayed stuck looking exactly as it did back
        then — every subsequent Export/Send handed out that same
        stale file, no matter how much export_nacelnik_template()
        itself had since improved.

        Regenerating against "still empty now" rather than reusing a
        frozen "empty at takeover" snapshot is safe, not just
        convenient: a slot can only ever LEAVE that set afterward (via
        appoint_by_nacelnik, the only way to fill one post-takeover —
        Phase 2 no longer accepts party imports once submissions are
        closed), never re-enter it, so this is always the same list or
        a subset of what the original takeover snapshot would still
        show, just reflecting appointments made since. The demo-mode
        single-BM restriction is re-applied every time for the same
        reason _on_nacelnik_takeover applies it originally -- it must
        not loosen just because the operator re-exports.

        Raises `IntegrityMismatchError` (propagated to the caller,
        which routes it through handle_integrity_mismatch exactly like
        before) if a template already exists on disk but doesn't match
        its last recorded fingerprint — regenerating must NOT silently
        paper over external tampering just because we're about to
        overwrite the file anyway; the operator still needs to see
        that something touched it outside the app."""
        if self.tab.corrections is None or not self.tab.corrections.nacelnik_takeover_active:
            return None
        internal_path = app_paths.master_dir() / "nacelnik_sablion.xlsx"
        if internal_path.exists():
            from biracki_odbor.core.file_integrity import check_or_raise
            check_or_raise(internal_path)

        empty = [p for p in self.tab.corrections.persons if not p.is_filled]
        if self.tab.state.license.is_demo and self.tab.state.oik.polling_stations:
            demo_bm = min(s.bm_number for s in self.tab.state.oik.polling_stations)
            empty = [p for p in empty if p.bm_number == demo_bm]

        from biracki_odbor.core.nacelnik_xlsx import export_nacelnik_template
        from biracki_odbor.core.models import PollingStation as _PS
        bm_map: dict[int, _PS] = {
            s.bm_number: s for s in self.tab.state.oik.polling_stations
        }
        export_nacelnik_template(
            empty, bm_map, internal_path,
            password=self.tab.state.oik.lock_password or "",
            election=self.tab.state.election,
        )
        from biracki_odbor.core import file_integrity
        file_integrity.record_verified(internal_path)
        return internal_path

    def _on_nacelnik_export(self) -> None:
        """Regenerate the chief's template fresh (see
        _regenerate_nacelnik_template) and copy it into the operator's
        export folder."""
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            internal_path = self._regenerate_nacelnik_template()
        except IntegrityMismatchError as e:
            from biracki_odbor.gui.dialogs.integrity_dialog import handle_integrity_mismatch
            handle_integrity_mismatch(self, self.tab.banner, e, self._on_nacelnik_export)
            return
        except Exception as exc:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Template generation failed:\n{error}").format(error=exc),
            )
            return
        if internal_path is None:
            QMessageBox.warning(
                self, self.tr("Template not found"),
                self.tr(
                    "The chief's template hasn't been generated yet —"
                    " it's created automatically when you click"
                    " 'Stop accepting submissions'."
                ),
            )
            return
        copied = self.tab.state.export_generated("Начелник", [internal_path])
        export_dir = self.tab.state.files_dir("Начелник")
        self.tab.banner.show_ok(
            self.tr("Template copied to: {path}").format(
                path=copied[0] if copied else export_dir
            )
        )
        import subprocess
        try:
            subprocess.Popen(["explorer", str(export_dir)])
        except OSError:
            pass

    def _on_nacelnik_import(self) -> None:
        """Import a completed nacelnik xlsx from disk."""
        if self.tab.corrections is None:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import completed chief template"),
            str(self.tab.state.files_dir("Начелник")),
            self.tr("Excel file (*.xlsx)"),
        )
        if not path:
            return

        self._import_from_path(path)

    def _on_nacelnik_send_email(self) -> None:
        """Create an email draft with the chief's xlsx template attached.

        Regenerates the template fresh (see
        _regenerate_nacelnik_template) rather than re-attaching
        whatever was generated once at takeover time — no file picker,
        same as every other "Send" button in the app (Phase 1/Phase 3):
        auto-attach whatever was actually just generated, never ask
        the operator to hunt for a file."""
        from biracki_odbor.integrations import email_client as ec
        if not ec.any_available():
            QMessageBox.warning(
                self, self.tr("Email client unavailable"),
                self.tr(
                    "No email client found (Outlook or Thunderbird).\n"
                    "Configure the email client in OIK Settings → System and try again."
                ),
            )
            return

        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            internal_path = self._regenerate_nacelnik_template()
        except IntegrityMismatchError as e:
            # Must not send an official document we can't currently
            # verify — no retry-callback that re-sends automatically.
            from biracki_odbor.gui.dialogs.integrity_dialog import handle_integrity_mismatch
            handle_integrity_mismatch(self, self.tab.banner, e, lambda: None)
            return
        except Exception as exc:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Template generation failed:\n{error}").format(error=exc),
            )
            return
        if internal_path is None:
            QMessageBox.warning(
                self, self.tr("Template not found"),
                self.tr(
                    "The chief's template hasn't been generated yet —"
                    " it's created automatically when you click"
                    " 'Stop accepting submissions'."
                ),
            )
            return

        # Ask for / confirm načelnik email address
        settings = self.tab.state.app_settings
        stored_email = settings.nacelnik_email

        from PySide6.QtWidgets import QInputDialog
        recipient, ok = QInputDialog.getText(
            self,
            self.tr("Chief's email"),
            self.tr("Enter the chief's email address:"),
            text=stored_email,
        )
        recipient = recipient.strip()
        if not ok or not recipient:
            return

        # Persist for next time
        if recipient != stored_email:
            settings.nacelnik_email = recipient
            self.tab.state.save_app_settings()

        from biracki_odbor.integrations.email_client import DraftSpec

        subject = (
            "Excel шаблон за именовање чланова ОИК — "
            + (self.tab.state.election.election.dates.date_full or "")
        )
        body = (
            "Поштовани,\n\n"
            "У прилогу се налази Excel шаблон са празним члановима бирачких"
            " одбора које је потребно именовати.\n\n"
            "Молимо попуните беле ћелије (Ime, Prezime, JMBG, ...) и вратите"
            " попуњен фајл на ову адресу.\n\n"
            "С поштовањем,\n"
            "Општинска изборна комисија"
        )

        results = ec.create_drafts(
            drafts=[DraftSpec(
                to=recipient,
                subject=subject,
                body=body,
                attachment=internal_path,
            )],
            preference=settings.email_client,
            display_first=True,
        )

        if results and not results[0].ok:
            QMessageBox.warning(
                self, self.tr("Send error"),
                self.tr("Draft was not created:\n{error}").format(error=results[0].error),
            )
            return

        self.tab.banner.show_ok(
            self.tr("Email draft for chief ({recipient}) opened in email client.").format(recipient=recipient)
        )

    def _on_nacelnik_inbox(self) -> None:
        """Fetch inbox for načelnik's xlsx reply and offer it for import."""
        from biracki_odbor.integrations import email_client as ec
        if not ec.any_inbox_available():
            QMessageBox.warning(
                self, self.tr("Email client unavailable"),
                self.tr(
                    "Inbox access is unavailable.\n"
                    "Configure Outlook or Thunderbird in OIK Settings → System."
                ),
            )
            return

        settings = self.tab.state.app_settings
        nacelnik_email = settings.nacelnik_email

        self.tab.banner.show_info(self.tr("Searching inbox…"))
        try:
            messages = ec.fetch_inbox_messages(
                preference=settings.email_client,
                since_days=60,
                only_xlsx=True,
                max_messages=50,
                subject_contains="",
                account_email=settings.oik_email or "",
            )
        except Exception as exc:
            self.tab.banner.show_error(self.tr("Error reading inbox: {error}").format(error=exc))
            return

        # Filter by sender if we know the načelnik email
        if nacelnik_email:
            filtered = [
                m for m in messages
                if nacelnik_email.lower() in (m.sender_email or "").lower()
            ]
            # Fall back to all if filtering removes everything
            if not filtered:
                filtered = messages
        else:
            filtered = messages

        if not filtered:
            QMessageBox.information(
                self, self.tr("No messages"),
                self.tr(
                    "No Excel messages found in inbox in the last 60 days.\n"
                    "Check whether the chief has replied."
                ),
            )
            self.tab.banner.show_warn(self.tr("No Excel messages found in inbox."))
            return

        # Simple picker dialog
        dlg = _NacelnikInboxPickerDialog(filtered, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return

        chosen_path = dlg.chosen_path
        if not chosen_path or not chosen_path.exists():
            return

        # Delegate to the existing import logic
        self._import_from_path(str(chosen_path))

    def _import_from_path(self, path: str) -> None:
        """Core import logic shared between disk-import and inbox-import."""
        if self.tab.corrections is None:
            return
        if (
            self.tab.corrections.nacelnik_gate_enabled
            and not self.tab.corrections.nacelnik_takeover_active
        ):
            # Defense-in-depth — the import button is already disabled
            # until takeover, so this should be unreachable in normal
            # use; only guards against a stale UI state.
            QMessageBox.warning(
                self, self.tr("Submissions not closed yet"),
                self.tr(
                    "The chief has no authority to fill slots yet —"
                    " click 'Stop accepting submissions' first."
                ),
            )
            return

        from datetime import date as _date
        from biracki_odbor.config.declension import parse_serbian_date
        from biracki_odbor.core.nacelnik_xlsx import read_nacelnik_xlsx

        election_date: _date | None = None
        try:
            parsed = parse_serbian_date(
                self.tab.state.election.election.dates.date_full
            )
            if parsed:
                election_date = _date(*parsed)
        except Exception:
            pass

        rows, errors = read_nacelnik_xlsx(path, election_date=election_date)

        # Defense-in-depth: the generated template already only covers the
        # demo BM (see CorrectionsTab._on_nacelnik_takeover), but the sheet
        # protection on the locked БМ column isn't real security -- reject
        # rows for any other BM here too, in case of a hand-edited file.
        if self.tab.state.license.is_demo and self.tab.state.oik.polling_stations:
            demo_bm = min(s.bm_number for s in self.tab.state.oik.polling_stations)
            for row in rows:
                if row.is_filled and row.bm_number != demo_bm:
                    errors.append(
                        f"Ред {row.row_number}: БМ {row.bm_number} није дозвољен"
                        f" у демо режиму (само БМ {demo_bm})."
                    )

        existing_jmbgs: dict[str, tuple[int, str]] = {}
        for p in self.tab.corrections.persons:
            if p.is_filled and p.jmbg:
                existing_jmbgs[p.jmbg] = (p.bm_number, p.function)

        for row in rows:
            if not row.is_filled or not row.jmbg:
                continue
            if row.jmbg in existing_jmbgs:
                other = existing_jmbgs[row.jmbg]
                errors.append(
                    f"Ред {row.row_number} (БМ {row.bm_number}, {row.function}): "
                    f"ЈМБГ '{row.jmbg}' већ постоји у слоту "
                    f"БМ {other[0]}, {other[1]}."
                )

        if errors:
            detail = "\n".join(f"• {e}" for e in errors)
            QMessageBox.critical(
                self, self.tr("Import rejected — incomplete or invalid file"),
                self.tr("File has {n} problem(s). Fix them and try again:\n\n{detail}").format(n=len(errors), detail=detail),
            )
            return

        already_filled = 0
        appointed = 0
        for row in rows:
            if not row.is_filled:
                continue
            target = next(
                (p for p in self.tab.corrections.persons
                 if p.slot_key == (row.bm_number, row.function)),
                None,
            )
            if target is None:
                continue
            if target.is_filled:
                already_filled += 1
                continue
            self.tab.corrections.appoint_by_nacelnik(
                row.bm_number, row.function,
                {
                    "first_name": row.first_name,
                    "last_name":  row.last_name,
                    "jmbg":       row.jmbg,
                    "mesto":      row.mesto,
                    "adresa":     row.adresa,
                    "telefon":    row.telefon,
                    "email":      row.email,
                },
                note="Увезено из Excel шаблона начелника",
            )
            appointed += 1

        if appointed:
            wl = self.tab.state.generation_log.workflow("stalni")
            wl.record_nacelnik_appointment(appointed)
            self.tab.state.save_generation_log()

        self.tab.after_mutation()

        msg = self.tr("Appointed: {n} slot(s).").format(n=appointed)
        if already_filled:
            msg += "\n" + self.tr("Skipped: {n} (already filled manually).").format(n=already_filled)
        QMessageBox.information(self, self.tr("Import complete"), msg)

    def _refresh_button_states(self) -> None:
        """Enable «Именуј од стране начелника…» only on empty rows, AND
        (stalni only, §21) only once the operator has clicked 'Stop
        accepting submissions' — the chief has no legal authority to
        fill slots before then. The 4 excel-workflow buttons share the
        same gate: preparing a chief template has no purpose until
        submissions are actually closed.

        Edit / Replace / Clear stay enabled regardless so existing
        flows for non-empty rows are unchanged."""
        p = self._selected_person()
        slot_ok = p is not None and not p.is_filled
        if self.tab._spec is None:  # noqa: SLF001 — same-tab sibling
            gate_ok = self.tab.state.generation_log.workflow("stalni").nacelnik_takeover_started()
            self.btn_nacelnik.setEnabled(slot_ok and gate_ok)
            for btn in (
                self.btn_nacelnik_export, self.btn_nacelnik_send,
                self.btn_nacelnik_inbox, self.btn_nacelnik_import,
            ):
                btn.setEnabled(gate_ok)
        else:
            # Prošireni has no legal nacelnik-cutoff concept — unchanged.
            self.btn_nacelnik.setEnabled(slot_ok)

    def _on_clear(self) -> None:
        p = self._selected_person()
        if p is None or self.tab.corrections is None:
            return
        clear_msg = (
            self.tr("Clear slot: BM {bm}, {func}, list {party}?")
            if self.tab._spec is not None
            else self.tr("Clear slot: BM {bm}, {func}, party {party}?")
        )
        if QMessageBox.question(
            self, self.tr("Confirm"),
            clear_msg.format(bm=p.bm_number, func=p.function, party=p.party),
        ) != QMessageBox.Yes:
            return
        self.tab.corrections.clear_member(
            p.bm_number, p.function, note="Испражњено из ГУИ",
        )
        self.tab.after_mutation()


class _SummaryPanel(QWidget):
    def __init__(self, tab: CorrectionsTab) -> None:
        super().__init__()
        self.tab = tab
        self._persons: list[Person] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("HeadLabel")
        self.summary_label.setWordWrap(True)
        top_row.addWidget(self.summary_label, stretch=1)
        self.btn_export_report = QPushButton(self.tr("Export status report…"))
        self.btn_export_report.clicked.connect(self._on_export_report)
        top_row.addWidget(self.btn_export_report)
        root.addLayout(top_row)

        self.party_table = QTableWidget(0, 3)
        party_col_label = self.tr("List") if tab._spec is not None else self.tr("Party")
        self.party_table.setHorizontalHeaderLabels([party_col_label, self.tr("Total"), self.tr("Filled")])
        self.party_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.party_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.party_table.verticalHeader().setVisible(False)
        # Let the table fill the panel — no trailing stretch means the empty
        # space at the bottom shows more rows instead of staying blank.
        root.addWidget(self.party_table, stretch=1)

    def set_persons(self, persons: list[Person]) -> None:
        self._persons = persons
        if not persons:
            self.summary_label.setText(self.tr("No data."))
            self.party_table.setRowCount(0)
            return
        total = len(persons)
        filled = sum(1 for p in persons if p.is_filled)
        n_bm = len({p.bm_number for p in persons})
        self.summary_label.setText(
            self.tr(
                "Total positions: {total}   ·   Filled: {filled}   ·   "
                "Empty: {empty}   ·   Polling stations: {n_bm}"
            ).format(total=total, filled=filled, empty=total - filled, n_bm=n_bm)
        )
        stats: dict[str, tuple[int, int]] = {}
        for p in persons:
            tot, fil = stats.get(p.party, (0, 0))
            tot += 1
            if p.is_filled:
                fil += 1
            stats[p.party] = (tot, fil)
        self.party_table.setRowCount(0)
        # Sort by allocated count DESC, then party name ASC.
        for party, (tot, fil) in sorted(stats.items(), key=lambda kv: (-kv[1][0], kv[0])):
            r = self.party_table.rowCount()
            self.party_table.insertRow(r)
            self.party_table.setItem(r, 0, QTableWidgetItem(party))
            self.party_table.setItem(r, 1, QTableWidgetItem(str(tot)))
            self.party_table.setItem(r, 2, QTableWidgetItem(str(fil)))

    def _on_export_report(self) -> None:
        """Dated .docx snapshot of this exact panel -- same numbers,
        same per-party breakdown, as a print/archive-ready document.
        Same "pick a path, default name/folder includes the date"
        pattern as CorrectionsTab._export_master, not an internal-copy
        + export_generated step -- this is a snapshot report, not an
        official document needing integrity tracking."""
        if not self._persons:
            QMessageBox.warning(
                self, self.tr("Export"),
                self.tr("Consolidated table does not exist. Run Phase 2."),
            )
            return
        from datetime import datetime
        from biracki_odbor.core.status_report import generate_status_report
        muni = (self.tab.state.oik.municipality.name or "OIK").replace(" ", "_")
        workflow_part = "Prosireni" if self.tab._spec is not None else "Stalni"
        date_part = datetime.now().strftime("%Y-%m-%d_%H%M")
        default_name = f"Status_{workflow_part}_{muni}_{date_part}.docx"
        default_path = str(self.tab.state.files_dir("Извештаји") / default_name)
        chosen, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export status report"), default_path,
            self.tr("Word files (*.docx)"),
        )
        if not chosen:
            return
        try:
            generate_status_report(
                self._persons, self.tab.state.oik, self.tab.state.election,
                chosen, spec=self.tab._spec,
            )
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Error"),
                self.tr("Cannot write report:\n{error}").format(error=e),
            )
            return
        self.tab.banner.show_ok(
            self.tr("Status report saved to: {path}").format(path=chosen)
        )


# ── Падежи места panel ────────────────────────────────────


class _PlacesPanel(QWidget):
    """One row per unique place in the master.

    Columns: Место (read-only), Аутоматски генитив (read-only), Корисничка
    измена (editable). The right-hand pane previews the sample sentence
    using the first filled person from the highlighted place so the user
    sees exactly what the решење will say.
    """

    HEADERS = [
        "Place", "Auto genitive", "User override", "Preposition",
    ]
    COL_PLACE = 0
    COL_RULE_GENITIVE = 1
    COL_USER_GENITIVE = 2
    COL_PREPOSITION = 3

    def __init__(self, tab: CorrectionsTab) -> None:
        super().__init__()
        self.tab = tab
        self._persons: list[Person] = []
        self._loading = False  # suppress itemChanged during refill

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # Left: places table
        left = QVBoxLayout()
        left.setSpacing(6)
        hint = QLabel(self.tr(
            'Edit the "User override" column to correct the auto-generated form.'
            ' The "Preposition" column accepts "из" (default) or "са"'
            ' (for mountains and heights: Авала, Цетиње, Уб...).'
            ' Entries are saved in places_genitive.json and places_prepositions.json'
            ' in the user folder and survive program updates.'
        ))
        hint.setWordWrap(True)
        hint.setObjectName("MutedLabel")
        left.addWidget(hint)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(self.tr("Search:")))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(self.tr("Type place name…"))
        self.ed_search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.ed_search, stretch=1)
        left.addLayout(search_row)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels([
            QCoreApplication.translate("_PlacesPanel", "Place"),
            QCoreApplication.translate("_PlacesPanel", "Auto genitive"),
            QCoreApplication.translate("_PlacesPanel", "User override"),
            QCoreApplication.translate("_PlacesPanel", "Preposition"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.resizeSection(self.COL_PLACE, 180)
        h.resizeSection(self.COL_RULE_GENITIVE, 200)
        h.resizeSection(self.COL_USER_GENITIVE, 200)
        h.resizeSection(self.COL_PREPOSITION, 70)
        h.setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._refresh_preview)
        left.addWidget(self.table, stretch=1)
        root.addLayout(left, stretch=2)

        # Right: live sentence preview
        right = QVBoxLayout()
        right.setSpacing(6)
        preview_title = QLabel(self.tr("Sample sentence"))
        preview_title.setObjectName("HeadLabel")
        right.addWidget(preview_title)
        self.preview_label = QLabel(self.tr("Select a place in the table."))
        self.preview_label.setObjectName("MutedLabel")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.preview_label)
        right.addStretch()
        root.addLayout(right, stretch=1)

    # ── Public ─────────────────────────────────────────

    def set_persons(self, persons: list[Person]) -> None:
        self._persons = persons
        self._reload_table()

    # ── Internal ───────────────────────────────────────

    def _unique_places(self) -> list[str]:
        """Distinct places, normalized (see `normalize_place_name`) so a
        party that typed "МИОНИЦА" and another that typed "Мионица"
        collapse into the same one row/override instead of two — this
        is also what made the all-caps row's genitive come out garbled
        in the first place (the rule engine's suffix matching is
        case-sensitive)."""
        seen: dict[str, None] = {}
        for p in self._persons:
            m = normalize_place_name((p.mesto or "").strip())
            if m and m not in seen:
                seen[m] = None
        return sorted(seen.keys())

    def _reload_table(self) -> None:
        self._loading = True
        try:
            overrides = load_overrides()
            prepositions = load_prepositions()
            places = self._unique_places()
            self.table.setRowCount(len(places))
            for r, place in enumerate(places):
                rule_genitive = self._rule_only_genitive(place)
                user_genitive = overrides.get(place, "")
                prep = prepositions.get(place, DEFAULT_PREPOSITION)

                place_item = QTableWidgetItem(place)
                place_item.setFlags(place_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, self.COL_PLACE, place_item)

                rule_item = QTableWidgetItem(rule_genitive)
                rule_item.setFlags(rule_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, self.COL_RULE_GENITIVE, rule_item)

                user_item = QTableWidgetItem(user_genitive)
                self.table.setItem(r, self.COL_USER_GENITIVE, user_item)

                prep_item = QTableWidgetItem(prep)
                self.table.setItem(r, self.COL_PREPOSITION, prep_item)
        finally:
            self._loading = False
        self._apply_filter()
        self._refresh_preview()

    def _apply_filter(self) -> None:
        """Show/hide rows based on the search bar text (substring match on place name)."""
        needle = self.ed_search.text().strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_PLACE)
            visible = not needle or (item is not None and needle in item.text().lower())
            self.table.setRowHidden(row, not visible)

    @staticmethod
    def _rule_only_genitive(place: str) -> str:
        """Compute the rule-engine output, bypassing the override file."""
        from biracki_odbor.config import declension as d
        if not place:
            return place
        tokens = place.strip().split()
        if len(tokens) >= 2:
            first = d._decline_adjective(tokens[0])
            rest = [d._decline_noun(t) for t in tokens[1:]]
            return " ".join([first] + rest)
        return d._decline_noun(place.strip())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        place = self.table.item(item.row(), self.COL_PLACE).text()
        new_value = item.text().strip()
        col = item.column()
        if col == self.COL_USER_GENITIVE:
            try:
                set_user_override(place, new_value)
            except OSError as e:
                QMessageBox.warning(self, self.tr("Error"), self.tr("Cannot write override: {error}").format(error=e))
                return
            self.tab.banner.show_ok(
                self.tr('Saved genitive for "{place}": {value}').format(place=place, value=new_value or "(deleted)")
            )
        elif col == self.COL_PREPOSITION:
            # Accept "из"/"са"; anything else silently normalizes to default.
            normalized = new_value if new_value in ("из", "са") else DEFAULT_PREPOSITION
            try:
                set_user_preposition(place, normalized)
            except OSError as e:
                QMessageBox.warning(self, self.tr("Error"), self.tr("Cannot write preposition: {error}").format(error=e))
                return
            if normalized != new_value:
                self._loading = True
                try:
                    item.setText(normalized)
                finally:
                    self._loading = False
            self.tab.banner.show_ok(
                self.tr('Saved preposition for "{place}": {prep}').format(place=place, prep=normalized)
            )
        else:
            return
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            self.preview_label.setText(self.tr("Select a place in the table."))
            return
        row = next(iter(rows))
        place_item = self.table.item(row, 0)
        if place_item is None:
            return
        place = place_item.text()
        # Table rows are normalized (see _unique_places) but a person's
        # own raw mesto may still be whatever casing the party typed —
        # normalize both sides or an all-caps submission would never
        # match its own (now-canonical) row.
        person = next(
            (p for p in self._persons
             if p.is_filled and normalize_place_name(p.mesto) == place),
            None,
        )
        if person is None:
            self.preview_label.setText(
                self.tr('No filled members from place "{place}".').format(place=place)
            )
            return
        # Mirror phase3 wording so the preview matches the actual решење line.
        gen = place_to_genitive(place)
        prep = place_preposition(place)
        proposal = ""
        if person.party or person.appointed_by_nacelnik:
            from biracki_odbor.core.phase3_docx import _proposal_text
            label, name = _proposal_text(
                person.party, self.tab.state.election,
                self.tab.state.oik.nacelnik_proposal_name,
                appointed_by_nacelnik=person.appointed_by_nacelnik,
            )
            if label and name:
                proposal = f", {label} {name}"
            elif label:
                proposal = f", {label}"
        sentence = f"{person.name} {prep} {gen}{proposal}."
        self.preview_label.setText(sentence)


# ── Edit dialog ───────────────────────────────────────────

# Common reasons a committee member's record gets edited/replaced.
# Not an exhaustive or locked list — the note field stays a free-typed
# combo box (editable=True) specifically so an operator can always type
# their own instead. "по члану 14. став 1. тачка 8)" is the чл. 15
# double-appointment scenario (see core.prestanak_docx) — selecting it
# reveals the BM/municipality fields below, since that reason needs to
# say WHERE the person is now also serving for the note to mean
# anything; the other reasons don't carry that extra context.
NOTE_REASON_CL_14_1_8 = "по члану 14. став 1. тачка 8)"
# Смрт / Неспособност / Губитак бирачког права come from core.izmene_docx —
# that's also where they gate the special чл. 41. ст. 2. izmena document
# track when the slot is председник/заменик председника, so the dropdown
# must offer the exact same strings the generator matches against.
NOTE_REASON_CHOICES = (
    NOTE_REASON_CL_14_1_8,
    "Исправка личних података",
    *CHAIRMAN_LAPSE_REASONS,
)


class _PersonEditDialog(QDialog):
    def __init__(
        self, person: Person, *, mode: str = "edit", spec=None, parent=None,
        other_workflow: list[Person] | None = None,
    ) -> None:
        super().__init__(parent)
        # The other composition's people: the committee DB rejects a JMBG
        # present in both (чл. 15), so catch it here with a clear message
        # instead of the raw database error on save.
        self._other_workflow = other_workflow or []
        self._other_is_prosireni = spec is None
        self.setWindowTitle(
            self.tr("Edit person") if mode == "edit" else self.tr("Replace person (illness/withdrawal)")
        )
        self.resize(520, 420)
        self._person = person

        layout = QVBoxLayout(self)

        ctx_msg = (
            self.tr("Slot: BM {bm}, {func}, list {party}") if spec is not None
            else self.tr("Slot: BM {bm}, {func}, party {party}")
        )
        ctx = QLabel(ctx_msg.format(bm=person.bm_number, func=person.function, party=person.party))
        ctx.setObjectName("MutedLabel")
        layout.addWidget(ctx)

        form = QFormLayout()
        self.ed_first_name = QLineEdit(person.first_name if mode == "edit" else "")
        self.ed_last_name = QLineEdit(person.last_name if mode == "edit" else "")
        self.ed_jmbg = QLineEdit(person.jmbg if mode == "edit" else "")
        self.ed_mesto = QLineEdit(person.mesto if mode == "edit" else "")
        self.ed_adresa = QLineEdit(person.adresa if mode == "edit" else "")
        self.ed_telefon = QLineEdit(person.telefon if mode == "edit" else "")
        self.ed_email = QLineEdit(person.email if mode == "edit" else "")
        form.addRow(self.tr("First name:"), self.ed_first_name)
        form.addRow(self.tr("Last name:"), self.ed_last_name)
        form.addRow(self.tr("JMBG:"), self.ed_jmbg)
        form.addRow(self.tr("Place:"), self.ed_mesto)
        form.addRow(self.tr("Address:"), self.ed_adresa)
        form.addRow(self.tr("Phone:"), self.ed_telefon)
        form.addRow(self.tr("Email:"), self.ed_email)
        layout.addLayout(form)

        layout.addWidget(QLabel(self.tr("Note (required):")))
        self.ed_note = QComboBox()
        self.ed_note.setEditable(True)
        self.ed_note.addItem("")
        for reason in NOTE_REASON_CHOICES:
            self.ed_note.addItem(reason)
        self.ed_note.setCurrentIndex(0)
        layout.addWidget(self.ed_note)

        # Only meaningful for the чл. 14(1)(8) reason — the note has to
        # say WHERE the person is now also serving, or it doesn't
        # explain anything. Hidden otherwise; shown/required together.
        self._other_appointment_row = QFormLayout()
        self.ed_other_bm = QLineEdit()
        self.ed_other_bm.setPlaceholderText(self.tr("e.g. 5"))
        self.ed_other_mun = QLineEdit()
        self.ed_other_mun.setPlaceholderText(self.tr("e.g. Ваљево"))
        self.ed_other_broj = QLineEdit()
        self.ed_other_broj.setPlaceholderText(self.tr("e.g. 013-5-30-1/2026"))
        self._other_appointment_row.addRow(
            self.tr("BM (other appointment):"), self.ed_other_bm,
        )
        self._other_appointment_row.addRow(
            self.tr("Municipality (other appointment):"), self.ed_other_mun,
        )
        self._other_appointment_row.addRow(
            self.tr("Decision number (other appointment):"), self.ed_other_broj,
        )
        layout.addLayout(self._other_appointment_row)
        self._set_other_appointment_visible(False)
        self.ed_note.currentTextChanged.connect(self._on_note_reason_changed)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Прихвати")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _set_other_appointment_visible(self, visible: bool) -> None:
        for i in range(self._other_appointment_row.rowCount()):
            label_item = self._other_appointment_row.itemAt(i, QFormLayout.LabelRole)
            field_item = self._other_appointment_row.itemAt(i, QFormLayout.FieldRole)
            if label_item and label_item.widget():
                label_item.widget().setVisible(visible)
            if field_item and field_item.widget():
                field_item.widget().setVisible(visible)

    def _on_note_reason_changed(self, text: str) -> None:
        self._set_other_appointment_visible(text.strip() == NOTE_REASON_CL_14_1_8)

    def _on_accept(self) -> None:
        note_text = self.ed_note.currentText().strip()
        if not note_text:
            QMessageBox.warning(
                self, self.tr("Note required"),
                self.tr("Enter a note before confirming. The note is required for the audit trail."),
            )
            return
        if note_text == NOTE_REASON_CL_14_1_8 and not (
            self.ed_other_bm.text().strip() and self.ed_other_mun.text().strip()
        ):
            QMessageBox.warning(
                self, self.tr("Other appointment required"),
                self.tr(
                    "Enter the BM and municipality where this person is now"
                    " also serving — \"{reason}\" doesn't explain anything"
                    " without them."
                ).format(reason=NOTE_REASON_CL_14_1_8),
            )
            return
        if not validators.is_valid_jmbg(self.ed_jmbg.text()):
            QMessageBox.warning(
                self, self.tr("Invalid JMBG"),
                self.tr("JMBG must be 13 digits and pass the MOD 11 checksum."),
            )
            return
        jmbg = self.ed_jmbg.text().strip()
        clash = next((o for o in self._other_workflow if o.is_filled and o.jmbg == jmbg), None)
        if clash is not None:
            composition = (
                self.tr("the extended composition") if self._other_is_prosireni
                else self.tr("the permanent composition")
            )
            QMessageBox.warning(
                self, self.tr("JMBG already used"),
                self.tr(
                    "This JMBG already belongs to {name} in {composition}"
                    " (BM {bm}, {func}). The same person cannot serve in both"
                    " compositions (Article 15 of the Law).\n\n"
                    "Correct the JMBG, or first remove that person from {composition}."
                ).format(
                    name=f"{clash.first_name} {clash.last_name}".strip(),
                    composition=composition, bm=clash.bm_number, func=clash.function,
                ),
            )
            return
        if not validators.is_valid_phone(self.ed_telefon.text()):
            QMessageBox.warning(
                self, self.tr("Invalid phone number"),
                self.tr("Phone number may contain only digits (spaces, dashes and slashes are removed automatically)."),
            )
            return
        if not validators.is_valid_email(self.ed_email.text()):
            QMessageBox.warning(
                self, self.tr("Invalid email"),
                self.tr("Enter a valid email address (e.g. name@example.com), or leave it blank."),
            )
            return
        self.accept()

    def values(self) -> dict:
        return {
            "first_name": self.ed_first_name.text(),
            "last_name": self.ed_last_name.text(),
            "jmbg": self.ed_jmbg.text(),
            "mesto": self.ed_mesto.text(),
            "adresa": self.ed_adresa.text(),
            "telefon": phone_normalize(self.ed_telefon.text()),
            "email": self.ed_email.text(),
        }

    def note(self) -> str:
        text = self.ed_note.currentText().strip()
        if text == NOTE_REASON_CL_14_1_8:
            bm = self.ed_other_bm.text().strip()
            mun = self.ed_other_mun.text().strip()
            if bm and mun:
                text += (
                    f" — изабран за члана бирачког одбора на бирачком"
                    f" месту број {bm} у општини {mun}"
                )
        return text

    def other_bm(self) -> int | None:
        """The other appointment's BM number, when the чл. 14(1)(8) reason
        is selected — real field alongside `note()`'s free-text sentence,
        so the Измене tab's Престанак track can detect and pre-fill from
        it without parsing that sentence back apart."""
        if self.ed_note.currentText().strip() != NOTE_REASON_CL_14_1_8:
            return None
        try:
            return int(self.ed_other_bm.text().strip())
        except ValueError:
            return None

    def other_municipality(self) -> str:
        if self.ed_note.currentText().strip() != NOTE_REASON_CL_14_1_8:
            return ""
        return self.ed_other_mun.text().strip()

    def other_decision_broj(self) -> str:
        """Optional — unlike BM/municipality, not required to accept the
        dialog, since the operator may not have this on hand yet when
        first flagging the person."""
        if self.ed_note.currentText().strip() != NOTE_REASON_CL_14_1_8:
            return ""
        return self.ed_other_broj.text().strip()


# ── Načelnik inbox picker ─────────────────────────────────


class _NacelnikInboxPickerDialog(QDialog):
    """List inbox messages with xlsx attachments; let operator pick one.

    On Accepted, ``chosen_path`` points to the saved temp file ready
    for ``_import_from_path()``.
    """

    def __init__(self, messages: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Select Excel file from inbox"))
        self.resize(640, 380)
        self.chosen_path = None
        self._messages = messages
        self._attachments: list = []  # flat list of (InboxAttachment, InboxMessage)

        layout = QVBoxLayout(self)

        hint = QLabel(self.tr(
            "Excel messages found in inbox. Double-click a row to import the attachment."
        ))
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lst = QListWidget()
        self.lst.setAlternatingRowColors(True)
        for msg in messages:
            for att in msg.attachments:
                item = QListWidgetItem(
                    f"{msg.sender_name} <{msg.sender_email}> — "
                    f"{msg.subject or self.tr('(no subject)')}  ·  {att.name}"
                )
                item.setToolTip(
                    f"{self.tr('Sender')}: {msg.sender_name} <{msg.sender_email}>\n"
                    f"{self.tr('Subject')}: {msg.subject}\n"
                    f"{self.tr('Received')}: {msg.received_time}\n"
                    f"{self.tr('Attachment')}: {att.name}  ({att.size // 1024 + 1} KB)"
                )
                self.lst.addItem(item)
                self._attachments.append((att, msg))
        self.lst.doubleClicked.connect(self._accept_selection)
        layout.addWidget(self.lst, stretch=1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Увези изабрано")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self._accept_selection)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _accept_selection(self) -> None:
        row = self.lst.currentRow()
        if row < 0:
            return
        att, _msg = self._attachments[row]
        import tempfile
        from pathlib import Path as _Path
        tmp = _Path(tempfile.mkstemp(suffix=".xlsx", prefix="nacelnik_inbox_")[1])
        try:
            att.save_to(tmp)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox as _MB
            _MB.critical(self, self.tr("Error"), self.tr("Cannot save attachment:\n{error}").format(error=exc))
            return
        self.chosen_path = tmp
        self.accept()
