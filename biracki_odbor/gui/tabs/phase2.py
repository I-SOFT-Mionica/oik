"""Фаза 2: обједињавање попуњених фајлова странака."""

from __future__ import annotations

import logging
import os

from pathlib import Path

from PySide6.QtCore import Signal

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.config import declension
from biracki_odbor.core import popunjeni_cache, popunjeni_io
from biracki_odbor.core.corrections import (
    append_late_submission_blocked,
    append_reply_email_sent,
    append_submission_superseded,
    count_party_corrections,
    errors_by_jmbg,
)
from biracki_odbor.core.master_io import read_master
from biracki_odbor.core.models import Person
from biracki_odbor.core.phase2_aggregate import Phase2Result, aggregate_party_files
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.error_table import ErrorTable
from biracki_odbor.gui.worker import start_worker
from biracki_odbor.integrations import outlook as outlook_mod
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation import preflight


log = logging.getLogger(__name__)


def _current_operator() -> str:
    """Operator-name for cache provenance — same source corrections.py uses."""
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


class Phase2Tab(QWidget):
    # Emitted after an import batch with the number of files accepted
    # (the guided tour waits on it after «Fill with sample data»).
    imported = Signal(int)

    _template_integrity_error = None  # set by _template_path(), read by _refresh_preflight

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.last_result: Phase2Result | None = None
        # JMBG → list[Issue] index built from the last Phase 2 run —
        # feeds the reply-email / export-errors actions below.
        self._errors_by_jmbg: dict[str, list] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel(self.tr("Consolidation"))
        title.setObjectName("TitleLabel")
        root.addWidget(title)

        steps = QLabel(
            self.tr(
                "1. Click 'Import files…' and select the completed .xlsx files"
                " from parties (directly from email attachments).\n"
                "2. The program recognizes each file by its embedded identifier and saves"
                " it under the canonical name in {popunjeni_dir}.\n"
                "3. Run Phase 2 (the template is taken from OIK Settings)."
            ).format(popunjeni_dir=app_paths.popunjeni_dir())
        )
        steps.setObjectName("MutedLabel")
        steps.setWordWrap(True)
        root.addWidget(steps)

        self.lbl_template = QLabel()
        self.lbl_template.setWordWrap(True)
        root.addWidget(self.lbl_template)

        # Cutoff date reminder — shows election-specific deadline when set.
        self.lbl_cutoff = QLabel()
        self.lbl_cutoff.setObjectName("MutedLabel")
        self.lbl_cutoff.setWordWrap(True)
        root.addWidget(self.lbl_cutoff)

        self.banner = StatusBanner()
        root.addWidget(self.banner)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.errors = ErrorTable()
        root.addWidget(self.errors)

        # Error-report actions — visible/enabled only while there's at
        # least one error from the last Phase 2 run. Placed right under
        # the error table so the "return to sender" loop happens where
        # the errors were actually found.
        error_actions_row = QHBoxLayout()
        self.btn_reply_email = QPushButton(self.tr("Compose reply email…"))
        self.btn_reply_email.setToolTip(self.tr(
            "Draft one correction-request email per party that has errors"
            " in the last Phase 2 import, listing each error and attaching"
            " that party's originally submitted file."
        ))
        self.btn_reply_email.setEnabled(False)
        self.btn_reply_email.clicked.connect(self._on_compose_reply_email)
        error_actions_row.addWidget(self.btn_reply_email)

        self.btn_export_errors = QPushButton(self.tr("Export errors…"))
        self.btn_export_errors.setToolTip(self.tr(
            "Export only the rows currently flagged with an error to a"
            " standalone Excel file."
        ))
        self.btn_export_errors.setEnabled(False)
        self.btn_export_errors.clicked.connect(self._on_export_errors)
        error_actions_row.addWidget(self.btn_export_errors)
        error_actions_row.addStretch()
        root.addLayout(error_actions_row)

        btns = QHBoxLayout()
        self.btn_import = QPushButton(self.tr("Import files…"))
        self.btn_import.clicked.connect(self._on_import)
        btns.addWidget(self.btn_import)
        self.btn_sample = QPushButton(self.tr("Fill with sample data"))
        self.btn_sample.setToolTip(self.tr(
            "Demo only: fills the party files generated in step 1 with"
            " fictional people (including two deliberate conflicts) and"
            " imports them, so you can try the rest of the workflow on your"
            " own polling stations and parties."
        ))
        self.btn_sample.clicked.connect(self._on_fill_sample)
        btns.addWidget(self.btn_sample)
        # Inbox import — visible when at least one backend can read
        # mail (Outlook COM OR Thunderbird with a discovered profile).
        # The actual backend is picked at click time from the
        # AppSettings.email_client preference via the dispatcher.
        from biracki_odbor.integrations import email_client as _ec_mod
        self.btn_import_outlook = QPushButton(self.tr("Receive"))
        self.btn_import_outlook.setToolTip(
            self.tr(
                "Import from email. Scans the inbox of the selected email"
                " client (Outlook / Thunderbird) and imports .xlsx"
                " attachments with the official received timestamp."
            )
        )
        self.btn_import_outlook.clicked.connect(self._on_import_outlook)
        self.btn_import_outlook.setVisible(_ec_mod.any_inbox_available())
        btns.addWidget(self.btn_import_outlook)
        btns.addStretch()
        # Used to «Отвори збирну табелу…» which launched Excel against
        # the working master — too risky (operator could silently edit
        # headers / drop rows / introduce formulas the rest of the
        # workflow can't see). Now exports a fresh copy to a chosen
        # path, leaving master/zbirana_tabela.xlsx untouched.
        self.btn_open_master = QPushButton(self.tr("Export consolidated table…"))
        self.btn_open_master.setToolTip(
            self.tr(
                "Saves a copy of the consolidated table to a path you choose."
                " The working copy in master/ is left untouched."
            )
        )
        self.btn_open_master.clicked.connect(self._export_master)
        self.btn_open_master.setEnabled(False)
        btns.addWidget(self.btn_open_master)
        self.btn_run = QPushButton(self.tr("Run"))
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run)
        btns.addWidget(self.btn_run)
        root.addLayout(btns)

        self.state.oik_changed.connect(self._refresh_preflight)
        self.state.template_changed.connect(self._refresh_preflight)
        self.state.election_changed.connect(self._refresh_cutoff_label)
        self.state.generation_log_changed.connect(self._restore_master_btn)
        self.state.election_changed.connect(self._restore_master_btn)
        self.state.generation_log_changed.connect(self._refresh_nacelnik_gate)
        self.state.license_changed.connect(self._refresh_sample_btn)
        self._refresh_sample_btn()
        self._refresh_preflight()
        self._refresh_cutoff_label()
        self._restore_master_btn()
        self._refresh_nacelnik_gate()

    @log_timing("Phase2Tab._restore_master_btn")
    def _restore_master_btn(self) -> None:
        """Enable «Извези збирну табелу» if стални has any aggregated data.

        Field report: this used to ALSO rebuild a full export_master_xlsx
        copy into the "Извештаји" folder on every call -- but this fires
        on every election_changed/generation_log_changed cascade (any
        edit anywhere that touches election/generation-log state, not
        just actual master changes), confirmed costing 230-260ms each
        time against real election data, and connected to BOTH signals
        independently so it ran twice per edit (election_changed's own
        cascade already triggers a nested generation_log_changed emission
        -- see AppState.reload_generation_log). That's the dominant cost
        behind a field report of ~800ms lag on completely unrelated edits
        (e.g. Датум седнице).

        The rebuild was always redundant for its stated purpose: _run()
        (Phase 2 actually completing) already regenerates this exact
        export right after aggregation, which is the only time the
        underlying data can actually change. Keeping only the cheap
        enabled-state check here removes the waste without losing the
        "Извештаји" copy staying fresh -- that's still guaranteed by
        _run().
        """
        persons = read_master(app_paths.master_path())
        self.btn_open_master.setEnabled(bool(persons))

    @log_timing("Phase2Tab._refresh_nacelnik_gate")
    def _refresh_nacelnik_gate(self) -> None:
        """Disable party-file imports once the operator has declared
        submissions closed (Корекције → "Заустави пријем пријава"), OR once
        decisions are submitted to RIK (further changes go through
        Corrections → Amendments, not a fresh import/aggregation)."""
        takeover = self.state.generation_log.workflow("stalni").nacelnik_takeover_started()
        submitted = self.state.generation_log.is_izmena_mode("stalni")
        active = takeover or submitted
        self.btn_import.setEnabled(not active)
        self.btn_import_outlook.setEnabled(not active)
        if submitted:
            self.banner.show_warn(self.tr(
                "Decisions submitted to RIK. This step is no longer needed"
                " for this cycle — further changes go through Corrections"
                " → Amendments."
            ))
        elif takeover:
            self.banner.show_warn(self.tr(
                "The chief has taken over unfilled slots — party"
                " submissions are no longer accepted."
            ))

    @log_timing("Phase2Tab._refresh_cutoff_label")
    def _refresh_cutoff_label(self) -> None:
        cutoff = self.state.election.election.dates.cutoff_stalni
        if cutoff:
            self.lbl_cutoff.setText(
                self.tr(
                    "Submission deadline for regular composition: <b>{date}</b>."
                    " After that date, empty slots are filled by the chief."
                ).format(date=cutoff)
            )
        else:
            self.lbl_cutoff.setText("")

    def _template_path(self):
        from biracki_odbor.core.file_integrity import IntegrityMismatchError
        try:
            self._template_integrity_error = None
            return self.state.template_path()
        except IntegrityMismatchError as e:
            self._template_integrity_error = e
            return None

    def _show_template_tampered(self, error) -> None:
        # Passive only — the interactive restore dialog lives in Election
        # Settings (where template management already lives) so a signal
        # fanning out to Phase1Tab/Phase2Tab/ElectionSettingsTab all at
        # once doesn't stack three modal dialogs on top of each other.
        self.lbl_template.setText(
            self.tr("<b>Template:</b> <span style='color:#9B0000'>changed"
                    " outside the application</span> — resolve in Election"
                    " Settings → Template.")
        )
        self.banner.show_error(
            self.tr(
                "{name} was changed outside the application since it was"
                " last verified ({when}). Resolve in Election Settings →"
                " Template before running."
            ).format(name=error.path.name, when=error.verified_at)
        )
        self.btn_run.setEnabled(False)

    @log_timing("Phase2Tab._refresh_preflight")
    def _refresh_preflight(self) -> None:
        # RIK submission gate: decisions already submitted -- aggregation is
        # no longer needed for this cycle (further changes go through
        # Corrections -> Amendments), same gate Phase 3 already enforces.
        if self.state.generation_log.is_izmena_mode("stalni"):
            self.btn_run.setEnabled(False)
            self.banner.show_warn(self.tr(
                "Decisions submitted to RIK. This step is no longer needed"
                " for this cycle — further changes go through Corrections"
                " → Amendments."
            ))
            return
        tp = self._template_path()
        if tp is None:
            if self._template_integrity_error is not None:
                self._show_template_tampered(self._template_integrity_error)
                return
            self.lbl_template.setText(
                self.tr("<b>Template:</b> <span style='color:#9B0000'>not set</span>"
                        " — open OIK Settings → Working Template.")
            )
            self.banner.show_warn(self.tr("Set up the template in OIK Settings."))
            self.btn_run.setEnabled(False)
            return
        self.lbl_template.setText(self.tr("<b>Template:</b> {path}").format(path=tp))
        report = preflight.preflight_phase2(
            tp, app_paths.popunjeni_dir(), self.state.oik,
        )
        self.errors.set_report(report)
        if report.ok:
            self.banner.show_ok(self.tr("Pre-flight checks passed."))
            self.btn_run.setEnabled(True)
        else:
            n = len(report.errors)
            error_word = declension.count_word(
                n, self.state.app_settings.ui_language,
                "error", "errors", "грешку", "грешке", "грешака",
            )
            self.banner.show_error(
                self.tr("Pre-flight has {n} {error_word}.").format(n=n, error_word=error_word)
            )
            self.btn_run.setEnabled(False)

    def _run(self) -> None:
        tp = self._template_path()
        if tp is None:
            return
        log.info("Phase 2 start: template=%s popunjeni=%s", tp, app_paths.popunjeni_dir())
        self.btn_run.setEnabled(False)
        self.btn_open_master.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self._worker, self._thread = start_worker(
            self, aggregate_party_files,
            app_paths.popunjeni_dir(), tp, app_paths.master_path(),
            self.state.oik,
            election=self.state.election,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

    def _on_progress(self, label: str, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"{label} ({current}/{total})")

    def _on_finished(self, result: Phase2Result) -> None:
        self.last_result = result
        if result.master_path.exists():
            # aggregate_party_files() always rewrites the working master
            # when it gets far enough to write at all — re-fingerprint it
            # now so the next read_master(..., verify=True) trusts this
            # run's output. See core/file_integrity.py.
            from biracki_odbor.core import file_integrity
            file_integrity.record_verified(result.master_path)
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_open_master.setEnabled(True)
        self.errors.set_report(result.report)
        self._errors_by_jmbg = errors_by_jmbg(result.report)
        has_errors = bool(self._errors_by_jmbg)
        self.btn_reply_email.setEnabled(has_errors)
        self.btn_export_errors.setEnabled(has_errors)
        if result.files_processed > 0:
            self.state.generation_log.record_phase("stalni", "phase2")
            self.state.save_generation_log()
        # Stash for Phase 2.5 to consume — row marking + «Само грешке»
        # filter both look this up via AppState.
        self.state.set_phase2_report(result.report)
        n_err = len(result.report.errors)
        n_warn = len(result.report.warnings)
        log.info(
            "Phase 2 finished: files=%d errors=%d warnings=%d",
            result.files_processed, n_err, n_warn,
        )
        if n_err:
            self.banner.show_error(
                self.tr(
                    "Phase 2 complete. {n_files} file(s) loaded."
                    " Errors: {n_err}. Fix via corrections or resend to parties."
                ).format(n_files=result.files_processed, n_err=n_err)
            )
        elif n_warn:
            self.banner.show_warn(
                self.tr(
                    "Phase 2 complete. {n_files} file(s) loaded."
                    " Warnings: {n_warn} (e.g. JMBG conflicts — resolve in Corrections)."
                ).format(n_files=result.files_processed, n_warn=n_warn)
            )
        else:
            self.banner.show_ok(self.tr("Phase 2 completed successfully. Consolidated table saved."))
        if result.persons:
            from biracki_odbor.core.master_io import export_master_xlsx
            export_path = self.state.files_dir("Извештаји") / "zbirana_tabela.xlsx"
            try:
                export_master_xlsx(result.persons, self.state.oik, export_path)
            except OSError:
                pass  # best-effort, matches export_generated's own failure handling
        self.state.master_changed.emit()

    def _on_compose_reply_email(self) -> None:
        """Draft one correction-request email per party with errors in
        the last Phase 2 import — the flagged persons' errors listed in
        the body, that party's originally submitted file attached."""
        if not self._errors_by_jmbg or self.last_result is None:
            return

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

        # Group flagged persons by party.
        by_party: dict[str, list[Person]] = {}
        for p in self.last_result.persons:
            if p.jmbg in self._errors_by_jmbg:
                by_party.setdefault(p.party, []).append(p)

        election = self.state.election
        election_uuid = election.election_uuid.strip()

        from biracki_odbor.integrations.email_client import DraftSpec

        token = election.election.dates.subject_token
        subject = (
            self.tr("Corrections needed — submission for BM")
            + (f" {token}" if token else "")
        )

        drafts: list[DraftSpec] = []
        draft_parties: list[str] = []
        skipped_no_email: list[str] = []
        skipped_no_file: list[str] = []
        for party, persons in sorted(by_party.items()):
            contact = election.party_contact(party)
            if not contact.email:
                skipped_no_email.append(party or self.tr("(unknown)"))
                continue
            attachment = popunjeni_cache.latest_submission_path_for_party(
                election_uuid, party,
            )
            if attachment is None:
                skipped_no_file.append(party or self.tr("(unknown)"))
                continue

            lines = []
            for p in sorted(persons, key=lambda p: (p.bm_number, p.function)):
                for issue in self._errors_by_jmbg.get(p.jmbg, []):
                    name = p.name or self.tr("(no name entered)")
                    lines.append(
                        f"БМ {p.bm_number}, {p.function}, {name}: {issue.message_sr}"
                    )
            body = (
                self.tr("Dear Sir/Madam,\n\n"
                        "The following issues were found in your submitted file:\n\n")
                + "\n".join(lines)
                + self.tr(
                    "\n\nPlease correct the above and resubmit the file.\n\n"
                    "Regards,\nMunicipal Election Commission"
                )
            )
            drafts.append(DraftSpec(
                to=contact.email, subject=subject, body=body, attachment=attachment,
            ))
            draft_parties.append(party)

        if not drafts:
            QMessageBox.warning(
                self, self.tr("No drafts created"),
                self.tr(
                    "No party with errors has both a configured email address"
                    " and a submitted file on record."
                ),
            )
            return

        results = ec.create_drafts(
            drafts,
            preference=self.state.app_settings.email_client,
            display_first=True,
        )

        log_path = app_paths.corrections_log_path()
        ok_count = 0
        for party, result in zip(draft_parties, results):
            if not result.ok:
                continue
            ok_count += 1
            n_errors = sum(
                len(self._errors_by_jmbg.get(p.jmbg, []))
                for p in by_party[party]
            )
            append_reply_email_sent(log_path, party, n_errors)

        failed = [r for r in results if not r.ok]
        msg_parts = [self.tr("Created {n} reply draft(s).").format(n=ok_count)]
        if failed:
            msg_parts.append(self.tr("{n} failed.").format(n=len(failed)))
        if skipped_no_email:
            msg_parts.append(
                self.tr("No email on file for: {parties}.").format(
                    parties=", ".join(skipped_no_email)
                )
            )
        if skipped_no_file:
            msg_parts.append(
                self.tr("No submitted file on record for: {parties}.").format(
                    parties=", ".join(skipped_no_file)
                )
            )
        if failed or skipped_no_email or skipped_no_file:
            self.banner.show_warn(" ".join(msg_parts))
        else:
            self.banner.show_ok(" ".join(msg_parts))

    def _on_export_errors(self) -> None:
        """Export only the currently-flagged (error) rows to a standalone
        .xlsx — same column layout as the master table round-trip."""
        if not self._errors_by_jmbg or self.last_result is None:
            return
        error_persons = [p for p in self.last_result.persons if p.jmbg in self._errors_by_jmbg]
        if not error_persons:
            return

        from datetime import datetime
        from biracki_odbor.core.master_io import export_master_xlsx
        date_part = datetime.now().strftime("%Y-%m-%d")
        default_path = str(
            self.state.files_dir("Извештаји") / f"Грешке_{date_part}.xlsx"
        )
        chosen, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export errors"), default_path,
            self.tr("Excel files (*.xlsx)"),
        )
        if not chosen:
            return
        try:
            export_master_xlsx(error_persons, self.state.oik, chosen)
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Export failed"),
                self.tr("Cannot write file: {error}").format(error=e),
            )
            return
        self.banner.show_ok(
            self.tr("Exported {n} error row(s) to: {path}").format(
                n=len(error_persons), path=chosen,
            )
        )

    def _on_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        log.exception("Phase 2 failed: %s", err)
        # Common Excel-locked-the-file scenario. The raw OSError is
        # cryptic ("[Errno 13] Permission denied: '...zbirana_tabela.xlsx'");
        # rewrite it to a friendly Cyrillic instruction. The user almost
        # always has the master open in Excel from a previous run.
        if "zbirana_tabela.xlsx" in err and (
            "Permission" in err or "Errno 13" in err
        ):
            friendly = self.tr(
                "The consolidated table (zbirana_tabela.xlsx) is currently open"
                " in Excel and the program cannot write the updated content."
                "\n\nClose the file in Excel and re-run Phase 2."
            )
            QMessageBox.warning(self, self.tr("Excel holds the file"), friendly)
            self.banner.show_warn(friendly)
            return
        QMessageBox.critical(self, self.tr("Error"), err)
        self.banner.show_error(self.tr("Unexpected error: {error}").format(error=err))

    def _export_master(self) -> None:
        """Copy the working master to an operator-chosen path.

        Safer than the previous «Отвори збирну табелу…» which opened
        the working file directly in Excel — that path let operators
        edit headers / drop rows / paste formulas that the rest of
        the workflow couldn't track. The exported copy is theirs to
        tinker with; the working master in `master/` stays the single
        source of truth for Phase 3 / audit.

        Default suggested name embeds municipality + election date so
        successive exports across cycles don't overwrite each other on
        the same Desktop.
        """
        from datetime import datetime
        from biracki_odbor.core.master_io import export_master_xlsx
        persons = read_master(app_paths.master_path())
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
            export_master_xlsx(persons, self.state.oik, chosen)
        except OSError as e:
            QMessageBox.critical(
                self, self.tr("Export failed"),
                self.tr("Cannot write export: {error}").format(error=e),
            )
            return
        self.banner.show_ok(self.tr("Consolidated table exported to: {path}").format(path=chosen))

    def _on_import(self) -> None:
        """Multi-select import of party-returned .xlsx files.

        For each picked file: runs safety + identity checks, then copies to
        the canonical path in popunjeni/ (overwriting prior version) and
        updates the persistent cache. Files that fail any check are
        surfaced with their specific reason and do NOT land in popunjeni/.
        """
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select .xlsx files to import"),
            str(self.state.files_dir("Странке")), self.tr("Excel files (*.xlsx)"),
        )
        if not files:
            return
        log.info("Phase 2 import: %d picked", len(files))
        self._import_paths([Path(f) for f in files])

    def _refresh_sample_btn(self) -> None:
        self.btn_sample.setVisible(self.state.license.is_demo)

    def _on_fill_sample(self) -> None:
        """Guided-tour step: fill copies of the Phase 1 party files with
        fictional people and import them (core.sample_fill)."""
        import shutil
        from biracki_odbor.core.sample_fill import fill_party_files
        src = app_paths.stranke_dir()
        files = sorted(src.glob("*.xlsx")) if src.exists() else []
        if not files:
            QMessageBox.information(
                self, self.tr("Sample data"),
                self.tr("Generate the party files first (tab 1)."),
            )
            return
        dest = self.state.files_dir("Пробни подаци")
        copies = []
        for f in files:
            shutil.copy2(f, dest / f.name)
            copies.append(dest / f.name)
        fill_party_files(copies, place=self.state.oik.municipality.name)
        log.info("sample data: filled and importing %d party files from %s", len(copies), dest)
        # The cycle's real deadline has usually passed when a prospect
        # replays it -- don't ask "submitted after deadline?" per file.
        self._import_paths(copies, check_cutoff=False)

    def _import_paths(self, files: list[Path], *, check_cutoff: bool = True) -> None:

        # Load cache scoped to current election; refresh entries as we go.
        election = self.state.election
        election_uuid = election.election_uuid.strip()
        if not election_uuid:
            QMessageBox.warning(
                self, self.tr("Election Configuration"),
                self.tr(
                    "Election configuration has no identifier set."
                    " Save the Election Configuration and try again."
                ),
            )
            return
        cache_data = popunjeni_cache.load(election_uuid=election_uuid)

        # With timestamped filenames each successful import is a NEW
        # entry — no more "replaced" status. The aggregator picks the
        # latest per party on the next Phase 2 run.
        imported = 0
        rejected: list[tuple[str, str]] = []  # (filename, cyrillic_reason)
        new_issues = []

        for src in files:
            outcome = popunjeni_io.import_file(
                src, election, app_paths.popunjeni_dir(),
                phase1_run_ts=self.state.generation_log.stalni.phase1_run_ts,
            )
            if outcome.status == "imported":
                imported += 1
            elif outcome.issue is not None:
                rejected.append((src.name, outcome.issue.message_sr))
                new_issues.append(outcome.issue)
                # Log the specific reason — banner/dialog go away once the
                # user dismisses them, but the log persists for diagnosis.
                log.warning(
                    "Phase 2 import rejected: %s — code=%s — %s",
                    src.name, outcome.issue.code, outcome.issue.message_sr,
                )
            # On success, check cutoff then supersession then populate cache.
            if outcome.ok and outcome.canonical_path is not None:
                # Cutoff warning for file-dialog imports (operator override).
                # Email imports are hard-blocked in _on_inbox_fetch_finished;
                # here the operator explicitly chose the file so we warn and
                # let them decide (they may know the party submitted on time
                # but outside the email channel).
                cutoff_stalni = self.state.election.election.dates.cutoff_stalni
                if cutoff_stalni and check_cutoff:
                    recv_date = (outcome.received_time_iso or "")[:10]
                    if recv_date and recv_date > cutoff_stalni:
                        ans = QMessageBox.question(
                            self,
                            self.tr("Submission after deadline"),
                            self.tr(
                                "File «{name}» has timestamp {recv_date},"
                                " but the submission deadline was {cutoff}.\n\n"
                                "You may continue if you are certain the party"
                                " submitted on time outside the email channel.\n\n"
                                "Do you want to continue with the import?"
                            ).format(
                                name=src.name, recv_date=recv_date, cutoff=cutoff_stalni,
                            ),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if ans != QMessageBox.StandardButton.Yes:
                            odbijeno = app_paths.popunjeni_odbijeno_dir()
                            dest_late = odbijeno / outcome.canonical_path.name
                            outcome.canonical_path.rename(dest_late)
                            append_late_submission_blocked(
                                app_paths.corrections_log_path(),
                                outcome.canonical_path.name,
                                outcome.party,
                                outcome.received_time_iso,
                                cutoff_stalni,
                                source="file_dialog",
                            )
                            reason = self.tr(
                                "Submission after deadline ({recv_date} > {cutoff})."
                                " Rejected at operator request."
                            ).format(recv_date=recv_date, cutoff=cutoff_stalni)
                            rejected.append((src.name, reason))
                            imported -= 1
                            continue

                # Supersession: party already had a prior import in this cycle.
                prior_paths = [
                    p for p, e in cache_data.entries.items()
                    if e.party == outcome.party
                ]
                if prior_paths:
                    log_path = app_paths.corrections_log_path()
                    prior_n = count_party_corrections(log_path, outcome.party)
                    if prior_n > 0:
                        ans = QMessageBox.question(
                            self,
                            self.tr("Resubmission — corrections will be overwritten"),
                            self.tr(
                                "Party «{party}» has previously submitted representatives"
                                " and there are {n} manual corrections for that party.\n\n"
                                "The new submission will overwrite those corrections on the"
                                " next consolidation run.\n\n"
                                "Do you want to continue?"
                            ).format(party=outcome.party, n=prior_n),
                        )
                        if ans != QMessageBox.StandardButton.Yes:
                            imported -= 1
                            continue
                        append_submission_superseded(
                            log_path, outcome.party,
                            outcome.canonical_path.name, prior_n,
                        )

                records, issues = popunjeni_io.parse_for_cache(outcome.canonical_path)
                new_issues.extend(issues)
                cache_data.entries[str(outcome.canonical_path)] = (
                    popunjeni_cache.CacheEntry.from_parsed(
                        outcome.canonical_path, records, issues,
                        received_time_iso=outcome.received_time_iso,
                        import_source=outcome.import_source,
                        party=outcome.party,
                        imported_by=_current_operator(),
                    )
                )

        popunjeni_cache.save(cache_data)
        log.info(
            "Phase 2 import done: %d imported, %d rejected",
            imported, len(rejected),
        )

        # Surface results in the banner + error table.
        if rejected:
            from biracki_odbor.core.models import ValidationReport
            r = ValidationReport()
            for issue in new_issues:
                r.add(issue)
            self.errors.set_report(r)
            self.banner.show_warn(
                self.tr("Imported: {ok}, rejected: {n_rej}. See details in the error table.").format(
                    ok=imported, n_rej=len(rejected),
                )
            )
            details = "\n\n".join(
                f"• {name}\n  {reason}" for name, reason in rejected
            )
            QMessageBox.warning(
                self,
                self.tr("Import — rejected files"),
                self.tr("{n} file(s) were rejected during import:\n\n{details}").format(
                    n=len(rejected), details=details,
                ),
            )
        else:
            self.banner.show_ok(self.tr("Imported: {n} submission(s).").format(n=imported))
        self._refresh_preflight()
        self.imported.emit(imported)

    def _on_import_outlook(self) -> None:
        """Start a background fetch of the inbox, then open the picker dialog.

        MBox parsing across multiple accounts can take several seconds on a
        busy inbox — running it on the GUI thread hangs the application.
        The fetch is offloaded to a worker; the picker dialog opens in
        _on_inbox_fetch_finished once the list is ready.
        """
        from biracki_odbor.integrations import email_client as ec_mod

        election = self.state.election
        election_uuid = election.election_uuid.strip()
        if not election_uuid:
            QMessageBox.warning(
                self, self.tr("Import"),
                self.tr(
                    "Election configuration has no identifier set."
                    " Save the Election Configuration and try again."
                ),
            )
            return

        self.btn_import_outlook.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.banner.show_ok(self.tr("Reading inbox…"))

        import time as _time
        phase1_ts = self.state.generation_log.stalni.phase1_run_ts
        if phase1_ts:
            since_days = max(1, int((_time.time() - phase1_ts) / 86400) + 2)
        else:
            since_days = 14

        self._inbox_worker, self._inbox_thread = start_worker(
            self,
            ec_mod.fetch_inbox_messages,
            preference=self.state.app_settings.email_client,
            since_days=since_days,
            only_xlsx=True,
            subject_contains=election.election.dates.subject_token,
            account_email=self.state.app_settings.oik_email,
        )
        self._inbox_worker.finished.connect(self._on_inbox_fetch_finished)
        self._inbox_worker.failed.connect(self._on_inbox_fetch_failed)

    def _on_inbox_fetch_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_import_outlook.setEnabled(True)
        from biracki_odbor.integrations import email_client as ec_mod
        if "InboxBackendUnavailable" in err:
            QMessageBox.warning(
                self, self.tr("Email client unavailable"),
                self.tr("{error}\n\nUse 'Import files…' to manually select .xlsx files.").format(
                    error=err,
                ),
            )
        else:
            log.exception("Inbox fetch failed: %s", err)
            QMessageBox.critical(
                self, self.tr("Error reading inbox"),
                self.tr("Error reading inbox:\n\n{error}").format(error=err),
            )
        self.banner.show_error(self.tr("Error reading inbox."))

    def _on_inbox_fetch_finished(self, messages: object) -> None:
        self.progress.setVisible(False)
        self.btn_import_outlook.setEnabled(True)
        self.banner.clear()

        from biracki_odbor.gui.dialogs.inbox_picker import InboxPickerDialog
        from biracki_odbor.integrations.thunderbird import find_imap_offline_gaps

        election = self.state.election
        election_uuid = election.election_uuid.strip()

        from biracki_odbor.integrations.email_client import InboxMessage
        from PySide6.QtWidgets import QDialog as _QD
        msgs: list[InboxMessage] = messages  # type: ignore[assignment]
        cutoff = self.state.election.election.dates.cutoff_stalni
        imap_gaps = find_imap_offline_gaps(self.state.app_settings.oik_email) if not msgs else []
        dlg = InboxPickerDialog(msgs, parent=self, cutoff_date=cutoff, imap_gaps=imap_gaps)
        if dlg.exec() != _QD.Accepted:
            return
        picks = dlg.picked()
        if not picks:
            return

        # Stream each attachment to a temp staging path, then run the
        # normal import pipeline against it. Staging avoids touching
        # popunjeni/ until we know the attachment cleared safety +
        # identity checks; rejections leave no residue.
        import tempfile
        cache_data = popunjeni_cache.load(election_uuid=election_uuid)
        imported = 0
        rejected: list[tuple[str, str]] = []
        new_issues = []
        with tempfile.TemporaryDirectory(prefix="outlook_import_") as staging:
            staging_path = Path(staging)
            for pick in picks:
                dest = staging_path / pick.attachment.name
                try:
                    pick.attachment.save_to(dest)
                except Exception as e:  # noqa: BLE001
                    log.warning("Outlook: cannot save %s (%s)", pick.attachment.name, e)
                    rejected.append((pick.attachment.name, f"Outlook: {e}"))
                    continue
                outcome = popunjeni_io.import_file(
                    dest, election, app_paths.popunjeni_dir(),
                    received_at=pick.received_time,
                    source="outlook",
                    phase1_run_ts=self.state.generation_log.stalni.phase1_run_ts,
                )
                if outcome.status == "imported":
                    imported += 1
                elif outcome.issue is not None:
                    rejected.append((pick.attachment.name, outcome.issue.message_sr))
                    new_issues.append(outcome.issue)
                    log.warning(
                        "Outlook import rejected: %s — code=%s — %s",
                        pick.attachment.name, outcome.issue.code,
                        outcome.issue.message_sr,
                    )
                if outcome.ok and outcome.canonical_path is not None:
                    # Hard block: email received after the submission cutoff.
                    # The InboxPickerDialog already marks late messages visually;
                    # this is the enforcement gate that moves and logs the file.
                    if cutoff:
                        recv_date = (outcome.received_time_iso or "")[:10]
                        if recv_date and recv_date > cutoff:
                            odbijeno = app_paths.popunjeni_odbijeno_dir()
                            dest_late = odbijeno / outcome.canonical_path.name
                            outcome.canonical_path.rename(dest_late)
                            append_late_submission_blocked(
                                app_paths.corrections_log_path(),
                                outcome.canonical_path.name,
                                outcome.party,
                                outcome.received_time_iso,
                                cutoff,
                                source="outlook",
                            )
                            reason = self.tr(
                                "Email received {recv_date} — deadline was {cutoff}."
                                " File moved to rejected."
                            ).format(recv_date=recv_date, cutoff=cutoff)
                            rejected.append((pick.attachment.name, reason))
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
                        )
                    )
        popunjeni_cache.save(cache_data)
        log.info(
            "Outlook import done: %d imported, %d rejected",
            imported, len(rejected),
        )

        if rejected:
            from biracki_odbor.core.models import ValidationReport
            r = ValidationReport()
            for issue in new_issues:
                r.add(issue)
            self.errors.set_report(r)
            details = "\n\n".join(
                f"• {name}\n  {reason}" for name, reason in rejected
            )
            QMessageBox.warning(
                self, self.tr("Email import — rejected attachments"),
                self.tr("{n} attachment(s) rejected:\n\n{details}").format(
                    n=len(rejected), details=details,
                ),
            )
            self.banner.show_warn(
                self.tr("From email imported: {ok}, rejected: {n_rej}.").format(
                    ok=imported, n_rej=len(rejected),
                )
            )
        else:
            self.banner.show_ok(
                self.tr("From email imported {n} submission(s).").format(n=imported)
            )
        self._refresh_preflight()
