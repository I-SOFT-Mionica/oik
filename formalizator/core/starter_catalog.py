"""Seed the bundled starter forms into a fresh working directory.

Calibrating an official form is the expensive, one-time step — days of
font and position tuning went into the original Mionica document — so
shipping an empty catalog would mean every new machine repeating work
that is already done. The forms calibrated for this cycle travel with
the app instead (`resources/starter/`) and are copied out on first run.

Seeding is per-template and additive, matching the OIK app's own
"seed-on-first-run" handling of user-tunable data: a starter form is
installed only when no template of that name exists yet, so an operator
who edited or deleted one never has their version overwritten by an
upgrade, while an upgrade that adds a brand-new form still delivers it.

Bundled indexes store a bare filename rather than an absolute path —
the install directory isn't known until it exists — and the real
absolute path is written as each file is copied into place.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _starter_root() -> Path:
    """The bundled starter files, at dev time and inside a PyInstaller
    one-file bundle (which unpacks datas under `sys._MEIPASS`)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "formalizator" / "resources" / "starter"
    return Path(__file__).resolve().parent.parent / "resources" / "starter"


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return []


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_index(
    *, bundled_index: Path, target_index: Path, path_key: str, asset_dir: Path,
) -> list[str]:
    """Copy any not-yet-present bundled entry into `target_index`,
    materialising the file named by `path_key` into `asset_dir` and
    rewriting the entry to point at it absolutely."""
    bundled = _load(bundled_index)
    if not bundled:
        return []

    existing = _load(target_index)
    known = {e.get("name") for e in existing}
    added: list[str] = []

    for entry in bundled:
        if entry.get("name") in known:
            continue
        filename = entry.get(path_key) or ""
        source = bundled_index.parent / filename
        if filename and source.exists():
            asset_dir.mkdir(parents=True, exist_ok=True)
            destination = asset_dir / filename
            if not destination.exists():
                shutil.copyfile(source, destination)
            entry[path_key] = str(destination)
        existing.append(entry)
        added.append(entry.get("name", ""))

    if added:
        _write(target_index, existing)
        log.info("seeded starter entries into %s: %s", target_index, added)
    return added


def seed(home_dir: Path | str, catalog_dir: Path | str) -> list[str]:
    """Install any missing starter forms. Returns the names added."""
    home_dir = Path(home_dir)
    catalog_dir = Path(catalog_dir)
    root = _starter_root()
    if not root.is_dir():
        return []

    added = _seed_index(
        bundled_index=root / "catalog.json",
        target_index=catalog_dir / "catalog.json",
        path_key="background_pdf_path",
        asset_dir=catalog_dir,
    )
    added += _seed_index(
        bundled_index=root / "export_templates.json",
        target_index=home_dir / "export_templates.json",
        path_key="source_file",
        asset_dir=home_dir / "export_sources",
    )
    return added
