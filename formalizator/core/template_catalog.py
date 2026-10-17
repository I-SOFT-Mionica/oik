"""Local catalog of already-calibrated templates.

Same "bundle it, don't over-build a sync mechanism" philosophy as the
OIK app's `config/opstine.py` municipality registry: a small JSON
index next to the catalog's background PDFs, under the app's data
directory. The operator picks an existing entry before falling back to
calibrating a new official document from scratch — calibration is the
expensive, one-time step (days of font/position tuning went into the
Mionica original), so reuse is the whole point.

Ships with whatever starter templates have actually been calibrated
(see `resources/templates/` — seeded once real official documents are
in hand, not fabricated ahead of that) rather than nothing at all.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from formalizator.core.models import CalibratedTemplate, CustomFieldDef, FieldPosition

_INDEX_FILENAME = "catalog.json"


def _index_path(catalog_dir: Path | str) -> Path:
    return Path(catalog_dir) / _INDEX_FILENAME


def load_catalog(catalog_dir: Path | str) -> list[CalibratedTemplate]:
    path = _index_path(catalog_dir)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    templates = []
    for d in raw:
        positions = [FieldPosition(**p) for p in d.get("positions", [])]
        custom_fields = [CustomFieldDef(**c) for c in d.get("custom_fields", [])]
        templates.append(CalibratedTemplate(
            name=d["name"], background_pdf_path=d["background_pdf_path"],
            positions=positions, custom_fields=custom_fields,
            form_id=d.get("form_id", ""),
            year=d.get("year", ""), municipality=d.get("municipality", ""),
            calibrated_at=d.get("calibrated_at", ""),
        ))
    return templates


def save_template(catalog_dir: Path | str, template: CalibratedTemplate) -> None:
    """Add or replace (by name) a calibrated template in the catalog."""
    catalog_dir = Path(catalog_dir)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    templates = [t for t in load_catalog(catalog_dir) if t.name != template.name]
    templates.append(template)
    _write_catalog(catalog_dir, templates)


def remove_template(catalog_dir: Path | str, name: str) -> None:
    templates = [t for t in load_catalog(catalog_dir) if t.name != name]
    _write_catalog(Path(catalog_dir), templates)


def find_by_name(catalog_dir: Path | str, name: str) -> CalibratedTemplate | None:
    for t in load_catalog(catalog_dir):
        if t.name == name:
            return t
    return None


def _write_catalog(catalog_dir: Path, templates: list[CalibratedTemplate]) -> None:
    data = [
        {
            "name": t.name, "background_pdf_path": t.background_pdf_path,
            "positions": [asdict(p) for p in t.positions],
            "custom_fields": [asdict(c) for c in t.custom_fields],
            "form_id": t.form_id, "year": t.year, "municipality": t.municipality,
            "calibrated_at": t.calibrated_at,
        }
        for t in templates
    ]
    _index_path(catalog_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
