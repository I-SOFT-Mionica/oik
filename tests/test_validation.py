"""Tests for validation modules."""

from __future__ import annotations

from biracki_odbor.core.models import Person
from biracki_odbor.validation import rows
from biracki_odbor.validation.reports import Codes
from tests.test_jmbg import VALID_SAMPLES


def _good_person(**overrides) -> Person:
    defaults = dict(
        bm_number=1,
        function="Председник",
        party="СНС",
        first_name="Петар",
        last_name="Петровић",
        jmbg=VALID_SAMPLES[0],
        mesto="Уб",
        adresa="Краља Петра 1",
        telefon="0641234567",
        email="petar@example.com",
    )
    # Tests pass `name=` for convenience — split into first/last fields
    # so the helper signature stays ergonomic.
    if "name" in overrides:
        text = overrides.pop("name").strip()
        if " " in text:
            defaults["first_name"], defaults["last_name"] = text.rsplit(" ", 1)
        else:
            defaults["first_name"], defaults["last_name"] = text, ""
    defaults.update(overrides)
    return Person(**defaults)


def test_clean_person_no_issues() -> None:
    assert rows.validate_person(_good_person()) == []


def test_empty_person_no_issues() -> None:
    """A blank slot is OK — it just hasn't been filled in yet."""
    p = Person(bm_number=1, function="Председник", party="СНС")
    assert rows.validate_person(p) == []


def test_bad_jmbg_format() -> None:
    issues = rows.validate_person(_good_person(jmbg="123"))
    codes = {i.code for i in issues}
    assert Codes.JMBG_BAD_FORMAT in codes


def test_bad_jmbg_checksum() -> None:
    issues = rows.validate_person(_good_person(jmbg="1234567890123"))
    codes = {i.code for i in issues}
    assert Codes.JMBG_BAD_CHECKSUM in codes


def test_non_cyrillic_name_warning() -> None:
    issues = rows.validate_person(_good_person(name="Petar Petrovic"))
    by_code = {i.code: i for i in issues}
    assert Codes.NAME_NON_CYRILLIC in by_code
    assert by_code[Codes.NAME_NON_CYRILLIC].severity == "warning"


def test_short_phone_warning() -> None:
    issues = rows.validate_person(_good_person(telefon="12345"))
    by_code = {i.code: i for i in issues}
    assert Codes.PHONE_TOO_SHORT in by_code
    assert by_code[Codes.PHONE_TOO_SHORT].severity == "warning"


def test_unknown_function_error() -> None:
    issues = rows.validate_person(_good_person(function="Нешто"))
    codes = {i.code for i in issues}
    assert Codes.FUNCTION_UNKNOWN in codes


def test_prosireni_function_without_spec_is_still_flagged_unknown() -> None:
    """Without spec=, prosireni's own bracket-numbered function strings
    are correctly indistinguishable from garbage -- confirms the
    "before" behavior that made every prosireni row fail this check."""
    issues = rows.validate_person(_good_person(function="Члан [1]"))
    codes = {i.code for i in issues}
    assert Codes.FUNCTION_UNKNOWN in codes


def test_prosireni_function_with_spec_is_not_flagged_unknown() -> None:
    """Field report: every prosireni Phase 2 run showed a spurious
    FUNCTION_UNKNOWN error -- prosireni's function strings ("Члан [1]",
    "Заменик члана [1]", ...) never appear in the fixed stalni
    FUNCTIONS tuple. spec=PROSIRENI_SPEC switches to the bracket-slot
    parser instead."""
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    for func in ("Члан [1]", "Заменик члана [1]", "Члан [12]", "Заменик члана [3]"):
        issues = rows.validate_person(_good_person(function=func), spec=PROSIRENI_SPEC)
        codes = {i.code for i in issues}
        assert Codes.FUNCTION_UNKNOWN not in codes, f"{func!r} wrongly flagged"


def test_prosireni_spec_still_flags_genuinely_malformed_function() -> None:
    from biracki_odbor.core.workflow import PROSIRENI_SPEC
    issues = rows.validate_person(_good_person(function="Нешто чудно"), spec=PROSIRENI_SPEC)
    codes = {i.code for i in issues}
    assert Codes.FUNCTION_UNKNOWN in codes


