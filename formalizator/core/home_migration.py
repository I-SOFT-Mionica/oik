"""Carry an existing working directory over when the app was renamed.

The app shipped its data under `~/Celik` before it was renamed to
Formalizator. Moving the folder is not enough on its own: both
catalogs store *absolute* paths into it (a calibrated template's
frozen background PDF, an export template's pristine source
spreadsheet), so a plain rename would leave every one of them pointing
at a folder that no longer exists — the calibration a template
represents is expensive, hand-tuned work, so losing it silently is the
worst possible outcome of a rename.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR_NAME = "Formalizator"
LEGACY_DIR_NAME = "Celik"
LEGACY_DB_NAME = "celik.db"
DB_NAME = "formalizator.db"


def default_home() -> Path:
    """The app's working directory, migrating a pre-rename one across
    the first time. Lives in core so GUI modules can resolve it without
    importing each other in a circle."""
    home = Path.home() / APP_DIR_NAME
    migrate_legacy_home(home)
    home.mkdir(parents=True, exist_ok=True)
    return home


def saved_pdf_dir() -> Path:
    """Where "Сачувај као PDF" (core.print_pdf.SAVE_AS_PDF) keeps a
    filled declaration instead of printing it.

    Deliberately not the fill-out screen's own preview folder — that
    one lives under the system temp directory and is wiped on exit
    (cleanup_previews()), which is right for a live preview but wrong
    here: choosing "save as PDF" means the file itself is the
    deliverable, so it has to survive past the session that made it."""
    d = default_home() / "Сачуване изјаве"
    d.mkdir(parents=True, exist_ok=True)
    return d

# (index file, key holding an absolute path into the working directory)
_PATH_KEYS = (
    (Path("templates") / "catalog.json", "background_pdf_path"),
    (Path("export_templates.json"), "source_file"),
)


def _rewrite_paths(index_path: Path, key: str, old_root: Path, new_root: Path) -> int:
    if not index_path.exists():
        return 0
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read %s for path rewriting: %s", index_path, exc)
        return 0

    old_text = str(old_root)
    rewritten = 0
    for entry in entries:
        value = entry.get(key)
        if not value:
            continue
        # Compare case-insensitively without normalising separators away:
        # these were written on Windows by this same app, so they match
        # the old root verbatim apart from case.
        if value.lower().startswith(old_text.lower()):
            entry[key] = str(new_root) + value[len(old_text):]
            rewritten += 1

    if rewritten:
        index_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return rewritten


def migrate_legacy_home(new_home: Path, legacy_home: Path | None = None) -> bool:
    """Move a pre-rename `~/Celik` working directory to `new_home`.

    Returns True when something was actually migrated. Does nothing if
    the new home already exists — an operator who has started using the
    renamed app keeps what they have, and the old folder is left alone
    rather than merged blindly.
    """
    new_home = Path(new_home)
    legacy_home = Path(legacy_home) if legacy_home is not None else new_home.parent / LEGACY_DIR_NAME

    if new_home.exists() or not legacy_home.is_dir():
        return False

    shutil.move(str(legacy_home), str(new_home))
    log.info("migrated working directory %s -> %s", legacy_home, new_home)

    legacy_db = new_home / LEGACY_DB_NAME
    if legacy_db.exists() and not (new_home / DB_NAME).exists():
        legacy_db.rename(new_home / DB_NAME)

    for relative, key in _PATH_KEYS:
        _rewrite_paths(new_home / relative, key, legacy_home, new_home)

    return True
