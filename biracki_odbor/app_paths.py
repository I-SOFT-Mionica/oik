"""Filesystem layout for the installed app.

All paths derive from a single base directory (default: %USERPROFILE%\\OIK).
The installer creates this layout; the GUI reads from it. When running
from source for development we still default to the same location so
behavior matches the installed app.

Override via BIRACKI_ODBOR_HOME env var for tests or alternate installs.
"""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """Return the app base directory, creating it if absent."""
    override = os.environ.get("BIRACKI_ODBOR_HOME")
    if override:
        p = Path(override)
    else:
        p = Path(os.path.expanduser("~")) / "OIK"
    p.mkdir(parents=True, exist_ok=True)
    return p


def oik_constants_path() -> Path:
    return home() / "oik_constants.json"


def election_config_path() -> Path:
    return home() / "election_config.json"


def corrections_log_path() -> Path:
    return home() / "corrections.log"


def sablon_dir() -> Path:
    p = home() / "sablon"
    p.mkdir(parents=True, exist_ok=True)
    return p


def stranke_dir() -> Path:
    p = home() / "stranka_fajlovi"
    p.mkdir(parents=True, exist_ok=True)
    return p


def popunjeni_dir() -> Path:
    p = home() / "popunjeni"
    p.mkdir(parents=True, exist_ok=True)
    return p


def popunjeni_odbijeno_dir() -> Path:
    """Rejected / late-submission holding dir for the стални workflow."""
    p = home() / "popunjeni_odbijeno"
    p.mkdir(parents=True, exist_ok=True)
    return p


def master_dir() -> Path:
    p = home() / "master"
    p.mkdir(parents=True, exist_ok=True)
    return p


def committee_db_path() -> Path:
    """Shared SQLite store for both workflows' master roster (see
    `core/master_io.py`). Replaces the old per-workflow `.xlsx` masters."""
    return master_dir() / "committee.db"


def master_path() -> Path:
    return committee_db_path()


def resenja_dir() -> Path:
    p = home() / "resenja"
    p.mkdir(parents=True, exist_ok=True)
    return p


def audit_dir() -> Path:
    """Output dir for accountability-log .docx files (combined + per-party).

    Separated from resenja/ because the accountability log is a meta
    output about the run itself (which file was used + every manual
    edit), not a per-БМ решење. Keeps the two artifact kinds visually
    sorted for the operator.
    """
    p = home() / "audit"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_dir() -> Path:
    p = home() / "log"
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_settings_path() -> Path:
    return home() / "app_settings.json"


def license_dat_path() -> Path:
    """The single-line JWT blob the licensing server issued at activation.

    No directory wrapper — sits directly under HOME so the technician
    can see it when looking at the working folder. Contents are the
    raw JWT (header.payload.signature) returned by
    POST /api/v1/biracki/activate.
    """
    return home() / "license.dat"


def places_genitive_path() -> Path:
    return home() / "places_genitive.json"


def places_prepositions_path() -> Path:
    return home() / "places_prepositions.json"


def obrazlozenje_path() -> Path:
    """User-editable obrazloženje (Phase 3 решење explanation) template."""
    return home() / "obrazlozenje.json"


def posmatraci_registry_path() -> Path:
    """Path to the observer-accreditation registry (orgs + observers +
    legitimacija layout)."""
    return home() / "posmatraci.json"


def popunjeni_cache_path() -> Path:
    """Path to the persistent popunjeni-aggregation cache + allowlist."""
    cache_dir = home() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "popunjeni.json"


def changelog_cache_path() -> Path:
    """Path to the cached server-fetched "what's new" changelog.

    Best-effort — the About page falls back to its built-in list if
    this is missing, stale, or unreadable."""
    cache_dir = home() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "changelog.json"


SUBDIRS = (
    # Workflow-independent
    "sablon", "cache", "log", "resenja_izmene",
    # Observer accreditation
    "posmatraci", "posmatraci/liste", "posmatraci/legitimacije",
    # Стални workflow
    "stranka_fajlovi", "popunjeni", "popunjeni_odbijeno",
    "master", "resenja", "audit",
    # Проширени workflow
    "stranka_fajlovi_prosireni", "popunjeni_prosireni", "popunjeni_odbijeno_prosireni",
    "master_prosireni", "resenja_prosireni", "audit_prosireni",
)


# ── Spec-aware helpers (prošireni + future workflows) ─────────────────
#
# Import WorkflowSpec lazily (inside the functions) to avoid a circular
# dependency: workflow.py → models.py; app_paths.py is imported by almost
# everything so a top-level import would create a cycle.


def workflow_subdir(subdir: str) -> Path:
    """Return `home() / subdir`, creating it if absent."""
    p = home() / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p


def stranke_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.stranke_subdir)  # type: ignore[union-attr]


def popunjeni_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.popunjeni_subdir)  # type: ignore[union-attr]


def popunjeni_odbijeno_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.popunjeni_odbijeno_subdir)  # type: ignore[union-attr]


def master_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.master_subdir)  # type: ignore[union-attr]


def master_path_for(spec: object) -> Path:
    return committee_db_path()


def legacy_xlsx_master_path_for(spec: object) -> Path:
    """Where a workflow's master `.xlsx` used to live, pre-SQLite-migration.

    Used only by the one-time startup reconciliation step to find old
    data to import — `master_path`/`master_path_for` above no longer
    point here."""
    return master_dir_for(spec) / spec.paths.master_filename  # type: ignore[union-attr]


def resenja_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.resenja_subdir)  # type: ignore[union-attr]


def audit_dir_for(spec: object) -> Path:
    return workflow_subdir(spec.paths.audit_subdir)  # type: ignore[union-attr]


def obrazlozenje_path_for(spec: object) -> Path:
    """User-editable obrazloženje template for the given workflow."""
    fname = getattr(spec, "obrazlozenje_filename", None)
    return home() / fname if fname else obrazlozenje_path()


def izmene_dir() -> Path:
    """Output dir for amendment resolution .docx files."""
    p = home() / "resenja_izmene"
    p.mkdir(parents=True, exist_ok=True)
    return p


def prestanak_dir() -> Path:
    """Output dir for чл. 15 cessation-of-function .docx files."""
    p = home() / "resenja_prestanak"
    p.mkdir(parents=True, exist_ok=True)
    return p


def izmena_obrazlozenje_path_for(slug: str) -> Path:
    """Editable amendment obrazlozenje template, one file per composition type."""
    return home() / f"izmena_obrazlozenje_{slug}.json"


def generation_log_path() -> Path:
    """Path to the per-election-cycle generation tracking file."""
    return home() / "generation_log.json"


def corrections_log_path_for(spec: object) -> Path:
    """Corrections log path for the given workflow.

    Stalni → corrections.log; prosireni → corrections_prosireni.log.
    Separate files so each workflow's accountability log covers only
    its own manual edits.
    """
    slug = getattr(spec, "slug", "stalni")
    if slug == "prosireni":
        return home() / "corrections_prosireni.log"
    return corrections_log_path()