def test_stalni_spec_explicitly_passed_uses_fixed_functions_tuple() -> None:
    """spec=STALNI_SPEC (explicit, not just the None default) must not
    accidentally take the prosireni branch."""
    from biracki_odbor.core.workflow import STALNI_SPEC
    issues = rows.validate_person(_good_person(function="Председник"), spec=STALNI_SPEC)
    assert Codes.FUNCTION_UNKNOWN not in {i.code for i in issues}
    issues = rows.validate_person(_good_person(function="Члан [1]"), spec=STALNI_SPEC)
    assert Codes.FUNCTION_UNKNOWN in {i.code for i in issues}


def test_find_duplicate_jmbgs() -> None:
    p1 = _good_person(bm_number=1, function="Председник", party="СНС")
    p2 = _good_person(bm_number=2, function="Члан 1", party="СПС")  # same JMBG
    p3 = _good_person(bm_number=3, function="Председник", party="ДС", jmbg=VALID_SAMPLES[1])
    issues = rows.find_duplicate_jmbgs([p1, p2, p3])
    assert len(issues) == 1
    assert issues[0].code == Codes.JMBG_DUPLICATE
    assert issues[0].detail == VALID_SAMPLES[0]


def test_gender_match_no_warning() -> None:
    """Male name + male JMBG (10th digit < 5) → no JMBG_GENDER_MISMATCH."""
    # VALID_SAMPLES[0] is built from "010199071000" → 10th digit = "1" → male
    issues = rows.validate_person(_good_person(
        first_name="Петар", last_name="Петровић", jmbg=VALID_SAMPLES[0],
    ))
    codes = {i.code for i in issues}
    assert Codes.JMBG_GENDER_MISMATCH not in codes


def test_gender_mismatch_female_name_male_jmbg() -> None:
    """Female name + male JMBG → warning."""
    issues = rows.validate_person(_good_person(
        first_name="Ана", last_name="Петровић", jmbg=VALID_SAMPLES[0],
    ))
    codes = {i.code for i in issues}
    assert Codes.JMBG_GENDER_MISMATCH in codes


def test_gender_mismatch_male_name_female_jmbg() -> None:
    """Male name + female JMBG → warning. Construct a JMBG with digit 10 = '5'."""
    from tests.test_jmbg import _build_valid
    female_jmbg = _build_valid("010199070500")  # position 10 = "5" → female
    issues = rows.validate_person(_good_person(
        first_name="Марко", last_name="Петровић", jmbg=female_jmbg,
    ))
    by_code = {i.code: i for i in issues}
    assert Codes.JMBG_GENDER_MISMATCH in by_code
    assert by_code[Codes.JMBG_GENDER_MISMATCH].severity == "warning"


def test_male_a_ending_exception_no_warning() -> None:
    """Никола ends in -а but is male. Don't fire a false-positive warning."""
    issues = rows.validate_person(_good_person(
        first_name="Никола", last_name="Тесла", jmbg=VALID_SAMPLES[0],
    ))
    codes = {i.code for i in issues}
    assert Codes.JMBG_GENDER_MISMATCH not in codes


def test_gender_check_skipped_when_jmbg_invalid() -> None:
    """Cross-check shouldn't fire when JMBG itself fails checksum."""
    issues = rows.validate_person(_good_person(
        first_name="Ана", last_name="Петровић", jmbg="1234567890123",
    ))
    codes = {i.code for i in issues}
    # Bad checksum is the only JMBG-related error here.
    assert Codes.JMBG_BAD_CHECKSUM in codes
    assert Codes.JMBG_GENDER_MISMATCH not in codes


def test_validation_report_aggregation() -> None:
    from biracki_odbor.core.models import Issue, ValidationReport
    r = ValidationReport()
    r.add(Issue(code="A", message_sr="x", severity="error"))
    r.add(Issue(code="B", message_sr="y", severity="warning"))
    assert not r.ok
    assert len(r.errors) == 1
    assert len(r.warnings) == 1
