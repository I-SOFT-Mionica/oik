"""Detect generated documents an operator has since edited by hand.

Operators (especially older ones) legitimately fine-tune решења in Word
after generating them. Regenerating used to overwrite those edits
silently. A manifest next to the documents records each file's hash at
generation time; a file whose content no longer matches was edited.

Files from before the manifest existed fall back to "modified after the
last generation run" (the generation log timestamp).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from biracki_odbor.core.file_integrity import compute_hash

log = logging.getLogger(__name__)

MANIFEST_NAME = ".generisano.json"
_MTIME_SLACK_S = 5


def _load(folder: Path) -> dict[str, str]:
    try:
        return json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_generated(folder: Path, paths: list[Path], keep: set[str] = frozenset()) -> None:
    """Remember the generated content of `paths`. Names in `keep` (files the
    operator chose to preserve) keep their previous entry, so they are
    still recognised as hand-edited next time."""
    manifest = _load(folder)
    for p in paths:
        if p.name in keep and p.name in manifest:
            continue
        manifest[p.name] = compute_hash(p)
    try:
        (folder / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8",
        )
    except OSError:
        log.warning("could not write %s", folder / MANIFEST_NAME, exc_info=True)


def hand_edited(folder: Path, last_generated_iso: str = "") -> list[Path]:
    """Documents in `folder` whose content differs from what was generated."""
    if not folder.exists():
        return []
    manifest = _load(folder)
    since = None
    if last_generated_iso:
        try:
            since = datetime.fromisoformat(last_generated_iso).timestamp()
        except ValueError:
            since = None
    edited = []
    for p in sorted(folder.glob("*.docx")):
        if p.name.startswith("~$"):
            continue  # Word's lock file while the document is open
        recorded = manifest.get(p.name)
        if recorded is not None:
            if compute_hash(p) != recorded:
                edited.append(p)
        elif since is not None and p.stat().st_mtime > since + _MTIME_SLACK_S:
            edited.append(p)
    return edited
