"""Фаза 1: генерисање фајлова за странке / листе кандидата.

`BasePhase1Tab`      — shared layout + logic (all workflows).
`Phase1Tab`          — стални sastav (template-driven, RIK form).
`ProsireniPhase1Tab` — проширені sastav (candidacies registry, no template).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from biracki_odbor import app_paths
from biracki_odbor.config import declension
from biracki_odbor.core.phase1_generate import Phase1Result, generate_party_files
from biracki_odbor.core.workflow import PROSIRENI_SPEC
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.gui.widgets.banner import StatusBanner
from biracki_odbor.gui.widgets.error_table import ErrorTable
from biracki_odbor.gui.worker import start_worker
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.validation import preflight


log = logging.getLogger(__name__)


class BasePhase1Tab(QWidget):
    """Shared Phase 1 layout and logic for all committee workflows.

    Layout (top → bottom):
      title → hint → [extra header rows] → banner → progress bar →
      error table (stretch) →
      [Поништи | ──stretch── | Отвори | Пошаљи | Покрени]

    Subclasses supply workflow-specific data through properties and hook
    methods; they must implement `_start_generation(run_ts)`.
    """

    # ── Properties subclasses must supply ─────────────────────────────

    @property
    def _title(self) -> str:
        raise NotImplementedError

    @property
    def _hint(self) -> str:
        raise NotImplementedError

    @property
    def _folder_btn_label(self) -> str:
        raise NotImplementedError

    @property
    def _send_btn_label(self) -> str:
        raise NotImplementedError

    @property
    def _send_btn_tooltip(self) -> str:
        raise NotImplementedError

    @property
    def _no_email_warn(self) -> str:
        raise NotImplementedError

    @property
    def _log_slug(self) -> str:
        raise NotImplementedError

    @property
    def _stranke_dir(self) -> Path:
        raise NotImplementedError

    @property
    def _popunjeni_dir(self) -> Path:
        raise NotImplementedError

    @property
    def _export_purpose(self) -> str:
        """`files_dir()` subfolder name generated party files are copied
        into — see `AppState.export_generated`."""
        raise NotImplementedError

    @property
    def _invalidate_body(self) -> str:
        raise NotImplementedError

    def _subject_token(self) -> str:
        raise NotImplementedError

    # ── Optional hook methods ──────────────────────────────────────────

    def _build_header_extras(self, layout: QVBoxLayout) -> None:
        """Add workflow-specific rows between the hint label and the banner."""

    def _connect_extra_signals(self) -> None:
        """Connect additional signals after the standard ones are wired."""

    def _on_post_init(self) -> None:
        """Called at end of __init__ — e.g. to trigger an initial preflight."""

    def _preflight_check(self) -> str | None:
        """Return an error string to abort before generation, or None to proceed."""
        return None

    def _start_generation(self, run_ts: int) -> None:
        raise NotImplementedError

    # ── Construction ──────────────────────────────────────────────────

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._last_files_written: list = []
        # Tracks WorkflowLog.phase1_last so _restore_from_log() only
        # re-exports when THIS tab's own Phase 1 actually changed --
        # generation_log_changed fires for every phase/workflow, not
        # just this one, so without this guard, running Phase 2/3 (or
        # the other workflow's Phase 1) silently re-copied this tab's
        # already-exported files over the operator's export folder
        # every time, even if nothing about them changed.
        self._last_seen_phase1_last: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        lbl = QLabel(self._title)
        lbl.setObjectName("TitleLabel")
        root.addWidget(lbl)

        hint = QLabel(self._hint)
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._build_header_extras(root)

        self.banner = StatusBanner()
        root.addWidget(self.banner)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.errors = ErrorTable()
        self.errors.set_report(_empty_report())
        root.addWidget(self.errors, stretch=1)

        from biracki_odbor.integrations import email_client as _ec_mod

        # Checked once at construction and cached — see the comment on
        # its uses in _restore_from_log()/_on_finished() below for why
        # this must not be re-derived from btn_send.isVisible() later.
        self._send_available = _ec_mod.any_available()

        btns = QHBoxLayout()
        self.btn_invalidate = QPushButton(self.tr("Invalidate and regenerate"))
        self.btn_invalidate.setObjectName("DestructiveButton")
        self.btn_invalidate.setToolTip(
            self.tr(
                "Deletes imported submissions and generates new files with a new"
                " identifier. Parties that already submitted the form must submit a new one."
            )
        )
        self.btn_invalidate.setVisible(False)
        self.btn_invalidate.clicked.connect(self._on_invalidate)
        btns.addWidget(self.btn_invalidate)
        btns.addStretch()
        self.btn_open = QPushButton(self._folder_btn_label)
        self.btn_open.clicked.connect(self._open_folder)
        # Deliberately always enabled. It used to unlock only after a
        # successful Phase 1, which made it permanently dead on
        # проширени: that workflow cannot run without a candidacy
        # registry, so an operator who had not got that far was left
        # with a button that did nothing and no way to tell why.
        # `state.files_dir()` creates the folder on demand, so there is
        # never a run this action depends on — opening an empty export
        # folder is a perfectly good answer.
        btns.addWidget(self.btn_open)
        self.btn_send = QPushButton(self._send_btn_label)
        self.btn_send.setToolTip(self._send_btn_tooltip)
        self.btn_send.setEnabled(False)
        if not self._send_available:  # setVisible(True) here would pop a window
            self.btn_send.hide()
        self.btn_send.clicked.connect(self._on_send)
        btns.addWidget(self.btn_send)
        self.btn_run = QPushButton(self.tr("Run"))
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run)
        btns.addWidget(self.btn_run)
        root.addLayout(btns)

        self.state.generation_log_changed.connect(self._restore_from_log)
        self.state.election_changed.connect(self._restore_from_log)
        self._connect_extra_signals()
        self._on_post_init()
        self._restore_from_log()

    # ── Shared logic ──────────────────────────────────────────────────

    def _log_entry(self):
        return getattr(self.state.generation_log, self._log_slug)

    @log_timing("Phase1Tab._restore_from_log")
    def _restore_from_log(self) -> None:
        phase1_last = self._log_entry().phase1_last
        if not phase1_last:
            if self._send_available:
                self.btn_send.setEnabled(False)
            self._last_files_written = []
            self.btn_run.setText(self.tr("Run"))
            self.btn_invalidate.setVisible(False)
            return
        folder = self._stranke_dir
        files = sorted(folder.glob("*.xlsx")) if folder.exists() else []
        self._last_files_written = files
        # generation_log_changed fires for EVERY workflow/phase, not
        # just this tab's own Phase 1 -- re-export only when this tab's
        # own phase1_last actually moved, so e.g. running Phase 2 (which
        # also calls save_generation_log()) doesn't silently overwrite
        # the operator's export folder with an unrelated re-copy.
        if files and phase1_last != self._last_seen_phase1_last:
            self.state.export_generated(self._export_purpose, files)
        self._last_seen_phase1_last = phase1_last
        self.btn_open.setEnabled(True)
        # Not self.btn_send.isVisible(): this method runs synchronously
        # from __init__, called for every tab before MainWindow ever
        # shows the window (__main__.py builds the whole GUI, then calls
        # showMaximized() — construction happens first). A widget's
        # isVisible() is ancestor-aware and is unconditionally False
        # until the top-level window is shown, no matter what
        # setVisible() was called with — so this check was silently
        # never true on the very first restore of every single launch,
        # and Пошаљи стayed disabled for the rest of the session unless
        # something else (a real re-run, a settings save) happened to
        # re-trigger this method after the window finally appeared.
        # Reported from the field: "the button is grayed out" right
        # after restarting, with a previous session's run already on
        # disk — exactly this path.
        if self._send_available:
            self.btn_send.setEnabled(bool(files))
        self.btn_run.setText(self.tr("Re-run"))
        self.btn_invalidate.setVisible(True)

    def _run(self) -> None:
        import time as _time

        error = self._preflight_check()
        if error:
            self.banner.show_error(error)
            return

        log_entry = self._log_entry()
        if log_entry.phase1_run_ts == 0:
            log_entry.phase1_run_ts = int(_time.time())
            self.state.save_generation_log()
        run_ts = log_entry.phase1_run_ts

        self.banner.hide()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_run.setEnabled(False)
        self.btn_invalidate.setEnabled(False)
        self.errors.clear()
        self._start_generation(run_ts)

    def _on_progress(self, label: str, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"{label} ({current}/{total})")

    def _on_finished(self, result: Phase1Result) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_invalidate.setEnabled(True)
        self.btn_open.setEnabled(True)
        self._last_files_written = list(result.files_written)
        if result.files_written:
            self.state.generation_log.record_phase(self._log_slug, "phase1")
            self.state.save_generation_log()
        if self._send_available:  # not isVisible() — see _restore_from_log
            self.btn_send.setEnabled(bool(result.files_written))
        self.errors.set_report(result.report)
        n = len(result.files_written)
        if result.report.errors:
            n_err = len(result.report.errors)
            error_word = declension.count_word(
                n_err, self.state.app_settings.ui_language,
                "error", "errors", "грешку", "грешке", "грешака",
            )
            self.banner.show_error(
                self.tr("Phase 1 completed with {n_err} {error_word}. Files created: {n}.").format(
                    n_err=n_err, error_word=error_word, n=n,
                )
            )
        elif result.report.warnings:
            self.banner.show_warn(
                self.tr("Phase 1 completed with {n_warn} warning(s). Files created: {n}.").format(
                    n_warn=len(result.report.warnings), n=n,
                )
            )
        else:
            self.banner.show_ok(
                self.tr("Phase 1 completed successfully. {n} file(s) created.").format(n=n)
            )

    def _on_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_invalidate.setEnabled(True)
        log.exception("Phase 1 failed: %s", err)
        QMessageBox.critical(self, self.tr("Error"), err)
        self.banner.show_error(self.tr("Unexpected error: {error}").format(error=err))

    def _on_invalidate(self) -> None:
        import shutil
        import time as _time

        ans = QMessageBox.question(
            self,
            self.tr("Invalidate and regenerate"),
            self._invalidate_body,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        pdir = self._popunjeni_dir
        if pdir.exists():
            shutil.rmtree(pdir)
        log_entry = self._log_entry()
        log_entry.phase1_run_ts = int(_time.time())
        log_entry.phase2_last = ""
        log_entry.phase3_last = ""
        self.state.save_generation_log()
        self._run()

    def _open_folder(self) -> None:
        # Say where, always. A file-manager window can open somewhere the
        # operator cannot see it — behind a maximised app, or on a second
        # display that is switched off — and then a working button is
        # indistinguishable from a dead one. That cost a long debugging
        # session: the folder was opening correctly every time, on a TV
        # that was powered down, with Windows configured to show taskbar
        # buttons only on the display a window lives on.
        path = str(self.state.files_dir(self._export_purpose))
        try:
            subprocess.Popen(["explorer", path])
        except OSError:
            QMessageBox.information(self, self.tr("Folder"), path)
            return
        self.banner.show_info(self.tr("Opened folder: {path}").format(path=path))

    def _send_recipients(self) -> tuple[dict[str, str], dict[str, str]]:
        """(full_names, emails) address book for the Send dialog, both
        keyed by the same identifier Phase 1 used for that file's own
        filename stem (`send_to_parties_dialog._match_party` matches by
        `_safe_filename(key) == file.stem`).

        Default: стални's RIK-party contacts (`ElectionConfig.
        party_contacts`, keyed by party abbreviation). Deliberately a
        separate address book from прошиени's entity contacts — see
        `ProsireniPhase1Tab`'s override and `Entity.email`'s docstring —
        so a party's saved email can never be reused to contact a
        прошиени list, or vice versa, just because one class happened
        not to override this method.
        """
        ec = self.state.election
        emails = {
            abbrev: contact.email
            for abbrev, contact in ec.party_contacts.items()
            if contact.email
        }
        return dict(ec.party_full_names), emails

    def _on_send(self) -> None:
        if not self._last_files_written:
            return
        from biracki_odbor.gui.dialogs.send_to_parties_dialog import SendToPartiesDialog
        from biracki_odbor.integrations import email_client as ec_mod
        from PySide6.QtWidgets import QDialog as _QD

        full_names, emails = self._send_recipients()
        dlg = SendToPartiesDialog(
            files=self._last_files_written,
            party_full_names=full_names,
            party_emails=emails,
            parent=self,
            subject_token=self._subject_token(),
            workflow_slug=self._log_slug,
        )
        if dlg.exec() != _QD.Accepted:
            return
        drafts = dlg.prepared_drafts()
        if not drafts:
            self.banner.show_warn(self._no_email_warn)
            return
        try:
            results = ec_mod.create_drafts(
                drafts,
                preference=self.state.app_settings.email_client,
                display_first=True,
            )
        except ec_mod.EmailClientUnavailable as e:
            QMessageBox.warning(self, self.tr("Email client unavailable"), str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("Email-client drafts failed")
            QMessageBox.critical(
                self, self.tr("Error creating drafts"),
                self.tr("Error creating drafts:\n\n{error}").format(error=e),
            )
            return
        ok = sum(1 for r in results if r.ok)
        failed = [r for r in results if not r.ok]
        if failed:
            details = "\n\n".join(f"• {r.spec.to}\n  {r.error}" for r in failed)
            QMessageBox.warning(
                self, self.tr("Drafts — partial"),
                self.tr("Created {ok} draft(s), {n_failed} failed:\n\n{details}").format(
                    ok=ok, n_failed=len(failed), details=details,
                ),
            )
            self.banner.show_warn(
                self.tr("Created {ok} draft(s); {n_failed} failed.").format(
                    ok=ok, n_failed=len(failed),
                )
            )
        else:
            self.banner.show_ok(
                self.tr("Created {ok} draft(s) in Outlook → Drafts. First opened for review.").format(ok=ok)
            )


# ── Стални састав ─────────────────────────────────────────────────────


class Phase1Tab(BasePhase1Tab):
    """Phase 1 for the стални workflow — generates party files from a RIK template."""

    _template_integrity_error = None  # set by _template_path(), read by _refresh_preflight

    @property
    def _title(self) -> str:
        return self.tr("Party File Generation")

    @property
    def _hint(self) -> str:
        return self.tr(
            "1. Select the RIK template in OIK Settings (Working Template).  "
            "2. Click 'Run'.  "
            "3. Send each generated .xlsx to the corresponding party."
        )

    @property
    def _folder_btn_label(self) -> str:
        return self.tr("Open export folder…")

    @property
    def _export_purpose(self) -> str:
        # Folder-name constant, not translatable UI text — same
        # convention as the existing files_dir() purpose labels
        # ("Групе", "Извештаји", ...) used elsewhere in the app.
        return "Странке"

    @property
    def _send_btn_label(self) -> str:
        return self.tr("Send")

    @property
    def _send_btn_tooltip(self) -> str:
        return self.tr(
            "Send to parties. Creates email drafts per party with the"
            " corresponding .xlsx as attachment."
            " Uses the email client selected in OIK Settings → System."
        )

    @property
    def _no_email_warn(self) -> str:
        return self.tr("No party has a valid email address — no drafts created.")

    @property
    def _log_slug(self) -> str:
        return "stalni"

    @property
    def _stranke_dir(self) -> Path:
        return app_paths.stranke_dir()

    @property
    def _popunjeni_dir(self) -> Path:
        return app_paths.popunjeni_dir()

    @property
    def _invalidate_body(self) -> str:
        return self.tr(
            "This will:\n"
            "  1. Delete all imported submissions for regular composition\n"
            "  2. Generate new party files with a new identifier\n\n"
            "Parties that have already submitted the form must submit a new one.\n\n"
            "Do you want to continue?"
        )

    def _subject_token(self) -> str:
        return self.state.election.election.dates.subject_token

    # ── Стані-specific: template row + live preflight ─────────────────

    def _build_header_extras(self, layout: QVBoxLayout) -> None:
        tpl_row = QHBoxLayout()
        self.lbl_template = QLabel()
        self.lbl_template.setWordWrap(True)
        tpl_row.addWidget(self.lbl_template, stretch=1)
        layout.addLayout(tpl_row)

    def _connect_extra_signals(self) -> None:
        self.state.oik_changed.connect(self._refresh_preflight)
        self.state.template_changed.connect(self._refresh_preflight)

    def _on_post_init(self) -> None:
        self._refresh_preflight()

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
        self.errors.set_report(_empty_report())

    @log_timing("Phase1Tab._refresh_preflight")
    def _refresh_preflight(self) -> None:
        # RIK submission gate: decisions already submitted -- Phase 1/2 are
        # no longer needed for this cycle (further changes go through
        # Corrections -> Amendments), same gate Phase 3 already enforces.
        # btn_run/btn_invalidate are paired everywhere else in this file
        # (see _start_generation/_on_finished/_on_failed) -- keep that
        # pairing here too, since "Invalidate and regenerate" is just as
        # much a re-run action as "Run" itself.
        if self.state.generation_log.is_izmena_mode(self._log_slug):
            self.btn_run.setEnabled(False)
            self.btn_invalidate.setEnabled(False)
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
            self.errors.set_report(_empty_report())
            return
        self.lbl_template.setText(self.tr("<b>Template:</b> {path}").format(path=tp))
        report = preflight.preflight_phase1(tp, self.state.oik)
        self.errors.set_report(report)
        if report.ok:
            self.banner.show_ok(
                self.tr("Pre-flight checks passed — you can run Phase 1.")
            )
            self.btn_run.setEnabled(True)
        else:
            n = len(report.errors)
            error_word = declension.count_word(
                n, self.state.app_settings.ui_language,
                "error", "errors", "грешку", "грешке", "грешака",
            )
            self.banner.show_error(
                self.tr("Pre-flight has {n} {error_word}. Fix them and try again.").format(
                    n=n, error_word=error_word,
                )
            )
            self.btn_run.setEnabled(False)

    def _start_generation(self, run_ts: int) -> None:
        tp = self._template_path()
        if tp is None:
            return
        log.info("Phase 1 start: template=%s run_ts=%d", tp, run_ts)
        self._worker, self._thread = start_worker(
            self, generate_party_files,
            tp, app_paths.stranke_dir(), self.state.oik,
            election=self.state.election,
            demo_mode=self.state.license.is_demo,
            run_ts=run_ts,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)


# ── Проширені sastav ──────────────────────────────────────────────────


class ProsireniPhase1Tab(BasePhase1Tab):
    """Phase 1 for the проширені workflow — generates from the candidacies registry."""

    @property
    def _title(self) -> str:
        return self.tr("Candidate List Generation")

    @property
    def _hint(self) -> str:
        return self.tr(
            "Generates one .xlsx file per list from the candidacies registry\n"
            "(Elections → Candidates). Each list file contains rows for\n"
            "Member + Deputy member for each polling station."
        )

    @property
    def _folder_btn_label(self) -> str:
        return self.tr("Open folder…")

    @property
    def _export_purpose(self) -> str:
        return "Странке (проширени)"

    @property
    def _send_btn_label(self) -> str:
        return self.tr("Send")

    @property
    def _send_btn_tooltip(self) -> str:
        return self.tr(
            "Send to lists. Creates email drafts per list with the"
            " corresponding .xlsx as attachment."
            " Uses the email client selected in OIK Settings → System."
        )

    @property
    def _no_email_warn(self) -> str:
        return self.tr("No list has a valid email address — no drafts created.")

    @property
    def _log_slug(self) -> str:
        return "prosireni"

    @property
    def _stranke_dir(self) -> Path:
        return app_paths.stranke_dir_for(PROSIRENI_SPEC)

    @property
    def _popunjeni_dir(self) -> Path:
        return app_paths.popunjeni_dir_for(PROSIRENI_SPEC)

    @property
    def _invalidate_body(self) -> str:
        return self.tr(
            "This will:\n"
            "  1. Delete all imported submissions for extended composition\n"
            "  2. Generate new list files with a new identifier\n\n"
            "Lists that have already submitted the form must submit a new one.\n\n"
            "Do you want to continue?"
        )

    def _subject_token(self) -> str:
        return self.state.election.election.dates.subject_token_for("prosireni")

    def _send_recipients(self) -> tuple[dict[str, str], dict[str, str]]:
        """Прошиени's own address book — candidacies.entities, keyed by
        entity_id (matches `generate_entity_files`' own filename stems,
        `f"{_safe_filename(entity_id)}.xlsx"`, so the Send dialog's
        file↔recipient matching actually finds a row instead of falling
        back to an unmatched/blank one for every list).

        Kept separate from the inherited стални default on purpose — a
        list's entity_id and a RIK party abbreviation are different
        identity systems that must never be cross-matched, so a list is
        never accidentally emailed using a party's saved address."""
        registry = getattr(self.state.election, "candidacies", None)
        entities = registry.entities if registry else []
        full_names = {e.entity_id: e.name for e in entities}
        emails = {e.entity_id: e.email for e in entities if e.email}
        return full_names, emails

    def _preflight_check(self) -> str | None:
        issues = preflight.check_oik(self.state.oik)
        if issues:
            return "; ".join(i.message_sr for i in issues)
        registry = getattr(self.state.election, "candidacies", None)
        if registry is None or not registry.entities:
            return self.tr(
                "Candidacy registry is empty. "
                "Add lists in Elections → Candidates before running Phase 1."
            )
        if not self.state.oik.polling_stations:
            return self.tr("No polling stations configured in OIK Settings.")
        return None

    def _start_generation(self, run_ts: int) -> None:
        from biracki_odbor.core.phase1_generate import generate_entity_files

        election = self.state.election
        oik = self.state.oik
        registry = getattr(election, "candidacies", None)
        bm_numbers = [ps.bm_number for ps in oik.polling_stations]
        out_dir = self._stranke_dir

        def _work() -> object:
            return generate_entity_files(
                registry=registry,
                bm_numbers=bm_numbers,
                output_dir=out_dir,
                oik=oik,
                progress=lambda name, i, n: None,
                election=election,
                run_ts=run_ts,
                demo_mode=self.state.license.is_demo,
            )

        self._worker, self._thread = start_worker(self, _work)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

    def _on_finished(self, result: Phase1Result) -> None:
        # generate_entity_files() -> build_prosireni_allocation() ->
        # canonical_slots() may have just assigned slot_index to any
        # newly-registered entities (mutated in place on the same
        # Entity objects held by self.state.election.candidacies).
        # Persist immediately -- once a slot number gets baked into a
        # generated file's locked Функција column, it must never
        # change again, so the assignment can't stay in-memory-only.
        super()._on_finished(result)
        self.state.save_election()


def _empty_report():
    from biracki_odbor.core.models import ValidationReport
    return ValidationReport()
