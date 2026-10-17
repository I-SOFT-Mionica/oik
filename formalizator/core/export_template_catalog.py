"""Local catalog of cumulative-export layouts (`ExportTemplateDef`).

Same "small JSON index under the app's data directory" pattern as
`core.template_catalog` — export templates are reusable across
sessions, independent of which `CalibratedTemplate` produced the
entries being exported, so they get their own catalog rather than
living inside a `CalibratedTemplate`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from formalizator.core.models import ExportColumnDef, ExportTemplateDef

_INDEX_FILENAME = "export_templates.json"

# The calibration wizard's "JMBG as 13 positioned digit boxes" key
# describes a printing layout and resolves to nothing in a spreadsheet.
# It was briefly offered in the export field picker too, so templates
# saved then carry it and silently exported a blank JMBG column —
# rewritten to the plain whole-number key on load so an already-saved
# template fixes itself instead of needing to be re-mapped by hand.
_LEGACY_FIELD_KEYS = {"__jmbg_comb__": "jmbg"}


def _index_path(catalog_dir: Path | str) -> Path:
    return Path(catalog_dir) / _INDEX_FILENAME


def load_catalog(catalog_dir: Path | str) -> list[ExportTemplateDef]:
    path = _index_path(catalog_dir)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    templates = []
    for d in raw:
        columns = []
        for c in d.get("columns", []):
            c = dict(c)
            c["field_keys"] = [
                _LEGACY_FIELD_KEYS.get(k, k) for k in c.get("field_keys", [])
            ]
            columns.append(ExportColumnDef(**c))
        templates.append(ExportTemplateDef(
            name=d["name"], columns=columns,
            source_file=d.get("source_file", ""),
            header_row=d.get("header_row", 1),
            sort_column_1=d.get("sort_column_1", ""),
            sort_column_2=d.get("sort_column_2", ""),
        ))
    return templates


def save_template(catalog_dir: Path | str, template: ExportTemplateDef) -> None:
    """Add or replace (by name) an export template in the catalog."""
    catalog_dir = Path(catalog_dir)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    templates = [t for t in load_catalog(catalog_dir) if t.name != template.name]
    templates.append(template)
    _write_catalog(catalog_dir, templates)


def remove_template(catalog_dir: Path | str, name: str) -> None:
    templates = [t for t in load_catalog(catalog_dir) if t.name != name]
    _write_catalog(Path(catalog_dir), templates)


def find_by_name(catalog_dir: Path | str, name: str) -> ExportTemplateDef | None:
    for t in load_catalog(catalog_dir):
        if t.name == name:
            return t
    return None


def _write_catalog(catalog_dir: Path, templates: list[ExportTemplateDef]) -> None:
    data = [
        {
            "name": t.name, "columns": [asdict(c) for c in t.columns],
            "source_file": t.source_file, "header_row": t.header_row,
            "sort_column_1": t.sort_column_1, "sort_column_2": t.sort_column_2,
        }
        for t in templates
    ]
    _index_path(catalog_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
