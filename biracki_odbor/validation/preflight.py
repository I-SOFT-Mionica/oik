"""Pre-flight checks: run before each phase, surface in Cyrillic.

Each function takes the inputs the phase will receive and returns a
ValidationReport. The GUI gates the action button on `report.ok`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from biracki_odbor.config.election import ElectionConfig
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.config.schema import require_keys
from biracki_odbor.core.models import Issue, Person, ValidationReport
from biracki_odbor.validation import rows as row_checks
from biracki_odbor.validation.reports import Codes, message


# ── Helpers ────────────────────────────────────────────────────────────

def _check_file(path: Path | str, into: ValidationReport) -> bool:
    p = Path(path)
    if not p.exists() or not p.is_file():
        into.add(Issue(
            code=Codes.FILE_MISSING,
            message_sr=message(Codes.FILE_MISSING, file=str(p)),
            severity="error",
            file=str(p),
        ))
        return False
    return True


def _check_oik(oik: OikConstants, into: ValidationReport) -> None:
    for err in oik.validate():
        into.add(Issue(
            code=Codes.OIK_INCOMPLETE,
            message_sr=message(Codes.OIK_INCOMPLETE, detail=err),
            severity="error",
            detail=err,
        ))


def _check_election(election: ElectionConfig, into: ValidationReport) -> None:
    for err in election.validate():
        into.add(Issue(
            code=Codes.ELECTION_INCOMPLETE,
            message_sr=message(Codes.ELECTION_INCOMPLETE, detail=err),
            severity="error",
            detail=err,
        ))


def _check_workbook_sheets(
    path: Path | str,
    required_sheets: Iterable[str],
    into: ValidationReport,
) -> None:
    import openpyxl
    p = Path(path)
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    except PermissionError:
        into.add(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(p)),
            severity="error",
            file=str(p),
        ))
        return
    except Exception as e:  # malformed xlsx
        into.add(Issue(
            code=Codes.FILE_LOCKED,
            message_sr=message(Codes.FILE_LOCKED, file=str(p)) + f" ({e})",
            severity="error",
            file=str(p),
        ))
        return
    try:
        names = set(wb.sheetnames)
        for sheet in required_sheets:
            if sheet not in names:
                into.add(Issue(
                    code=Codes.SHEET_MISSING,
                    message_sr=message(Codes.SHEET_MISSING, file=p.name, sheet=sheet),
                    severity="error",
                    file=str(p), sheet=sheet,
                ))
    finally:
        wb.close()


# ── Public OIK check ──────────────────────────────────────────────────

def check_oik(oik: OikConstants) -> list[Issue]:
    """Return OIK completeness errors as a flat list of Issues."""
    report = ValidationReport()
    _check_oik(oik, report)
    return report.issues


# ── Per-phase pre-flights ──────────────────────────────────────────────

def preflight_phase1(
    template_path: Path | str,
    oik: OikConstants,
) -> ValidationReport:
    report = ValidationReport()
    if _check_file(template_path, report):
        _check_workbook_sheets(template_path, ["Raspodela"], report)
    _check_oik(oik, report)
    return report


def preflight_phase2(
    template_path: Path | str,
    popunjeni_dir: Path | str,
    oik: OikConstants,
) -> ValidationReport:
    report = ValidationReport()
    if _check_file(template_path, report):
        _check_workbook_sheets(template_path, ["Raspodela"], report)
    _check_oik(oik, report)

    d = Path(popunjeni_dir)
    if not d.exists() or not d.is_dir():
        report.add(Issue(
            code=Codes.FILE_MISSING,
            message_sr=message(Codes.FILE_MISSING, file=str(d)),
            severity="error",
            file=str(d),
        ))
    else:
        xlsx_files = [
            f for f in d.iterdir()
            if f.is_file() and f.suffix.lower() == ".xlsx" and not f.name.startswith("~")
        ]
        if not xlsx_files:
            report.add(Issue(
                code=Codes.POPUNJENI_EMPTY,
                message_sr=message(Codes.POPUNJENI_EMPTY),
                severity="error",
            ))
    return report


def preflight_phase3(
    zbirana_path: Path | str,
    oik: OikConstants,
    election: ElectionConfig,
    parties_in_data: Iterable[str] = (),
    spec: object = None,
    persons: Iterable[Person] = (),
) -> ValidationReport:
    report = ValidationReport()
    _check_file(zbirana_path, report)
    _check_oik(oik, report)
    _check_election(election, report)

    # Cross-workflow JMBG collision: the actual block belongs here, not at
    # Phase 2 import time (see core/master_io.py's schema history) —
    # producing a решење that appoints an already-double-seated person is
    # the costly mistake; importing the data is always soft-flagged only.
    # `persons` is optional (defaults to empty, i.e. no check) so callers
    # that haven't been updated yet don't silently lose this check — they
    # just don't get it, same as before this was added.
    if persons:
        from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
        other_spec = STALNI_SPEC if getattr(spec, "slug", "stalni") == "prosireni" else PROSIRENI_SPEC
        other_jmbgs = row_checks.other_workflow_filled_jmbgs(zbirana_path, other_spec)
        if other_jmbgs:
            for issue in row_checks.find_cross_workflow_duplicate_jmbgs(
                list(persons), other_jmbgs, other_spec.resenja_item_i_intro,
            ):
                report.add(issue)
    session_date_field = getattr(spec, "session_date_field", "session_date")
    if not getattr(election.election.dates, session_date_field, "").strip():
        report.add(Issue(
            code=Codes.ELECTION_INCOMPLETE,
            message_sr=message(
                Codes.ELECTION_INCOMPLETE,
                detail="Избори: датум седнице није унет",
            ),
            severity="error",
            detail="Избори: датум седнице није унет",
        ))
    # number_prefix/legal_basis are owned by Phase 3's own UI (moved out
    # of the Election Settings tab), so they're checked here rather than
    # in ElectionConfig.validate() — same reasoning as session_date above.
    # Стални and проширени keep separate Document fields (see WorkflowSpec's
    # number_prefix_field / resenja_legal_basis_key) — check the pair that
    # matches this workflow, not stalni's regardless of which spec is running.
    number_prefix_field = getattr(spec, "number_prefix_field", "number_prefix")
    legal_basis_field = getattr(spec, "resenja_legal_basis_key", "legal_basis")
    for err in require_keys(
        election.document.to_dict(), [number_prefix_field, legal_basis_field], "Документ"
    ):
        report.add(Issue(
            code=Codes.ELECTION_INCOMPLETE,
            message_sr=message(Codes.ELECTION_INCOMPLETE, detail=err),
            severity="error",
            detail=err,
        ))

    # Party-name match check (warnings, not errors — _default exists)
    for party in parties_in_data:
        _, matched = election.party_full_name(party, oik.nacelnik_full_name)
        if not matched:
            report.add(Issue(
                code=Codes.PARTY_UNMATCHED,
                message_sr=message(Codes.PARTY_UNMATCHED, detail=party),
                severity="warning",
                detail=party,
            ))

    return report
