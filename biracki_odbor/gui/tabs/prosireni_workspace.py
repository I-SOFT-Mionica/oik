"""Проширени састав workspace — three-phase workflow tabs.

Phase 1: Generate per-entity Excel popunjeni templates from the
         candidacies registry (entities entered under Избори → Кандидати).
Phase 2: Aggregate submitted entity files → prosireni master.xlsx.
Phase 3: Generate prosireni Word решења per БМ.

All three phases call the existing phase functions with spec=PROSIRENI_SPEC.
No election template file is needed — the allocation is computed from the
candidacies registry at runtime.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.core.corrections import append_late_submission_blocked
from biracki_odbor.core.workflow import PROSIRENI_SPEC
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.tabs.corrections import CorrectionsTab
from biracki_odbor.gui.tabs.phase1 import ProsireniPhase1Tab
from biracki_odbor.gui.tabs.phase3 import Phase3Tab
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.error_table import ErrorTable
from biracki_odbor.gui.worker import start_worker
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation import preflight


log = logging.getLogger(__name__)


# ── Phase 1 — ProsireniPhase1Tab lives in phase1.py ──────────────────


# ── Phase 2 ───────────────────────────────────────────────────────────


class _ProsireniPhase2Tab(QWidget):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel(self.tr("Aggregation"))
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        hint = QLabel(
            self.tr(
                "1. Import filled-in .xlsx files from entities.\n"
                "2. Run Phase 2 — the program aggregates them into the master table\n"
                "   ({master})."
            ).format(master=app_paths.master_path_for(PROSIRENI_SPEC).name)
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.banner = StatusBanner()
        root.addWidget(self.banner)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        btn_row = QHBoxLayout()

        self.btn_import = QPushButton(self.tr("Import files…"))
        self.btn_import.clicked.connect(self._import_files)
        btn_row.addWidget(self.btn_import)

        from biracki_odbor.integrations import email_client as _ec_mod
        self.btn_outlook = QPushButton(self.tr("Receive"))
        self.btn_outlook.setToolTip(
            self.tr(
                "Import from email. Browses the inbox of the selected email"
                " client (Outlook / Thunderbird) and imports .xlsx"
                " attachments with official receipt timestamps."
            )
        )
        self.btn_outlook.clicked.connect(self._import_outlook)
        self.btn_outlook.setVisible(_ec_mod.any_inbox_available())
        btn_row.addWidget(self.btn_outlook)

        self.btn_run = QPushButton(self.tr("Run"))
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run)
        btn_row.addWidget(self.btn_run)

        self.btn_open = QPushButton(self.tr("Open master table…"))
        self.btn_open.clicked.connect(self._open_master)
        self.btn_open.setEnabled(False)
        btn_row.addWidget(self.btn_open)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.error_table = ErrorTable()
        root.addWidget(self.error_table, stretch=1)

        self.state.generation_log_changed.connect(self._restore_master_btn)
        self.state.election_changed.connect(self._restore_master_btn)
        self._restore_master_btn()

    @log_timing("ProsireniWorkspace._restore_master_btn")
    def _restore_master_btn(self) -> None:
        """Enable «Отвори збирну табелу» if проширени has any aggregated data.

        Field report: used to ALSO rebuild a full export_master_xlsx copy
        on every call -- see Phase2Tab._restore_master_btn's identical fix
        for the measured cost (confirmed 103-105ms here, same root cause:
        fires on every election_changed/generation_log_changed cascade,
        connected to both independently so it ran twice per edit). The
        rebuild was always redundant here too: _run() (Phase 2 actually
        completing, line ~479 below) already regenerates this exact
        export right after aggregation, the only time the underlying
        data can actually change.
        """
        from biracki_odbor.core.master_io import read_master
        persons = read_master(app_paths.master_path_for(PROSIRENI_SPEC), spec=PROSIRENI_SPEC)
        self.btn_open.setEnabled(bool(persons))

    def _import_files(self) -> None:
        import os
        from PySide6.QtWidgets import QFileDialog
        from biracki_odbor.core import popunjeni_io, popunjeni_cache

        paths, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Import entity files"),
            str(self.state.files_dir("Странке (проширени)")),
            "Excel (*.xlsx)",
        )
        if not paths:
            return

        election = self.state.election
        election_uuid = election.election_uuid.strip() if election else ""
        if not election_uuid:
            QMessageBox.warning(
                self, self.tr("Import"),
                self.tr(
                    "Election configuration has no identifier set."
                    " Save the election configuration and try again."
                ),
            )
            return

        popunjeni_dir = app_paths.popunjeni_dir_for(PROSIRENI_SPEC)
        cache_data = popunjeni_cache.load(election_uuid=election_uuid)
        imported = 0
        rejected: list[tuple[str, str]] = []
        new_issues = []
        operator = os.environ.get("USERNAME") or os.environ.get("USER") or ""

        for p in paths:
            src = Path(p)
            outcome = popunjeni_io.import_file(
                src, election, popunjeni_dir,
                phase1_run_ts=self.state.generation_log.prosireni.phase1_run_ts,
            )
            if outcome.status == "imported":
                imported += 1
            elif outcome.issue is not None:
                rejected.append((src.name, outcome.issue.message_sr))
                new_issues.append(outcome.issue)
                log.warning(
                    "Prosireni import rejected: %s — code=%s — %s",
                    src.name, outcome.issue.code, outcome.issue.message_sr,
                )
            if outcome.ok and outcome.canonical_path is not None:
                # Cutoff warning for file-dialog imports (operator override).
                cutoff_prosireni = self.state.election.election.dates.cutoff_prosireni
                if cutoff_prosireni:
                    recv_date = (outcome.received_time_iso or "")[:10]
                    if recv_date and recv_date > cutoff_prosireni:
                        ans = QMessageBox.question(
                            self,
                            self.tr("Late submission"),
                            self.tr(
                                "File «{name}» has a timestamp of {recv_date},"
                                " but the submission deadline for the extended"
                                " composition has passed on {cutoff}.\n\n"
                                "You may continue if you are certain the entity"
                                " submitted the file on time through a non-email"
                                " channel.\n\n"
                                "Do you want to continue with the import?"
                            ).format(
                                name=src.name,
                                recv_date=recv_date,
                                cutoff=cutoff_prosireni,
                            ),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if ans != QMessageBox.StandardButton.Yes:
                            odbijeno = app_paths.popunjeni_odbijeno_dir_for(PROSIRENI_SPEC)
                            dest_late = odbijeno / outcome.canonical_path.name
                            outcome.canonical_path.rename(dest_late)
                            append_late_submission_blocked(
                                app_paths.corrections_log_path_for(PROSIRENI_SPEC),
                                outcome.canonical_path.name,
                                outcome.party,
                                outcome.received_time_iso,
                                cutoff_prosireni,
                                source="file_dialog",
                            )
                            reason = self.tr(
                                "Late submission ({recv_date} > {cutoff})."
                                " Rejected at operator request."
                            ).format(recv_date=recv_date, cutoff=cutoff_prosireni)
                            rejected.append((src.name, reason))
                            imported -= 1
                            continue

                records, issues = popunjeni_io.parse_for_cache(outcome.canonical_path)
                new_issues.extend(issues)
                cache_data.entries[str(outcome.canonical_path)] = (
                    popunjeni_cache.CacheEntry.from_parsed(
                        outcome.canonical_path, records, issues,
                        received_time_iso=outcome.received_time_iso,
                        import_source=outcome.import_source,
                        party=outcome.party,
                        imported_by=operator,
                    )
                )

        popunjeni_cache.save(cache_data)
        log.info("Prosireni import: %d imported, %d rejected", imported, len(rejected))

        if rejected:
            from biracki_odbor.core.models import ValidationReport
            report = ValidationReport()
            for issue in new_issues:
                report.add(issue)
            self.error_table.set_report(report)
            self.banner.show_warn(
                self.tr("Imported: {imported}, rejected {rejected}."
                        " See details in the error table.").format(
                    imported=imported, rejected=len(rejected)
                )
            )
            details = "\n\n".join(f"• {n}\n  {reason}" for n, reason in rejected)
            QMessageBox.warning(
                self, self.tr("Import — rejected files"),
                self.tr("{n} file(s) rejected during import:\n\n{details}").format(
                    n=len(rejected), details=details
                ),
            )
        else:
            self.banner.show_ok(
                self.tr("Imported: {n} submissions.").format(n=imported)
            )

    def _import_outlook(self) -> None:
        """Browse Outlook Inbox with the prosireni subject token, import attachments."""
        from biracki_odbor.gui.dialogs.inbox_picker import InboxPickerDialog
        from biracki_odbor.integrations import email_client as ec_mod
        from biracki_odbor.core import popunjeni_io, popunjeni_cache
        import tempfile

        election = self.state.election
        election_uuid = election.election_uuid.strip() if election else ""
        if not election_uuid:
            QMessageBox.warning(
                self, self.tr("Import"),
                self.tr(
                    "Election configuration has no identifier set."
                    " Save the election configuration and try again."
                ),
            )
            return

        subject_token = election.election.dates.subject_token_for("prosireni")
        try:
            messages = ec_mod.fetch_inbox_messages(
                preference=self.state.app_settings.email_client,
                since_days=14, only_xlsx=True,
                subject_contains=subject_token,
                account_email=self.state.app_settings.oik_email,
            )
        except ec_mod.InboxBackendUnavailable as e:
            QMessageBox.warning(
                self, self.tr("Email client unavailable"),
                self.tr("{error}\n\nUse 'Import files…' to manually select .xlsx files.").format(
                    error=e
                ),
            )
            return
        except Exception as e:  # noqa: BLE001
            log.exception("Prosireni inbox fetch failed")
            QMessageBox.critical(
                self, self.tr("Error reading Inbox"),
                self.tr("Error reading Inbox:\n\n{error}").format(error=e),
            )
            return

        cutoff = self.state.election.election.dates.cutoff_prosireni
        from biracki_odbor.integrations.thunderbird import find_imap_offline_gaps
        imap_gaps = find_imap_offline_gaps(self.state.app_settings.oik_email) if not messages else []
        dlg = InboxPickerDialog(messages, parent=self, cutoff_date=cutoff, imap_gaps=imap_gaps)
        from PySide6.QtWidgets import QDialog as _QD
        if dlg.exec() != _QD.Accepted:
            return
        picks = dlg.picked()
        if not picks:
            return

        popunjeni_dir = app_paths.popunjeni_dir_for(PROSIRENI_SPEC)
        cache_data = popunjeni_cache.load(election_uuid=election_uuid)
        imported = 0
        rejected: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory(prefix="outlook_prosireni_") as staging:
            staging_path = Path(staging)
            for pick in picks:
                dest = staging_path / pick.attachment.name
                try:
                    pick.attachment.save_to(dest)
                except Exception as e:  # noqa: BLE001
                    log.warning("Outlook prosireni: cannot save %s (%s)", pick.attachment.name, e)
                    rejected.append((pick.attachment.name, f"Outlook: {e}"))
                    continue
                outcome = popunjeni_io.import_file(
                    dest, election, popunjeni_dir,
                    received_at=pick.received_time,
                    source="outlook",
                    phase1_run_ts=self.state.generation_log.prosireni.phase1_run_ts,
                )
                if outcome.status == "imported":
                    imported += 1
                elif outcome.issue is not None:
                    rejected.append((pick.attachment.name, outcome.issue.message_sr))
                if outcome.ok and outcome.canonical_path is not None:
                    # Hard block: email received after the prošireni submission cutoff.
                    if cutoff:
                        recv_date = (outcome.received_time_iso or "")[:10]
                        if recv_date and recv_date > cutoff:
                            odbijeno = app_paths.popunjeni_odbijeno_dir_for(PROSIRENI_SPEC)
                            dest_late = odbijeno / outcome.canonical_path.name
                            outcome.canonical_path.rename(dest_late)
                            append_late_submission_blocked(
                                app_paths.corrections_log_path_for(PROSIRENI_SPEC),
                                outcome.canonical_path.name,
                                outcome.party,
                                outcome.received_time_iso,
                                cutoff,
                                source="outlook",
                            )
                            reason = self.tr(
                                "Email received {recv_date} — deadline passed on {cutoff}."
                                " File moved to rejected folder."
                            ).format(recv_date=recv_date, cutoff=cutoff)
                            rejected.append((pick.attachment.name, reason))
                            imported -= 1
                            continue

                    records, issues = popunjeni_io.parse_for_cache(outcome.canonical_path)
                    cache_data.entries[str(outcome.canonical_path)] = (
                        popunjeni_cache.CacheEntry.from_parsed(
                            outcome.canonical_path, records, issues,
                            received_time_iso=outcome.received_time_iso,
                            import_source=outcome.import_source,
                            party=outcome.party,
                        )
                    )
        popunjeni_cache.save(cache_data)

        if rejected:
            details = "\n\n".join(f"• {n}\n  {r}" for n, r in rejected)
            QMessageBox.warning(
                self, self.tr("Import from email — rejected attachments"),
                self.tr("{n} attachment(s) rejected:\n\n{details}").format(
                    n=len(rejected), details=details
                ),
            )
            self.banner.show_warn(
                self.tr("From email imported: {imported}, rejected {rejected}.").format(
                    imported=imported, rejected=len(rejected)
                )
            )
        else:
            self.banner.show_ok(
                self.tr("From email imported {n} submissions.").format(n=imported)
            )

    def _run(self) -> None:
        election = self.state.election
        oik = self.state.oik

        issues = preflight.check_oik(oik)
        if issues:
            self.banner.show_error("; ".join(i.message_sr for i in issues))
            return

        registry = getattr(election, "candidacies", None)
        if registry is None or not registry.entities:
            self.banner.show_error(
                self.tr("Candidacy registry is empty — no lists to aggregate.")
            )
            return

        bm_numbers = [ps.bm_number for ps in oik.polling_stations]
        if not bm_numbers:
            self.banner.show_error(
                self.tr("No polling stations in OIK settings.")
            )
            return

        popunjeni_dir = app_paths.popunjeni_dir_for(PROSIRENI_SPEC)
        master_out = app_paths.master_path_for(PROSIRENI_SPEC)

        from biracki_odbor.core.prosireni_allocation import build_prosireni_allocation
        allocs = build_prosireni_allocation(registry, bm_numbers)
        # canonical_slots() (called by build_prosireni_allocation) may
        # have just assigned slot_index to an entity that has never
        # been through Phase 1 -- persist immediately so the number
        # stays stable even if this ends up being the first place it
        # was ever computed (see Entity.slot_index's docstring).
        self.state.save_election()

        self.banner.hide()
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        # NOT .clear() -- that also wipes the header labels ErrorTable
        # set at construction time (nothing restores them afterward),
        # leaving Qt's default numeric "1 2 3 4 5" column headers after
        # the first run. setRowCount(0) only removes rows, matching the
        # same clear-before-refresh pattern ErrorTable.set_report() uses.
        self.error_table.setRowCount(0)

        from biracki_odbor.core.phase2_aggregate import aggregate_party_files
        self._worker, self._thread = start_worker(
            self, aggregate_party_files,
            input_dir=popunjeni_dir,
            template_path=None,
            output_path=master_out,
            oik=oik,
            election=election,
            spec=PROSIRENI_SPEC,
            allocations_override=allocs,
        )
        # Bound methods, not local closures — a signal connected to a
        # bare local function/closure (no QObject anchoring its
        # lifetime) silently failed to fire here: worker.finished.emit()
        # returned normally but the slot never actually ran, leaving the
        # progress bar and Покрени button stuck even though the
        # underlying aggregate_party_files call (and its file write)
        # had already completed successfully on the worker thread.
        # Matches the working stalni Phase2Tab pattern.
        self._worker.finished.connect(self._on_phase2_finished)
        self._worker.failed.connect(self._on_phase2_failed)

    def _on_phase2_finished(self, result: object) -> None:
        from biracki_odbor.core.phase2_aggregate import Phase2Result
        assert isinstance(result, Phase2Result)
        master_out = app_paths.master_path_for(PROSIRENI_SPEC)
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_open.setEnabled(True)
        if master_out.exists():
            # Re-fingerprint the working master right after our own
            # write, same as the stalni Phase2Tab — see
            # core/file_integrity.py.
            from biracki_odbor.core import file_integrity
            file_integrity.record_verified(master_out)
        if result.persons:
            from biracki_odbor.core.master_io import export_master_xlsx
            export_path = self.state.files_dir("Извештаји") / PROSIRENI_SPEC.paths.master_filename
            try:
                export_master_xlsx(result.persons, self.state.oik, export_path, spec=PROSIRENI_SPEC)
            except OSError:
                pass  # best-effort, matches export_generated's own failure handling
        self.state.prosireni_master_changed.emit()
        if result.files_processed > 0:
            self.state.generation_log.record_phase("prosireni", "phase2")
            self.state.save_generation_log()
        if result.report.ok:
            self.banner.show_ok(
                self.tr("Aggregated {n} files → {master}.").format(
                    n=result.files_processed, master=master_out.name
                )
            )
        else:
            self.banner.show_warn(
                self.tr("Aggregated with warnings ({n} files).").format(
                    n=result.files_processed
                )
            )
        self.error_table.set_report(result.report)

    def _on_phase2_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.banner.show_error(self.tr("Error: {exc}").format(exc=err))
        log.exception("prosireni phase2 failed: %s", err)

    def _open_master(self) -> None:
        # Opens the exported .xlsx copy in files_dir("Извештаји"), not the
        # internal working master (a SQLite DB now, not something to open
        # directly) — editing the copy can't corrupt the data Phase 3/audit
        # rely on. Same reasoning as Phase2Tab's _export_master.
        p = self.state.files_dir("Извештаји") / PROSIRENI_SPEC.paths.master_filename
        if p.exists():
            os.startfile(str(p))  # noqa: S606


# ── Workspace container ───────────────────────────────────────────────


class ProsireniWorkspace(QWidget):
    """Top-level widget for the Проширени состав sidebar section.

    Five tabs: Листе → Обједињавање → Корекције → Решења → Измене.
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Replaces the old dead sidebar button: Проширени is reachable
        # whenever onboarding is done, and the fact that no lists are
        # registered yet is stated here instead of being hidden in a
        # tooltip on a button that could not be clicked.
        self.lists_banner = StatusBanner()
        root.addWidget(self.lists_banner)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.addTab(ProsireniPhase1Tab(state), self.tr("1. Templates"))
        self.tabs.addTab(_ProsireniPhase2Tab(state), self.tr("2. Aggregation"))
        self.prosireni_corrections_tab = CorrectionsTab(state, spec=PROSIRENI_SPEC)
        self.tabs.addTab(self.prosireni_corrections_tab, self.tr("3. Corrections"))
        self.tabs.addTab(Phase3Tab(state, spec=PROSIRENI_SPEC), self.tr("4. Decisions"))

        from biracki_odbor.gui.tabs.izmene import IzmenaPanel
        from biracki_odbor.core.workflow import PROSIRENI_SPEC as _PROSIRENI_SPEC

        def _navigate_to_corrections(jmbg: str) -> None:
            self.tabs.setCurrentIndex(2)
            self.prosireni_corrections_tab.set_search(jmbg)

        self.tabs.addTab(
            IzmenaPanel(_PROSIRENI_SPEC, state, _navigate_to_corrections),
            self.tr("5. Amendments"),
        )

        root.addWidget(self.tabs)

        state.generation_log_changed.connect(self._refresh_tab_states)
        state.election_changed.connect(self._refresh_tab_states)
        state.election_changed.connect(self._refresh_lists_hint)
        self._refresh_tab_states()
        self._refresh_lists_hint()

    @log_timing("ProsireniWorkspace._refresh_lists_hint")
    def _refresh_lists_hint(self) -> None:
        """Non-blocking notice when the candidacy registry is still empty.

        The section stays reachable on purpose — проширени needs neither
        стални nor the РИК матрица, so an operator can open it and work
        through the setup before the lists are certified. The phases
        themselves still refuse to run without a registry; see
        ProsireniPhase1Tab._preflight_check and _ProsireniPhase2Tab._run.
        """
        registry = getattr(self.state.election, "candidacies", None)
        if registry is not None and registry.entities:
            self.lists_banner.clear()
            return
        self.lists_banner.show_warn(self.tr(
            "No electoral lists are registered yet. Phases 1 and 2 cannot run"
            " until at least one list is added under Elections → Candidates."
        ))

    @log_timing("ProsireniWorkspace._refresh_tab_states")
    def _refresh_tab_states(self) -> None:
        """Once prosireni izmena_mode activates (decisions submitted to
        RIK), disable Templates (0), Aggregation (1), and Decisions (3) --
        none of them are needed for the rest of this cycle, further
        changes go through Corrections (2) -> Amendments (4)."""
        gl = self.state.generation_log
        izmena_mode = gl.is_izmena_mode("prosireni")
        tooltip = self.tr(
            "Decisions have been submitted to RIK."
            " Further corrections are made through Corrections (auto-generate amendments)."
        ) if izmena_mode else ""
        for idx in (0, 1, 3):
            self.tabs.setTabEnabled(idx, not izmena_mode)
            self.tabs.setTabToolTip(idx, tooltip)
        if izmena_mode and self.tabs.currentIndex() in (0, 1, 3):
            self.tabs.setCurrentIndex(2)
