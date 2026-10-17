"""Tests for biracki_odbor.core.jmbg.

Test JMBGs are computed (not real people's IDs). We build a known-good
13-digit string by picking 12 digits and computing the legal check digit.
"""

from __future__ import annotations

import pytest

from biracki_odbor.core import jmbg


def _build_valid(prefix12: str) -> str:
    """Compute the MOD 11 check digit for a 12-digit prefix and append it."""
    assert len(prefix12) == 12 and prefix12.isdigit()
    digits = [int(c) for c in prefix12]
    weights = (7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    total = sum(w * digits[i] for i, w in enumerate(weights))
    remainder = total % 11
    if remainder == 1:
        # prefix produces an invalid JMBG; bump last digit to dodge it
        new_prefix = prefix12[:-1] + str((int(prefix12[-1]) + 1) % 10)
        return _build_valid(new_prefix)
    check = 0 if remainder == 0 else 11 - remainder
    return prefix12 + str(check)


VALID_SAMPLES = [
    _build_valid("010199071000"),
    _build_valid("150385715002"),
    _build_valid("030270890001"),
    _build_valid("121280715005"),
    _build_valid("250790710008"),
]

INVALID_SAMPLES = [
    "",
    "1234567890123",  # 13 digits but bad checksum (random)
    "0101990710001",  # bad checksum (random)
    "abc",
    "12345678901234",  # 14 digits
    "123456789012",   # 12 digits
    None,
    "0101 990710001",  # space in middle
]


@pytest.mark.parametrize("j", VALID_SAMPLES)
def test_valid_jmbgs_pass(j: str) -> None:
    assert jmbg.is_valid(j)


@pytest.mark.parametrize("j", INVALID_SAMPLES)
def test_invalid_jmbgs_fail(j: object) -> None:
    assert not jmbg.is_valid(j)


def test_int_jmbg_accepted() -> None:
    """Excel sometimes stores a JMBG as a numeric cell — must work."""
    s = VALID_SAMPLES[0]
    assert jmbg.is_valid(int(s))


def test_float_integer_jmbg_accepted() -> None:
    s = VALID_SAMPLES[0]
    assert jmbg.is_valid(float(s))


def test_float_with_fraction_rejected() -> None:
    assert not jmbg.is_valid(1234567890123.5)


def test_none_rejected() -> None:
    assert not jmbg.is_valid(None)


def test_bool_rejected() -> None:
    """bool is a subclass of int in Python; must not be accepted as JMBG."""
    assert not jmbg.is_valid(True)
    assert not jmbg.is_valid(False)


def test_leading_zero_int_padding() -> None:
    """A JMBG starting with 0 stored as int loses the leading zero — we pad."""
    s = _build_valid("010199071000")  # starts with '0'
    as_int = int(s)
    assert jmbg.is_valid(as_int), f"int form {as_int} should pad back to {s}"


def test_normalize_strips_whitespace() -> None:
    s = VALID_SAMPLES[0]
    assert jmbg.normalize(f"  {s}  ") == s


def test_normalize_empty() -> None:
    assert jmbg.normalize(None) == ""
    assert jmbg.normalize("") == ""
    assert jmbg.normalize("abc") == ""


def test_excel_formula_shape() -> None:
    """Sanity check: the formula must reference the cell and use MOD 11."""
    f = jmbg.excel_validation_formula("F5")
    assert "F5" in f
    assert "MOD(" in f
    assert "LEN(F5)=13" in f


def test_excel_formula_uses_iferror_wrapper() -> None:
    """Regression: wrong-length pastes (e.g. `abc`) made VALUE(MID(...,13,1))
    raise #VALUE!. AND() doesn't short-circuit so the error propagated to
    the Провера cell, which then never matched the CF "=N4=\"✗\"" rule and
    stayed un-tinted. IFERROR around the whole AND collapses any internal
    error to FALSE → Провера shows "✗" → CF fires red."""
    f = jmbg.excel_validation_formula("G4")
    assert f.startswith("=IFERROR(AND("), (
        f"expected IFERROR wrap; got prefix: {f[:30]!r}"
    )
    assert f.endswith(",FALSE)")


# ── Gender helper ───────────────────────────────────────────


def test_gender_male_low_digit() -> None:
    # Position 10 of "010199071000" (1-indexed) is "1" → male.
    j = _build_valid("010199071000")
    assert jmbg.gender(j) == "M"


def test_gender_female_high_digit() -> None:
    # Position 10 of "010199070500" is "5" → female (5XX serial range).
    j = _build_valid("010199070500")
    assert jmbg.gender(j) == "F"


def test_gender_invalid_returns_none() -> None:
    assert jmbg.gender("") is None
    assert jmbg.gender(None) is None
    assert jmbg.gender("abc") is None
    assert jmbg.gender("123") is None


def test_gender_skips_checksum_validation() -> None:
    """Gender is derivable from a structurally-13-digit string even if the
    checksum is wrong — used to surface mismatches during partial entry."""
    assert jmbg.gender("0101990710001") in ("M", "F")
