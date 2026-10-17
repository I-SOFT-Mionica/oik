"""Regression: preflight_phase3 must check the fields for the workflow
that's actually running, not stalni's regardless of spec.

Field report: generating a prosireni решење flagged "Документ: поље
'legal_basis' је празно" even though the operator had filled in the
prosireni-specific 'legal_basis_prosireni' field — the check was
hardcoded to stalni's field names ("number_prefix"/"legal_basis",
"session_date") instead of reading them off the WorkflowSpec.
"""

from __future__ import annotations

from biracki_odbor.config.election import (
    DocumentInfo, ElectionConfig, ElectionDates, ElectionInfo,
)
from biracki_odbor.config.oik import OikConstants
from biracki_odbor.core.workflow import PROSIRENI_SPEC, STALNI_SPEC
from biracki_odbor.validation import preflight
from biracki_odbor.validation.reports import Codes
from tests.test_phase1 import _make_oik


def _election_with_only(**doc_fields) -> ElectionConfig:
    return ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date="6. децембра 2026. године",
                session_date_prosireni="6. децембра 2026. године",
            ),
        ),
        document=DocumentInfo(**doc_fields),
    )


def test_stalni_preflight_checks_stalni_fields(tmp_path) -> None:
    election = _election_with_only(
        number_prefix_prosireni="013-5-31",
        legal_basis_prosireni="На основу члана 39...",
    )
    report = preflight.preflight_phase3(
        tmp_path / "zbirna.xlsx", OikConstants(), election, spec=STALNI_SPEC,
    )
    detail_blob = " ".join(i.detail or "" for i in report.issues)
    assert "number_prefix" in detail_blob
    assert "legal_basis" in detail_blob
    assert "number_prefix_prosireni" not in detail_blob
    assert "legal_basis_prosireni" not in detail_blob


def test_prosireni_preflight_checks_prosireni_fields_not_stalni(tmp_path) -> None:
    """The exact field bug: stalni's fields are empty but prosireni's own
    are filled in — prosireni's own preflight must be satisfied, not
    blocked on stalni's blank fields."""
    election = _election_with_only(
        number_prefix_prosireni="013-5-31",
        legal_basis_prosireni="На основу члана 39...",
    )
    report = preflight.preflight_phase3(
        tmp_path / "zbirna.xlsx", OikConstants(), election, spec=PROSIRENI_SPEC,
    )
    detail_blob = " ".join(i.detail or "" for i in report.issues)
    assert "number_prefix_prosireni" not in detail_blob
    assert "legal_basis_prosireni" not in detail_blob


def test_prosireni_preflight_flags_its_own_empty_fields(tmp_path) -> None:
    election = _election_with_only(
        number_prefix="013-5-30",
        legal_basis="На основу члана 35...",
    )
    report = preflight.preflight_phase3(
        tmp_path / "zbirna.xlsx", OikConstants(), election, spec=PROSIRENI_SPEC,
    )
    codes = {i.code for i in report.issues}
    assert Codes.ELECTION_INCOMPLETE in codes
    detail_blob = " ".join(i.detail or "" for i in report.issues)
    assert "number_prefix_prosireni" in detail_blob
    assert "legal_basis_prosireni" in detail_blob


def test_prosireni_preflight_checks_its_own_session_date_field() -> None:
    """session_date_field is also workflow-specific (session_date vs
    session_date_prosireni) — same class of bug as the legal_basis one."""
    election = ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date="6. децембра 2026. године",   # stalni filled
                session_date_prosireni="",                  # prosireni empty
            ),
        ),
        document=DocumentInfo(
            number_prefix_prosireni="013-5-31",
            legal_basis_prosireni="На основу члана 39...",
        ),
    )
    report = preflight.preflight_phase3(
        "no_such_file.xlsx", OikConstants(), election, spec=PROSIRENI_SPEC,
    )
    detail_blob = " ".join(i.detail or "" for i in report.issues)
    assert "датум седнице није унет" in detail_blob


# ── Cross-workflow JMBG collision — the real block, moved here from the
#    DB layer (see master_io's schema history). Field report: a client
#    loaded prosireni before stalni; the old DB-level trigger fired on
#    whichever workflow aggregated SECOND and silently blanked its copy
#    of the colliding JMBG instead of surfacing it as a fixable error.


def _full_election() -> ElectionConfig:
    return ElectionConfig(
        election=ElectionInfo(
            dates=ElectionDates(
                date_full="17. децембар 2026. године",
                session_date="6. децембра 2026. године",
                session_date_prosireni="6. децембра 2026. године",
            ),
        ),
        document=DocumentInfo(
            number_prefix="013-5-30", legal_basis="На основу члана 35...",
            number_prefix_prosireni="013-5-31", legal_basis_prosireni="На основу члана 39...",
        ),
    )


def test_preflight_blocks_on_cross_workflow_jmbg_collision(tmp_path) -> None:
    from biracki_odbor.core import master_io
    from biracki_odbor.core.models import Person

    db = tmp_path / "committee.db"
    shared_jmbg = "1605991774818"
    master_io.write_master(
        [Person(bm_number=1, function="Члан [1]", party="ent1",
                first_name="Ана", last_name="Анић", jmbg=shared_jmbg)],
        OikConstants(), db, spec=PROSIRENI_SPEC,
    )
    stalni_persons = [Person(bm_number=1, function="Председник", party="СНС",
                              first_name="Ана", last_name="Анић", jmbg=shared_jmbg)]

    report = preflight.preflight_phase3(
        db, OikConstants(), _full_election(), spec=STALNI_SPEC, persons=stalni_persons,
    )
    assert report.errors
    assert Codes.PERSON_IN_OTHER_WORKFLOW in {i.code for i in report.issues}


def test_preflight_does_not_block_without_collision(tmp_path) -> None:
    from biracki_odbor.core import master_io
    from biracki_odbor.core.models import Person

    db = tmp_path / "committee.db"
    master_io.write_master(
        [Person(bm_number=1, function="Члан [1]", party="ent1",
                first_name="Ана", last_name="Анић", jmbg="1605991774818")],
        OikConstants(), db, spec=PROSIRENI_SPEC,
    )
    stalni_persons = [Person(bm_number=1, function="Председник", party="СНС",
                              first_name="Марко", last_name="Марковић", jmbg="0202980774807")]

    report = preflight.preflight_phase3(
        db, OikConstants(), _full_election(), spec=STALNI_SPEC, persons=stalni_persons,
    )
    assert Codes.PERSON_IN_OTHER_WORKFLOW not in {i.code for i in report.issues}


def test_preflight_without_persons_arg_skips_cross_workflow_check(tmp_path) -> None:
    """Backward compatibility: `persons` is optional and defaults to no
    check, rather than crashing an older call site that hasn't been
    updated to pass it."""
    report = preflight.preflight_phase3(
        tmp_path / "zbirna.xlsx", OikConstants(), _full_election(), spec=STALNI_SPEC,
    )
    assert Codes.PERSON_IN_OTHER_WORKFLOW not in {i.code for i in report.issues}
