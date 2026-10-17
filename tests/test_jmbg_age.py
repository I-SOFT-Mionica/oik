"""Tests for the new date-of-birth + 18+ helpers in `core/jmbg.py`.

Companion to the existing `tests/test_jmbg.py` (which covers MOD-11 +
normalize + gender + Excel formula). Keeping these in a separate file
so the new helpers don't bury the older tests' diff.

Covers:
  - Birthdate extraction across both century branches (yyy < 500 →
    2000s, yyy ≥ 500 → 1900s).
  - Malformed inputs (wrong length, non-digits, unreal calendar dates).
  - Age calculation against election day — on the anniversary, the
    day before, after, and one-day-shy edge cases (the bug operators
    care about most when verifying a list submitted right at cutoff).
  - Leap-day birthdays handled without raising.
"""

from __future__ import annotations

from datetime import date

from biracki_odbor.core.jmbg import (
    extract_date_of_birth, is_at_least_18_on,
)


# ── Birthdate extraction ──────────────────────────────────────────


def test_extract_dob_20th_century() -> None:
    """yyy ≥ 500 → 1000 + yyy. JMBG 1605991... = 16 May 1991."""
    assert extract_date_of_birth("1605991774818") == date(1991, 5, 16)


def test_extract_dob_20th_century_boundary() -> None:
    """yyy = 900 → 1900; yyy = 999 → 1999. Lowest + highest of the
    20th-century band. We don't care about checksum validity here —
    this helper is intentionally permissive on MOD-11."""
    assert extract_date_of_birth("0101900770010") == date(1900, 1, 1)
    assert extract_date_of_birth("3112999770010") == date(1999, 12, 31)


def test_extract_dob_21st_century() -> None:
    """yyy < 500 → 2000 + yyy. JMBG 0101005... = 1 Jan 2005."""
    assert extract_date_of_birth("0101005770010") == date(2005, 1, 1)


def test_extract_dob_21st_century_boundary() -> None:
    """yyy = 000 → 2000; yyy = 099 → 2099."""
    assert extract_date_of_birth("0101000770010") == date(2000, 1, 1)
    assert extract_date_of_birth("0101099770010") == date(2099, 1, 1)


def test_extract_dob_leap_day() -> None:
    """Feb 29 on leap years parses normally; on non-leap years returns
    None rather than crashing (calendar-date validation kicks in)."""
    assert extract_date_of_birth("2902996774806") == date(1996, 2, 29)
    assert extract_date_of_birth("2902997770010") is None


def test_extract_dob_rejects_wrong_length() -> None:
    """Anything but exactly 13 digits returns None — defensive guard
    so a non-Yugoslav string doesn't crash callers that forgot to
    pre-validate."""
    assert extract_date_of_birth("123") is None
    assert extract_date_of_birth("12345678901234") is None
    assert extract_date_of_birth("") is None


def test_extract_dob_rejects_non_digits() -> None:
    assert extract_date_of_birth("abcdefghijklm") is None
    assert extract_date_of_birth("1605-91770022") is None


def test_extract_dob_rejects_impossible_dates() -> None:
    """day=32 / month=13 / Feb-30 are all None, not exceptions."""
    assert extract_date_of_birth("3201990770010") is None
    assert extract_date_of_birth("0113990770010") is None
    assert extract_date_of_birth("3002990770010") is None


def test_extract_dob_accepts_int_form() -> None:
    """JMBG often arrives as a numeric Excel cell; the underlying
    `normalize` helper pads back to 13 digits. The DOB extractor
    must work on that form too."""
    # JMBG starting with leading zero stored as int loses it.
    assert extract_date_of_birth(101990770010) == date(1990, 1, 1)


# ── 18+ check against election date ───────────────────────────────


def test_at_least_18_after_birthday() -> None:
    """Born 1990-05-16; election 2026-05-17 — they're 36, well past 18."""
    assert is_at_least_18_on("1605990774806", date(2026, 5, 17))


def test_at_least_18_exact_birthday() -> None:
    """Eighteenth birthday IS the day you become 18 — Serbian electoral
    convention. So someone born 2008-06-05 voting 2026-06-05 qualifies."""
    assert is_at_least_18_on("0506008770010", date(2026, 6, 5))


def test_under_18_day_before_birthday() -> None:
    """One day before their 18th — they're still 17. Must reject."""
    assert not is_at_least_18_on("0506008770010", date(2026, 6, 4))


def test_under_18_recent_birth() -> None:
    """A 10-year-old is not eligible to be on an OIK committee."""
    assert not is_at_least_18_on("0506016770010", date(2026, 6, 5))


def test_at_least_18_returns_false_on_bad_jmbg() -> None:
    """Unparseable JMBG → False (the caller surfaces a separate
    'JMBG malformed' error; this function never raises)."""
    assert not is_at_least_18_on("not-a-jmbg", date(2026, 6, 5))
    assert not is_at_least_18_on("", date(2026, 6, 5))


def test_age_check_month_boundary() -> None:
    """Born 15 March; election day 14 March — anniversary hasn't yet
    arrived this year, so age is decremented. Common one-day-shy bug."""
    jmbg = "1503008770010"  # 15 March 2008
    assert not is_at_least_18_on(jmbg, date(2026, 3, 14))
    assert is_at_least_18_on(jmbg, date(2026, 3, 15))
