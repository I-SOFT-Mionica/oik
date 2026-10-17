"""App-wide preferences (not OIK or election data).

Stored at `~/Biracki_Odbor/app_settings.json`. Currently holds the debug
logging toggle; future app-level switches land here too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from biracki_odbor.core.observers import (
    CardSetup, LegitimacijaBlock, default_legitimacija_layout,
)


@dataclass
class PosmatraciSettings:
    """Settings for the observer accreditation workflow.

    The legitimacija layout is an ordered list of LegitimacijaBlock
    instances that the OIK composes in Посматрачи → Легитимација.
    card_setup holds the physical card and paper dimensions.
    """

    card_setup: CardSetup = field(default_factory=CardSetup)
    legitimacija_layout: list[LegitimacijaBlock] = field(
        default_factory=default_legitimacija_layout,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_setup": self.card_setup.to_dict(),
            "legitimacija_layout": [b.to_dict() for b in self.legitimacija_layout],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PosmatraciSettings":
        raw_layout = d.get("legitimacija_layout")
        if raw_layout and isinstance(raw_layout, list):
            layout = [LegitimacijaBlock.from_dict(b) for b in raw_layout]
        else:
            layout = default_legitimacija_layout()
        raw_setup = d.get("card_setup")
        card_setup = CardSetup.from_dict(raw_setup) if isinstance(raw_setup, dict) else CardSetup()
        # Backward-compat: old saves had cards_per_page but no card_setup.
        # We silently ignore cards_per_page — card_setup.cards_per_sheet() now computes it.
        return cls(
            card_setup=card_setup,
            legitimacija_layout=layout,
        )


@dataclass
class AppSettings:
    debug_logging: bool = False
    # Base URL of the I-SOFT license server (waterworks-derived).
    # Empty string ⇒ licensing is DISABLED — app runs in full mode,
    # no activation flow, updater falls back to the original GitHub
    # Releases polling. This is the default so existing dev / CI
    # workflows don't need a server. Production installs ship with
    # the URL pre-set via the release-build configuration.
    licensing_server_url: str = ""
    # Preferred e-mail client backend for Phase 1 send-to-parties and
    # backup e-mail. Values map to `integrations.email_client.EmailClient`:
    # "auto" picks the first available (Outlook before Thunderbird),
    # "outlook" / "thunderbird" pin a specific one. Validated at use
    # time — an unrecognised string falls back to AUTO. Default AUTO
    # means existing installs keep their Outlook behavior unchanged
    # when Outlook is installed.
    email_client: str = "auto"
    # OIK's own e-mail address. Used to filter Thunderbird inbox scans
    # to the single account that receives party replies, avoiding a full
    # walk of every account on a multi-account Thunderbird install.
    oik_email: str = ""
    # Načelnik's e-mail address — remembered after the first nacelnik
    # send so the operator doesn't have to retype it each time.
    nacelnik_email: str = ""
    # UI display language. "sr" loads biracki_sr.qm (Serbian Cyrillic).
    # "en" skips loading any translator — English source strings show directly.
    # Takes effect on next application launch.
    ui_language: str = "sr"
    # When True, _refresh_tab_states() enables all tabs regardless of workflow
    # progress — useful for reviewing or correcting content out of order.
    disable_tab_gating: bool = False
    # Background-task stall timeout, in seconds. Any operation started via
    # gui/worker.py's start_worker() (Outlook/Thunderbird inbox fetch, Phase
    # 1/2/3 generation, etc.) or the in-app update download abandons the
    # wait and reports failure if it goes this long without progress. 0
    # disables the timeout (wait forever, old behavior). See gui/worker.py
    # module docstring for why this exists — cross-thread progress/finished
    # signals were observed to silently vanish in the packaged build,
    # leaving an indeterminate progress bar spinning forever with no way
    # for the operator to tell a stalled task from a slow one.
    worker_stall_timeout_seconds: int = 180
    # Base folder for export/import file dialogs (parties, lists, matrix,
    # observers, bm.xlsx, reports, PDF converter, etc). Empty ⇒ not yet
    # configured by the operator, falls back to Path.home() / "Documents".
    # Each dialog auto-creates a purpose subfolder under this base (e.g.
    # "Групе", "Расподела") — see AppState.files_dir(). Dialogs tied to
    # the app's own managed data (načelnik chief template, backups) are
    # NOT affected — those keep their functional app-internal defaults.
    default_files_dir: str = ""
    posmatraci: PosmatraciSettings = field(default_factory=PosmatraciSettings)
    # App version that last ran on this machine. Compared against the
    # running __version__ at startup to detect an upgrade and trigger
    # any one-time reconciliation (e.g. core/master_io.py's legacy
    # xlsx-master -> SQLite import). Empty ⇒ never recorded (fresh
    # install or pre-this-field data) — treated as "reconcile if needed".
    last_run_version: str = ""
    # Key into core.maintenance's action registry, or "" for none pending.
    # Set by code (e.g. a startup reconciliation step) when a one-off
    # operator-triggered cleanup becomes available; surfaced as a hidden-
    # by-default button in Поставке ОИК → Систем that only appears while
    # this is non-empty, and clears itself (button disappears again) once
    # the operator runs it. See core/maintenance.py.
    pending_maintenance_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "debug_logging": self.debug_logging,
            "licensing_server_url": self.licensing_server_url,
            "email_client": self.email_client,
            "oik_email": self.oik_email,
            "nacelnik_email": self.nacelnik_email,
            "ui_language": self.ui_language,
            "disable_tab_gating": self.disable_tab_gating,
            "worker_stall_timeout_seconds": self.worker_stall_timeout_seconds,
            "default_files_dir": self.default_files_dir,
            "posmatraci": self.posmatraci.to_dict(),
            "last_run_version": self.last_run_version,
            "pending_maintenance_action": self.pending_maintenance_action,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppSettings":
        return cls(
            debug_logging=bool(d.get("debug_logging", False)),
            licensing_server_url=str(d.get("licensing_server_url", "")),
            email_client=str(d.get("email_client", "auto")),
            oik_email=str(d.get("oik_email", "")),
            nacelnik_email=str(d.get("nacelnik_email", "")),
            ui_language=str(d.get("ui_language", "sr")),
            disable_tab_gating=bool(d.get("disable_tab_gating", False)),
            worker_stall_timeout_seconds=int(d.get("worker_stall_timeout_seconds", 180)),
            default_files_dir=str(d.get("default_files_dir", "")),
            posmatraci=PosmatraciSettings.from_dict(d.get("posmatraci") or {}),
            last_run_version=str(d.get("last_run_version", "")),
            pending_maintenance_action=str(d.get("pending_maintenance_action", "")),
        )


def load(path: Path | str) -> AppSettings:
    p = Path(path)
    if not p.exists():
        return AppSettings()
    try:
        with p.open("r", encoding="utf-8") as f:
            return AppSettings.from_dict(json.load(f))
    except (OSError, json.JSONDecodeError):
        return AppSettings()


def save(settings: AppSettings, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(p)
