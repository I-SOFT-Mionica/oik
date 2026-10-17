"""One-off, operator-triggered maintenance actions.

Some code changes leave behind artifacts that are safe to clean up
later but shouldn't be deleted automatically without the operator's
awareness (e.g. legacy files kept as a migration safety net). This is
a small, reusable registry rather than a one-shot script: a future
change registers a new action here and sets
`AppSettings.pending_maintenance_action` to its key when the condition
that makes it relevant occurs. `gui/tabs/settings_oik.py`'s System tab
shows a single button for whatever action is pending — hidden by
default, visible only while a key is set, and cleared (hidden again,
persisted so it stays hidden on next launch) once the operator runs it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class MaintenanceAction:
    key: str
    label_sr: str
    description_sr: str
    run: Callable[[], str]  # returns a short human-readable result summary


def _cleanup_legacy_migration_files() -> str:
    """Removes the `.migrated` legacy per-workflow xlsx masters (and their
    now-orphaned file_integrity sidecar entries, keyed to the pre-rename
    filename) left behind by the 2026-08 SQLite migration — see
    core/master_io.py's `reconcile_legacy_xlsx_masters()`. The data was
    already imported into committee.db and confirmed working; this only
    removes the now-unneeded backup copies.
    """
    from biracki_odbor import app_paths
    from biracki_odbor.core.workflow import all_specs

    removed: list[str] = []
    for spec in all_specs():
        legacy = app_paths.legacy_xlsx_master_path_for(spec)
        candidates = [
            legacy.with_name(legacy.name + ".migrated"),
            legacy.parent / ".verified" / f"{legacy.name}.json",
            legacy.parent / ".verified" / legacy.name,
        ]
        for f in candidates:
            if f.exists():
                try:
                    f.unlink()
                    removed.append(f.name)
                except OSError:
                    log.exception("cleanup_legacy_migration_files: could not remove %s", f)
    if not removed:
        return "Ништа за чишћење — датотеке су већ уклоњене."
    return f"Уклоњено: {', '.join(removed)}."


_REGISTRY: dict[str, MaintenanceAction] = {
    "cleanup_legacy_migration_files": MaintenanceAction(
        key="cleanup_legacy_migration_files",
        label_sr="Очисти преостале датотеке миграције",
        description_sr=(
            "Уклања резервне (.migrated) копије старих xlsx master фајлова"
            " остављене приликом преласка на дељену SQLite базу"
            " (committee.db). Подаци су већ увезени — ово само чисти"
            " неискоришћене остатке."
        ),
        run=_cleanup_legacy_migration_files,
    ),
}


def get(key: str) -> MaintenanceAction | None:
    return _REGISTRY.get(key)
