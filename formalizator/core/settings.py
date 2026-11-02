"""Formalizator's settings store — <home>/settings.json.

One place for every machine-local preference, mirroring OIK's
config/settings.py: a dataclass, `load()` / `save()`, atomic writes.
Planned features add their fields here (signing image and certificate,
OIK-form filling, ...) instead of growing files of their own.

Unknown keys in the file are kept on save, so an older Formalizator
never erases what a newer one stored. Secrets never go here: the PIN
for qualified signing is entered in the card middleware's own dialog.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from formalizator.core.home_migration import default_home

log = logging.getLogger(__name__)

SETTINGS_NAME = "settings.json"


@dataclass
class FormalizatorSettings:
    # Čelik API DLL for the ID-card reader. MUP periodically ships a new
    # one for newer card chips; the operator can point here at a newer
    # copy without waiting for a Formalizator release. "" = default
    # lookup (bundled copy, then MUP's system install).
    celik_dll_path: str = ""
    # Smart-card reader to read ID cards from, by its Windows name
    # (eid_reader.list_readers()). "" = the first reader, which is all a
    # single-reader PC needs.
    card_reader_name: str = ""

    # Keys this version doesn't know, carried through unchanged.
    _extra: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "_extra"}
        return {**self._extra, **d}

    @classmethod
    def from_dict(cls, d: dict) -> "FormalizatorSettings":
        known = {f.name for f in fields(cls)} - {"_extra"}
        s = cls(
            celik_dll_path=str(d.get("celik_dll_path") or ""),
            card_reader_name=str(d.get("card_reader_name") or ""),
        )
        s._extra = {k: v for k, v in d.items() if k not in known}
        return s


def settings_path(home: Path | None = None) -> Path:
    return (home or default_home()) / SETTINGS_NAME


def load(home: Path | None = None) -> FormalizatorSettings:
    p = settings_path(home)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return FormalizatorSettings()
    except (OSError, ValueError):
        log.warning("Formalizator settings unreadable, using defaults: %s", p)
        return FormalizatorSettings()
    return FormalizatorSettings.from_dict(data if isinstance(data, dict) else {})


def save(settings: FormalizatorSettings, home: Path | None = None) -> None:
    p = settings_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
