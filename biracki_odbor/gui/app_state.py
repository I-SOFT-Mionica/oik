"""Shared application state across tabs.

A single instance is created by MainWindow and passed to each tab. Tabs
read configs through it (so a change saved in one tab is visible in
another immediately) and subscribe to changes via Qt signals.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, Signal

from biracki_odbor import app_paths
from biracki_odbor.config import election as election_mod
from biracki_odbor.config import oik as oik_mod
from biracki_odbor.config import settings as settings_mod
from biracki_odbor.licensing.state import License, Mode, load_license
from biracki_odbor.logging_setup import log_timing

log = logging.getLogger(__name__)


def _read_legacy_nacelnik_name(election_config_path: Path) -> str:
    """Read a pre-migration nacelnik display name directly from the raw
    election_config.json, bypassing ElectionConfig (which no longer has
    the field). Checks both historical locations: the plain
    nacelnik_full_name field, and the older party_full_names["_default"]
    entry it was itself migrated from."""
    if not election_config_path.exists():
        return ""
    import json
    try:
        with election_config_path.open("r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    direct = str(d.get("nacelnik_full_name") or "").strip()
    if direct:
        return direct
    legacy = (d.get("party_full_names") or {}).get("_default", "")
    return str(legacy).strip()


class AppState(QObject):
    oik_changed = Signal()
    election_changed = Signal()
    generation_log_changed = Signal()
    master_changed = Signal()
    prosireni_master_changed = Signal()
    template_changed = Signal()
    # Emitted when Phase 2 finishes and stashes its ValidationReport.
    # Phase 2.5 «Сви чланови» listens to this to mark rows whose
    # JMBG has a matching error (light-red background + tooltip).
    # In-memory only — the master itself doesn't carry the report,
    # so a fresh app launch with an existing master clears it.
    phase2_report_changed = Signal()
    # Emitted whenever any persistent state was successfully saved to
    # disk (OIK constants, election config, app settings, template
    # path). The MainWindow's status bar listens to this to refresh
    # its "Аутосачувано пре N мин" indicator.
    saved = Signal()
    # Emitted after `reload_license` updates `self._license`. Wired
    # to the demo banner + Phase 1 cap so a successful activation in
    # the dialog flips the app to LICENSED without a restart.
    license_changed = Signal()
    # Emitted whenever the observer registry is saved. The Посматрачи
    # workspace tabs subscribe to refresh their views.
    posmatraci_changed = Signal()
    app_settings_changed = Signal()
    # Narrow siblings of election_changed / oik_changed. Решења/Измене
    # field edits (session date/number, number prefix, sub-number,
    # legal basis, authorization) and Пре/После/line spacing are typed
    # live and only matter to the decision screens -- emitting the broad
    # signal for them re-rendered every tab's preview and rebuilt the
    # Изборна конфигурација RIK cards on each edit. Same file on disk.
    resenja_fields_changed = Signal()
    document_format_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        # Must check existence BEFORE load() — oik_mod.load() returns a
        # default-populated OikConstants (nacelnik_full_name defaults to
        # DEFAULT_NACELNIK_ROLE, never blank) whether or not a real file
        # is on disk, so a blank-field check can no longer tell "nothing
        # saved yet" from "explicitly saved, happens to be non-blank".
        oik_path = app_paths.oik_constants_path()
        is_fresh_oik = not oik_path.exists()
        self._oik = oik_mod.load(oik_path)
        self._election = election_mod.load(app_paths.election_config_path())
        self._app_settings = settings_mod.load(app_paths.app_settings_path())
        # One-time migration: nacelnik_full_name moved from ElectionConfig
        # to OikConstants (the chief doesn't change between election
        # cycles, so "New election cycle" must not reset it — see
        # settings_election.py's _on_new_cycle). Pull forward whatever an
        # old election_config.json still has, reading the raw JSON since
        # ElectionConfig no longer parses this field at all. Saves once,
        # immediately, so this is a no-op on every subsequent launch.
        if is_fresh_oik:
            legacy = _read_legacy_nacelnik_name(app_paths.election_config_path())
            if legacy:
                self._oik.nacelnik_full_name = legacy
                oik_mod.save(self._oik, app_paths.oik_constants_path())
        from biracki_odbor.core import generation_log as _gl_mod
        self._generation_log = _gl_mod.load(
            app_paths.generation_log_path(),
            self._election.election_uuid,
        )
        # Wall-clock of the most recent successful save. None until the
        # first save in this session — the indicator stays blank until
        # then so a fresh launch with nothing yet saved doesn't claim
        # "Аутосачувано пре 0 мин".
        self._last_save_at: datetime | None = None
        # License is checked once at construction (and again on
        # explicit reload after activation). DISABLED when
        # `licensing_server_url` is blank — see state.load_license.
        self._license: License = load_license(
            licensing_server_url=self._app_settings.licensing_server_url,
            license_dat_path=app_paths.license_dat_path(),
        )
        # Most recent Phase 2 ValidationReport. None until Phase 2
        # runs in this session. Consumed by Phase 2.5 to mark rows
        # with errors.
        self._last_phase2_report = None
        # Observer registry — lazy-loaded on first access so the
        # startup path stays fast for operators without local elections.
        self._observer_registry = None

    @property
    def oik(self) -> oik_mod.OikConstants:
        return self._oik

    @property
    def election(self) -> election_mod.ElectionConfig:
        return self._election

    @property
    def app_settings(self) -> settings_mod.AppSettings:
        return self._app_settings

    @property
    def license(self) -> License:
        """Current license state. Always populated — DISABLED when
        licensing isn't configured (blank server URL)."""
        return self._license

    @property
    def demo_bm(self) -> int | None:
        """Demo mode covers one polling station -- the lowest-numbered,
        same choice as Phase 1's demo limit. None when licensed."""
        if not self._license.is_demo or not self._oik.polling_stations:
            return None
        return min(s.bm_number for s in self._oik.polling_stations)

    @property
    def generation_log(self):
        """Current GenerationLog for this election cycle."""
        return self._generation_log

    def save_generation_log(self) -> None:
        """Persist generation_log to disk and emit generation_log_changed."""
        from biracki_odbor.core import generation_log as _gl_mod
        _gl_mod.save(self._generation_log, app_paths.generation_log_path())
        self.generation_log_changed.emit()

    @log_timing("AppState.reload_generation_log")
    def reload_generation_log(self) -> None:
        """Re-read from disk (e.g. after election UUID changes) and emit signal."""
        from biracki_odbor.core import generation_log as _gl_mod
        self._generation_log = _gl_mod.load(
            app_paths.generation_log_path(),
            self._election.election_uuid,
        )
        self.generation_log_changed.emit()

    def _reload_generation_log_if_cycle_changed(self) -> None:
        """The log is keyed by election_uuid, so it only needs reloading
        when the cycle itself changed (Нови изборни циклус, restore) --
        not on every ordinary election save."""
        if self._generation_log.election_uuid != self._election.election_uuid:
            self.reload_generation_log()

    @property
    def last_phase2_report(self):
        """The most recent Phase 2 ValidationReport, or None.

        Returned object may be a `ValidationReport` from
        `biracki_odbor.core.models` or any duck-typed equivalent — the
        consumer (Phase 2.5 PersonsSubTab.set_error_report) only reads
        `.issues` with `.severity`, `.detail`, `.message_sr`.
        """
        return self._last_phase2_report

    def set_phase2_report(self, report) -> None:
        """Set the most recent Phase 2 report + emit signal.

        Phase 2 calls this on successful finish (or when there are
        errors but the operator chose to proceed). Pass None to clear
        — Phase 2.5's marking then disappears."""
        self._last_phase2_report = report
        self.phase2_report_changed.emit()

    def reload_license(self) -> None:
        """Re-read license.dat + recompute HID, emit `license_changed`.

        Called after the activation dialog accepts so the demo banner
        + Phase 1 cap flip to full mode without restarting the app.
        """
        self._license = load_license(
            licensing_server_url=self._app_settings.licensing_server_url,
            license_dat_path=app_paths.license_dat_path(),
        )
        self.license_changed.emit()

    def reload_oik(self) -> None:
        self._oik = oik_mod.load(app_paths.oik_constants_path())
        self.oik_changed.emit()

    def reload_election(self) -> None:
        self._election = election_mod.load(app_paths.election_config_path())
        self._reload_generation_log_if_cycle_changed()
        self.election_changed.emit()

    @log_timing("AppState.save_oik")
    def save_oik(self) -> None:
        oik_mod.save(self._oik, app_paths.oik_constants_path())
        self._mark_saved()
        self.oik_changed.emit()

    @log_timing("AppState.save_document_format")
    def save_document_format(self) -> None:
        """Persist oik.document_format; only the decision screens react."""
        oik_mod.save(self._oik, app_paths.oik_constants_path())
        self._mark_saved()
        self.document_format_changed.emit()

    @log_timing("AppState.save_election")
    def save_election(self) -> None:
        election_mod.save(self._election, app_paths.election_config_path())
        self._mark_saved()
        self._reload_generation_log_if_cycle_changed()
        self.election_changed.emit()

    @log_timing("AppState.save_resenja_fields")
    def save_resenja_fields(self) -> None:
        """Persist election config after a Решења/Измене field edit; only
        the decision screens react (see resenja_fields_changed)."""
        election_mod.save(self._election, app_paths.election_config_path())
        self._mark_saved()
        self.resenja_fields_changed.emit()

    def save_app_settings(self) -> None:
        settings_mod.save(self._app_settings, app_paths.app_settings_path())
        self._mark_saved()
        self.app_settings_changed.emit()

    # ── "Last saved at" tracking ──

    @property
    def last_save_at(self) -> datetime | None:
        """Wall-clock of the most recent successful save in this session.

        None when nothing has been saved yet — the indicator should
        stay blank in that case (a fresh first-launch app shouldn't
        claim a save it didn't make).
        """
        return self._last_save_at

    def _mark_saved(self) -> None:
        """Internal: bump the timestamp + emit `saved`."""
        self._last_save_at = datetime.now()
        self.saved.emit()

    # ── Template path (OIK-owned, used by Phase 1/2) ──

    def template_path(self) -> Path | None:
        """Configured template path; falls back to auto-find in sablon/.

        Raises `file_integrity.IntegrityMismatchError` if the resolved
        file's content no longer matches its last verified (app-driven)
        write — see core/file_integrity.py. Callers (Phase1Tab,
        Phase2Tab, ElectionSettingsTab) must catch this and show a
        distinct "tampered, restore or re-import" state rather than
        the generic "not configured" one.
        """
        configured = self._oik.template_path.strip()
        if configured:
            p = Path(configured)
            if p.exists():
                self._check_template_integrity(p)
                return p
        default = self.template_default_path()
        if default is not None:
            self._check_template_integrity(default)
        return default

    @staticmethod
    def _check_template_integrity(path: Path) -> None:
        from biracki_odbor.core import file_integrity
        file_integrity.check_or_raise(path)

    def set_template_path(self, path: Path | str | None) -> None:
        self._oik.template_path = str(path) if path else ""
        oik_mod.save(self._oik, app_paths.oik_constants_path())
        self._mark_saved()
        self.template_changed.emit()
        self.oik_changed.emit()

    # ── Default export/import folder (operator-owned, OIK Settings → System) ──

    def files_dir(self, purpose: str) -> Path:
        """Base folder for a file dialog, auto-creating a purpose subfolder.

        `default_files_dir` empty ⇒ operator hasn't configured one yet,
        falls back to Path.home() / "Documents". `purpose` is a short
        Cyrillic label (e.g. "Групе", "Расподела") so files from
        different features land in distinct, predictable subfolders
        instead of one flat pile.

        Over 40 call sites across the GUI treat this as a function that
        always returns a real, existing directory — file-open/save
        dialogs pass it straight through as their default path, export
        helpers build sub-paths under it — none of them are written to
        handle it raising. It used to, though: a configured
        `default_files_dir` pointing at a network share raised straight
        out of `mkdir()` the moment that share was unreachable (a drive
        not yet reconnected after sleep, a server briefly down).
        Reported from the field with exactly that configuration. Since
        this is invoked from ~40 different `clicked` slots, the failure
        was invisible each time: Qt swallows an exception escaping a
        slot (prints to stderr, doesn't crash), so the operator just saw
        nothing happen — no dialog, no export, no error — for whichever
        button they'd pressed.

        A folder that cannot currently be created or reached now falls
        back to the same Documents default used when nothing is
        configured, logged as a warning so it's diagnosable from
        app.log — matching the fallback that already existed for "not
        configured at all" rather than inventing a new failure mode.
        This does mean a file can land in Documents instead of the
        configured share on a day the share is down; the alternative
        (silently doing nothing when the operator clicks Извези) is
        worse, and the warning is there so a support call can trace it.
        """
        configured = self.app_settings.default_files_dir.strip()
        base = Path(configured) if configured else (Path.home() / "Documents")
        p = base / purpose
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            if not configured:
                raise  # the Documents fallback itself failing is a real, different problem
            log.warning(
                "files_dir: could not reach %r (default_files_dir=%r) --"
                " falling back to Documents", p, configured, exc_info=True,
            )
            p = Path.home() / "Documents" / purpose
            p.mkdir(parents=True, exist_ok=True)
        return p

    def export_generated(self, purpose: str, paths: Iterable[Path]) -> list[Path]:
        """Copy freshly-generated files into `files_dir(purpose)`,
        overwriting any same-named file left over from a previous run.

        Operators should never need to browse the app's own internal
        data folders to reach files they generated — every feature that
        produces take-away documents calls this right after generation
        so the result also lands in the operator's own export folder.

        Best-effort: a copy failure (e.g. destination file open in
        Excel/Word) is logged, not raised — an export hiccup must never
        mask a generation run's own success/failure.

        That contract used to be broken by its own first line:
        `files_dir(purpose)` calls `Path.mkdir()`, which is *not* inside
        the try/except below, so an unreachable destination (a network
        share that dropped, a removable drive that isn't plugged in)
        raised straight out of this "never raises" function. Reported
        from the field with `default_files_dir` set to a UNC network
        path — reproduced directly: a plain call to `export_generated()`
        against an unmapped drive raises `FileNotFoundError` before the
        copy loop is ever reached.

        The callers that matter most are Qt slots with no exception
        handling of their own — `_restore_from_log()` in phase1.py (also
        phase2/phase3/corrections/izmene) calls this and then, on the
        very next lines, enables the Пошаљи/Отвори buttons for that run.
        An uncaught raise here skips those lines, so the button is left
        exactly as its constructor set it: disabled. Worse, this same
        call happens unconditionally from `BasePhase1Tab.__init__`, which
        MainWindow builds with no try/except around it (`__main__.py`) —
        hit this at the wrong instant (the share still reconnecting after
        sleep/wake, right as the app starts) and the whole window fails
        to construct, silently, since this is a windowed build with no
        console and no installed excepthook.
        """
        try:
            dest_dir = self.files_dir(purpose)
        except OSError:
            log.warning(
                "export_generated: could not reach export folder for %r"
                " (default_files_dir=%r) -- nothing copied",
                purpose, self.app_settings.default_files_dir, exc_info=True,
            )
            return []
        copied: list[Path] = []
        for src in paths:
            dest = dest_dir / src.name
            try:
                shutil.copy2(src, dest)
                copied.append(dest)
            except OSError:
                log.warning("export_generated: failed to copy %s -> %s", src, dest, exc_info=True)
        return copied

    # ── Convenience paths ──

    @staticmethod
    def template_default_path() -> Path | None:
        """Look for Stalni_sastav.xlsx in sablon/ as the default."""
        sablon = app_paths.sablon_dir()
        for p in sablon.iterdir():
            if p.suffix.lower() == ".xlsx" and not p.name.startswith("~"):
                return p
        return None

    @property
    def onboarding_complete(self) -> bool:
        """True when minimum configuration is in place to run Phase 1.

        Deliberately lighter than validate() — excludes Phase-3-specific
        fields (session_date, number_prefix, legal_basis) which aren't
        needed before the first workflow run.
        """
        oik = self._oik
        ec = self._election
        if not oik.municipality.name.strip():
            return False
        if not oik.polling_stations:
            return False
        if not ec.election.dates.date_full.strip():
            return False
        if not ec.election.types:
            return False
        return True

    @staticmethod
    def master_path() -> Path:
        return app_paths.master_path()

    # ── Observer registry ─────────────────────────────────────────────

    @property
    def observer_registry(self):
        """Lazy-loaded ObserverRegistry for the current home directory."""
        if self._observer_registry is None:
            from biracki_odbor.core.observers import ObserverRegistry
            self._observer_registry = ObserverRegistry.load(
                app_paths.posmatraci_registry_path()
            )
        return self._observer_registry

    def save_observer_registry(self) -> None:
        """Persist the observer registry to disk and emit posmatraci_changed."""
        self.observer_registry.save(app_paths.posmatraci_registry_path())
        self._mark_saved()
        self.posmatraci_changed.emit()

    def reload_observer_registry(self) -> None:
        """Force re-read from disk (e.g. after restoring from backup)."""
        from biracki_odbor.core.observers import ObserverRegistry
        self._observer_registry = ObserverRegistry.load(
            app_paths.posmatraci_registry_path()
        )
        self.posmatraci_changed.emit()
