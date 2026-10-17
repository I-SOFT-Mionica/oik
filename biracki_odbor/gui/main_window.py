"""Main application window — sidebar + stacked workspace.

Six top-level sections per the V1 sidebar layout (see sidebar.py):
Изборна конфигурација, Стални састав, Проширени састав (V2),
Посматрачи (V2), Поставке ОИК, О апликацији. The right pane is a
QStackedWidget — one widget per section, stack indices match the
SECTION_* constants exactly so navigation is just
`stack.setCurrentIndex(section)`.

Изборна конфигурација and Поставке ОИК are now SEPARATE stack items
(promoted from inner-tabs-of-Поставке in v0.5.1) so each gets its own
sidebar entry per the V1 design. Dirty-flag plumbing follows them:
leaving either page with unsaved edits prompts Save / Discard / Cancel.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QStatusBar, QTabWidget, QWidget,
)

from biracki_odbor import __version__, app_paths
from biracki_odbor.gui.about_page import AboutPage
from biracki_odbor.gui.app_state import AppState
from biracki_odbor.logging_setup import log_timing
from biracki_odbor.gui.sidebar import (
    SECTION_ABOUT, SECTION_ALATI, SECTION_IZBORNA, SECTION_OIK,
    SECTION_POSMATRACI, SECTION_PROSIRENI, SECTION_STALNI, SECTION_ZAKONI,
    Sidebar,
)
from biracki_odbor.updates import (
    LicensedUpdateChecker, UpdateChecker, UpdateInfo,
)


# Sections whose pages might have unsaved edits. Used by the dirty-leave
# interception to know which sections need a prompt.
_DIRTY_AWARE_SECTIONS = (SECTION_IZBORNA, SECTION_OIK)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            self.tr("Polling Board — Permanent Composition Management") + f"  ({__version__})"
        )
        # Some platform-plugin / DPI-scaling combinations drop min/max in the
        # bundled .exe. Request the full Windows chrome explicitly.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(1280, 800)
        # 1024×600 is the V1 baseline target (21" 720p with room for the
        # title + status bars). § 3.1 of the theming guide.
        self.setMinimumSize(1024, 600)

        self.state = AppState()

        self.sidebar = Sidebar()
        self.sidebar.section_changed.connect(self._on_section_changed)
        self.state.oik_changed.connect(self._refresh_onboarding_state)
        self.state.election_changed.connect(self._refresh_onboarding_state)
        self.state.master_changed.connect(self._refresh_onboarding_state)

        from biracki_odbor.gui.tabs.settings_oik import OikSettingsTab
        from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

        # Two separate top-level settings pages (no inner tab strip).
        self.izborna_page = ElectionSettingsTab(self.state)
        self.oik_page = OikSettingsTab(self.state)

        from biracki_odbor.gui.tabs.phase1 import Phase1Tab
        from biracki_odbor.gui.tabs.phase2 import Phase2Tab
        from biracki_odbor.gui.tabs.corrections import CorrectionsTab
        from biracki_odbor.gui.tabs.phase3 import Phase3Tab
        from biracki_odbor.gui.tabs.izmene import IzmeneTab

        # Стални workflow tabs — template upload moved to Избори → tab 3.
        # Sequential gating: each tab unlocks once the previous phase completes.
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.addTab(Phase1Tab(self.state), self.tr("1. Parties"))
        self.tabs.addTab(Phase2Tab(self.state), self.tr("2. Consolidation"))
        self.corrections_tab = CorrectionsTab(self.state)
        self.tabs.addTab(self.corrections_tab, self.tr("3. Corrections"))
        self.tabs.addTab(Phase3Tab(self.state), self.tr("4. Decisions"))
        self.izmene_tab = IzmeneTab(self.state)
        self.tabs.addTab(self.izmene_tab, self.tr("5. Amendments"))
        self.izmene_tab.navigate_to_corrections.connect(self._go_to_corrections)

        from biracki_odbor.gui.tabs.prosireni_workspace import ProsireniWorkspace
        from biracki_odbor.gui.tabs.posmatraci_workspace import PosmatraciWorkspace
        from biracki_odbor.gui.tabs.zakoni_page import ZakoniPage
        from biracki_odbor.gui.tabs.alati_page import AlatiPage

        self.about_page = AboutPage(state=self.state)
        self.about_page.tour_requested.connect(self.start_tour)
        self.prosireni_page = ProsireniWorkspace(self.state)
        self.posmatraci_page = PosmatraciWorkspace(self.state)
        self.zakoni_page = ZakoniPage()
        self.alati_page = AlatiPage(self.state)

        # Stack indices match the SECTION_* constants in sidebar.py:
        #   0 — Изборна конфигурација
        #   1 — Стални састав (workflow phase tabs)
        #   2 — Проширени састав (live Phase E workspace)
        #   3 — Посматрачи (placeholder, disabled in sidebar)
        #   4 — Поставке ОИК
        #   5 — О апликацији
        #   6 — Закони (read-only law viewer)
        #   7 — Алати (PDF converter + backup/restore)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.izborna_page)      # SECTION_IZBORNA
        self.stack.addWidget(self.tabs)              # SECTION_STALNI
        self.stack.addWidget(self.prosireni_page)    # SECTION_PROSIRENI
        self.stack.addWidget(self.posmatraci_page)   # SECTION_POSMATRACI
        self.stack.addWidget(self.oik_page)          # SECTION_OIK
        self.stack.addWidget(self.about_page)        # SECTION_ABOUT
        self.stack.addWidget(self.zakoni_page)       # SECTION_ZAKONI
        self.stack.addWidget(self.alati_page)        # SECTION_ALATI
        # Default to Стални састав for an operator who has already done
        # setup. If onboarding is not complete (first run or missing
        # config), _refresh_onboarding_state (called at the end of
        # __init__) will redirect to the Избори settings page.
        self.stack.setCurrentIndex(SECTION_STALNI)

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.sidebar)
        outer.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

        status = QStatusBar()
        status.showMessage(self.tr("Working directory: {path}").format(path=app_paths.home()))
        self.setStatusBar(status)

        # "Аутосачувано" indicator — permanent widget, right side of
        # the status bar. AppState emits `saved` after every successful
        # config write; a 30 s tick refreshes the relative-time label
        # so it stays accurate even when no new save has happened.
        # Stays empty until the first save of the session so a fresh
        # launch doesn't claim "Аутосачувано пре 0 мин" when nothing
        # has been saved yet.
        self._save_label = QLabel("")
        self._save_label.setObjectName("MutedLabel")
        status.addPermanentWidget(self._save_label)
        self.state.saved.connect(self._refresh_save_label)
        self._save_tick = QTimer(self)
        self._save_tick.setInterval(30_000)  # 30 s
        self._save_tick.timeout.connect(self._refresh_save_label)
        self._save_tick.start()
        # Initial paint (may be empty if nothing saved yet).
        self._refresh_save_label()

        self._update_btn = QPushButton("")
        self._update_btn.setObjectName("PrimaryButton")
        self._update_btn.setVisible(False)
        self._update_btn.clicked.connect(self._open_update_url)
        status.addPermanentWidget(self._update_btn)
        self._update_url = ""

        # Update-checker selection follows the license mode:
        #   DISABLED → GitHub Releases poll (legacy / dev / OSS path)
        #   LICENSED → server-gated check; server consults
        #              updates_until before offering anything
        #   DEMO     → no update checker at all; operator activates
        #              first, then a restart re-evaluates this branch
        lic = self.state.license
        if lic.mode.name == "LICENSED":
            from biracki_odbor import app_paths as _ap
            try:
                token = _ap.license_dat_path().read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
            self._update_checker = LicensedUpdateChecker(
                self.state.app_settings.licensing_server_url, token, self,
            )
            self._update_checker.update_available.connect(self._on_update_available)
            self._update_checker.updates_expired.connect(self._on_updates_expired)
            self._update_checker.token_refreshed.connect(self.state.reload_license)
            self._update_checker.start()
        elif lic.mode.name == "DISABLED":
            self._update_checker = UpdateChecker(self)
            self._update_checker.update_available.connect(self._on_update_available)
            self._update_checker.start()
        else:
            # DEMO — no update checker, activation comes first.
            self._update_checker = None

        # License banner in the status bar — only visible when the
        # local license is in DEMO mode. DISABLED (licensing feature
        # off) and LICENSED (everything OK) both hide the banner.
        self._license_label = QLabel("")
        self._license_label.setObjectName("WarnLabel")
        self._license_label.setVisible(False)
        status.addPermanentWidget(self._license_label)
        self.state.license_changed.connect(self._refresh_license_banner)
        self.state.license_changed.connect(self._refresh_onboarding_state)
        self._refresh_license_banner()

        # On first launch with licensing configured but no license
        # file present, pop the activation dialog immediately. The
        # technician sees it before they get to the workflow tabs.
        # Use a queued single-shot so the main loop is running by the
        # time the dialog opens.
        if (
            self.state.license.mode.name == "DEMO"
            and self.state.license.reason == "no_license_file"
        ):
            QTimer.singleShot(0, self._open_activation_dialog)

        if not self.state.onboarding_complete:
            QTimer.singleShot(200, self._open_setup_wizard)

        self.state.template_changed.connect(self._refresh_tab_states)
        self.state.generation_log_changed.connect(self._refresh_tab_states)
        self.state.app_settings_changed.connect(self._refresh_tab_states)
        self._refresh_tab_states()

        # Onboarding gate — must be last so the sidebar + stack are
        # fully wired before we potentially redirect to SECTION_IZBORNA.
        self._refresh_onboarding_state()

        # Daily auto-backup: fires once immediately at startup (via
        # singleShot so the main loop is running), then every hour.
        # Silent — no banner or dialog; the operator sees the file in
        # HOME/backups/ if they ever need it.
        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.setInterval(60 * 60 * 1_000)  # 1 h
        self._auto_backup_timer.timeout.connect(self._run_auto_backup)
        self._auto_backup_timer.start()
        QTimer.singleShot(0, self._run_auto_backup)

    def _go_to_corrections(self, jmbg: str) -> None:
        """Navigate to Corrections tab and prefill JMBG search."""
        self.stack.setCurrentIndex(SECTION_STALNI)
        self.tabs.setCurrentIndex(2)  # CorrectionsTab is at index 2
        self.corrections_tab.set_search(jmbg)

    @log_timing("MainWindow._refresh_tab_states")
    def _refresh_tab_states(self) -> None:
        """Sequential tab gating for the Стални workflow.

        Tab 0 (Странке)      — unlocks once the template is uploaded.
        Tab 1 (Обједињавање) — unlocks after Phase 1 has run at least once.
        Tab 2 (Корекције)    — unlocks after Phase 2 has run at least once.
        Tab 3 (Решења)       — available until RIK submission confirmed.
        Tab 4 (Измене)       — available only in izmena_mode (post-submission).
        """
        def _set(idx: int, enabled: bool, tip: str = "") -> None:
            self.tabs.setTabEnabled(idx, enabled)
            self.tabs.setTabToolTip(idx, tip if not enabled else "")

        if self.state.app_settings.disable_tab_gating:
            for i in range(self.tabs.count()):
                _set(i, True)
            return

        gl = self.state.generation_log
        wl = gl.stalni
        izmena_mode = gl.is_izmena_mode("stalni")
        try:
            has_template = self.state.template_path() is not None
        except Exception:  # noqa: BLE001 — file_integrity.IntegrityMismatchError
            # Tab gating just needs a yes/no here; Phase1Tab/Phase2Tab's own
            # preflight is where the actual tampered-file dialog + restore
            # flow lives (see gui/dialogs/integrity_dialog.py). A tampered
            # template must not unlock tabs that depend on it.
            has_template = False
        has_phase1 = bool(wl.phase1_last)
        has_phase2 = bool(wl.phase2_last)

        _set(0, has_template and not izmena_mode,
             self.tr("Decisions submitted to RIK — no longer needed this cycle.")
             if izmena_mode else
             self.tr("Upload the allocation template in Избори → Template first."))
        _set(1, has_template and has_phase1 and not izmena_mode,
             self.tr("Decisions submitted to RIK — no longer needed this cycle.")
             if izmena_mode else
             self.tr("Run Phase 0 (Parties) at least once to unlock."))
        _set(2, has_template and has_phase1 and has_phase2,
             self.tr("Run Phase 1 (Consolidation) at least once to unlock."))
        _set(3, has_phase2 and not izmena_mode,
             self.tr("Decisions submitted to RIK. Use the Amendments tab for further corrections.")
             if izmena_mode else
             self.tr("Run Phase 1 (Consolidation) at least once to unlock."))
        _set(4, izmena_mode,
             self.tr("Amendments become available after confirming 'Submitted to RIK' on the Decisions tab."))

        # If the currently selected tab just became disabled, move to the
        # highest-numbered enabled tab at or below it -- or, if none (e.g.
        # sitting on tab 0/1 when RIK submission disables them), the
        # lowest-numbered enabled tab above it (Корекције is always
        # enabled whenever izmena_mode disables 0/1, so this always finds
        # a home rather than leaving a disabled tab selected).
        cur = self.tabs.currentIndex()
        if not self.tabs.isTabEnabled(cur):
            for i in range(cur - 1, -1, -1):
                if self.tabs.isTabEnabled(i):
                    self.tabs.setCurrentIndex(i)
                    break
            else:
                for i in range(cur + 1, self.tabs.count()):
                    if self.tabs.isTabEnabled(i):
                        self.tabs.setCurrentIndex(i)
                        break

    @log_timing("MainWindow._refresh_onboarding_state")
    def _refresh_onboarding_state(self) -> None:
        """Enable/disable workflow sidebar sections based on config completeness.

        Called once at startup and then on every oik_changed / election_changed
        signal. Redirects to the election settings page when the minimum
        configuration needed to run Phase 1 is not yet in place.
        """
        complete = self.state.onboarding_complete
        local_elections = "local" in (self.state.election.election.types or [])
        self.sidebar.set_workflow_enabled(complete, local_elections=local_elections)
        if not complete:
            cur = self.stack.currentIndex()
            if cur in (SECTION_STALNI, SECTION_PROSIRENI, SECTION_POSMATRACI):
                self.sidebar.set_section(SECTION_IZBORNA)

    def _run_auto_backup(self) -> None:
        """Hourly / startup auto-backup check. Silent — no UI interaction."""
        from biracki_odbor.core.backup import run_daily_backup_if_due
        import logging as _log
        try:
            run_daily_backup_if_due(app_paths.home())
        except Exception as e:  # noqa: BLE001
            _log.getLogger(__name__).warning("auto-backup check failed: %s", e)

    def _on_section_changed(self, index: int) -> None:
        # Leaving a settings page with unsaved edits → prompt
        # Save / Discard / Cancel. Settings pages are top-level sections
        # in V1 (Изборна конфигурација at SECTION_IZBORNA, Поставке ОИК
        # at SECTION_OIK) — formerly inner tabs of a single Поставке
        # section in v0.5.1.
        prev = self.stack.currentIndex()
        if prev in _DIRTY_AWARE_SECTIONS and index != prev:
            leaving = self.stack.widget(prev)
            if not self._handle_dirty_leave(leaving):
                # User cancelled — restore the previous selection in the
                # sidebar so it stays in sync with the stack.
                self.sidebar.set_section(prev)
                return
        self.stack.setCurrentIndex(index)

    # ── Unsaved-changes interception ───────────────────────────────

    def _handle_dirty_leave(self, leaving_tab) -> bool:
        """If `leaving_tab` has dirty=True, prompt the user.

        Returns True iff the leave is allowed (Save or Discard chosen, or
        nothing dirty). False means the caller must revert whatever
        navigation action it was about to perform.
        """
        if leaving_tab is None or not getattr(leaving_tab, "dirty", False):
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle(self.tr("Unsaved Changes"))
        msg.setText(
            self.tr("You have unsaved changes in these settings.\n\nSave changes before leaving?")
        )
        msg.setIcon(QMessageBox.Question)
        btn_save    = msg.addButton(self.tr("Save"),    QMessageBox.AcceptRole)
        btn_discard = msg.addButton(self.tr("Discard"), QMessageBox.DestructiveRole)
        btn_cancel  = msg.addButton(self.tr("Cancel"),  QMessageBox.RejectRole)
        msg.setDefaultButton(btn_save)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_save:
            ok = leaving_tab.save()
            if not ok:
                # Save failed — keep user on the tab to fix the issue.
                return False
            return True
        if clicked is btn_discard:
            leaving_tab.revert()
            return True
        # Cancel (btn_cancel or dialog closed).
        return False

    def closeEvent(self, event) -> None:  # noqa: N802
        """On window close, check both settings pages for unsaved edits."""
        for section in _DIRTY_AWARE_SECTIONS:
            page = self.stack.widget(section)
            if not self._handle_dirty_leave(page):
                event.ignore()
                return
        super().closeEvent(event)

    def _on_update_available(self, info: UpdateInfo) -> None:
        self._update_url = info.url
        self._update_btn.setText(
            self.tr("Update available: {latest} — О апликацији").format(
                latest=info.latest,
            )
        )
        self._update_btn.setVisible(True)
        self.about_page.notify_update_available(info)

    def _open_update_url(self) -> None:
        self.sidebar.section_changed.emit(SECTION_ABOUT)
        self.stack.setCurrentIndex(SECTION_ABOUT)

    def _on_updates_expired(self, expired_on: str) -> None:
        """Server told us the updates subscription is past expiry.

        Show a renewal prompt in the status bar (instead of the usual
        "update available" button). The app still runs — the customer
        paid for the version they're on perpetually; renewal only
        unlocks newer versions.
        """
        self._update_btn.setText(
            self.tr("Updates subscription expired ({date}) — renew through I-SOFT").format(
                date=expired_on,
            )
        )
        self._update_btn.setVisible(True)
        # Stash a marker so _open_update_url doesn't try to navigate
        # somewhere when there's no URL.
        self._update_url = ""

    def _refresh_license_banner(self) -> None:
        """Show/hide the demo-mode status-bar banner."""
        lic = self.state.license
        if lic.mode.name == "DEMO":
            reason_map = {
                "no_license_file": self.tr("Demo mode — license not activated."),
                "license_malformed": self.tr("Demo mode — license is corrupted."),
                "license_invalid_signature": self.tr("Demo mode — license signature is not valid."),
                "license_unreadable": self.tr("Demo mode — license is unreadable."),
                "machine_mismatch": self.tr("Demo mode — license was issued for a different machine."),
            }
            self._license_label.setText(
                reason_map.get(lic.reason, self.tr("Demo mode."))
            )
            self._license_label.setVisible(True)
        else:
            self._license_label.setVisible(False)

    def _open_setup_wizard(self) -> None:
        if self.state.onboarding_complete:
            return
        from biracki_odbor.gui.dialogs.setup_wizard import SetupWizard
        wiz = SetupWizard(self.state, self)
        accepted = wiz.exec()
        if wiz.requested_section is not None:
            self.sidebar.set_section(wiz.requested_section)
        # A prospect trying the demo gets walked through one full cycle.
        if accepted and self.state.license.is_demo and self.state.onboarding_complete:
            QTimer.singleShot(400, self.start_tour)

    def start_tour(self) -> None:
        from biracki_odbor.gui.tour import GuidedTour
        if getattr(self, "_tour", None) is not None:
            return
        self._tour = GuidedTour(self)
        self._tour.finished.connect(self._on_tour_finished)
        self._tour.start()

    def _on_tour_finished(self, _completed: bool) -> None:
        self._tour.deleteLater()
        self._tour = None

    def _open_activation_dialog(self) -> None:
        """Open the activation dialog and reload the license on accept."""
        from biracki_odbor.gui.dialogs.activation_dialog import ActivationDialog
        from biracki_odbor.config import settings as settings_mod
        from PySide6.QtWidgets import QDialog as _QD

        dlg = ActivationDialog(
            server_url=self.state.app_settings.licensing_server_url,
            license_dat_path=app_paths.license_dat_path(),
            machine_hid=self.state.license.machine_hid,
            parent=self,
        )
        if dlg.exec() == _QD.Accepted:
            self.state.reload_license()

    def _refresh_save_label(self) -> None:
        """Update the status-bar autosave indicator with a fresh
        relative-time string.

        Fires on every `AppState.saved` emit AND on a 30 s tick so
        the "5 min ago" stays accurate even when nothing new has
        been saved. Empty when nothing has been saved yet in this
        session — a fresh first-launch app shouldn't claim a save.
        """
        from datetime import datetime
        last = self.state.last_save_at
        if last is None:
            self._save_label.setText("")
            return
        delta = datetime.now() - last
        secs = int(delta.total_seconds())
        if secs < 60:
            text = self.tr("Autosaved just now")
        elif secs < 60 * 60:
            mins = secs // 60
            text = self.tr("Autosaved {n} min ago").format(n=mins)
        elif secs < 24 * 60 * 60:
            hours = secs // 3600
            text = self.tr("Autosaved {n} h ago").format(n=hours)
        else:
            # > 24 h shouldn't happen in normal use (the app gets
            # restarted, last_save_at resets to None). Belt-and-
            # suspenders: show the absolute time instead of a huge
            # "+2 days" relative.
            text = self.tr("Autosaved {dt}").format(dt=last.strftime('%Y-%m-%d %H:%M'))
        self._save_label.setText(text)
