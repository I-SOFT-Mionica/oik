"""JMBG (Yugoslav personal ID) validation — MOD 11 checksum.

JMBG format: 13 digits.
  Positions  0..6 : date of birth (DDMMYYY) and region
  Positions  7..11: unique sequence
  Position  12   : MOD 11 check digit

Checksum: weights [7,6,5,4,3,2,7,6,5,4,3,2] over first 12 digits.
  remainder = total % 11
  remainder == 0  → check digit must be 0
  remainder == 1  → JMBG invalid (no valid check digit)
  else            → check digit = 11 - remainder

This module is the single source of truth for JMBG validation across
the app. The Excel-side conditional-formatting formula in
core.phase1_generate uses the same arithmetic.
"""

from __future__ import annotations

import re
from datetime import date

_JMBG_RE = re.compile(r"^\d{13}$")
_WEIGHTS = (7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def normalize(value: object) -> str:
    """Coerce arbitrary cell content to a 13-digit JMBG string, or empty.

    Handles the real-world mess from Excel cells:
      - None → ""
      - int / float (e.g. 0101990710001 stored as number) → padded string
      - str with whitespace → stripped
      - any non-numeric input → ""
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value).zfill(13)
    if isinstance(value, float):
        if not value.is_integer():
            return ""
        return str(int(value)).zfill(13)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return s  # preserve user input as-is for format checks
        return ""
    return ""


def is_valid(jmbg: object) -> bool:
    """True iff JMBG passes both shape and MOD 11 checksum."""
    s = normalize(jmbg)
    if not _JMBG_RE.match(s):
        return False
    digits = [int(c) for c in s]
    total = sum(w * digits[i] for i, w in enumerate(_WEIGHTS))
    remainder = total % 11
    if remainder == 0:
        check = 0
    elif remainder == 1:
        return False
    else:
        check = 11 - remainder
    return digits[12] == check


def gender(jmbg: object) -> str | None:
    """Return "M" or "F" from a valid JMBG, or None if not derivable.

    Positions 10-12 (1-indexed) form a 3-digit serial encoding the holder's
    sex: 000-499 → male, 500-999 → female. Equivalently, the 10th digit
    alone suffices: 0-4 → male, 5-9 → female.

    Returns None for malformed JMBG (caller should rely on `is_valid` for
    the full structural check; this helper is intentionally permissive on
    the checksum so it can be called on partially-typed input).
    """
    s = normalize(jmbg)
    if not _JMBG_RE.match(s):
        return None
    d = int(s[9])
    return "M" if d <= 4 else "F"


def extract_date_of_birth(jmbg: object) -> date | None:
    """Return the birthdate encoded in a JMBG, or None if unparseable.

    Doesn't run MOD-11 here — `is_valid` is the gate when correctness
    matters. Format guard only (13 digits after normalize). Returns
    None when:
      - Wrong length / non-digits.
      - Day / month / year combos that aren't a real calendar date
        (e.g. 31 of February, day 32, month 13).

    Century disambiguation rule:
      yyy < 500  → 2000 + yyy   (born 2000-2499; in practice 2000-2099)
      yyy ≥ 500  → 1000 + yyy   (born 1500-1999; in practice 1900-1999)
    Standard Yugoslav convention; 1900-1999 use 900-999, 2000-2099
    use 000-099.
    """
    s = normalize(jmbg)
    if not _JMBG_RE.match(s):
        return None
    try:
        day = int(s[0:2])
        month = int(s[2:4])
        yyy = int(s[4:7])
    except ValueError:
        return None
    year = 2000 + yyy if yyy < 500 else 1000 + yyy
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_at_least_18_on(jmbg: object, on_date: date) -> bool:
    """True iff the JMBG-encoded person is ≥ 18 years old on `on_date`.

    The check uses the date of birth precisely — someone born on
    1990-06-15 is exactly 18 on 2008-06-15, not 2008-06-14. This
    matches Serbian electoral law (and common-law birthday rule)
    where the person reaches age N on the anniversary date itself,
    not the day before.

    Returns False when the JMBG is unparseable (bad length, non-digits,
    or unreal date). Safe default — the caller can surface a distinct
    "ЈМБГ није исправан" error instead of "млађи од 18".
    """
    dob = extract_date_of_birth(jmbg)
    if dob is None:
        return False
    age = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        age -= 1
    return age >= 18


# Serials 480-499 (male) and 980-999 (female): a region would need ~480
# births of one sex on a single day to reach them, which no Serbian
# registry ever has. So these numbers pass every check but belong to
# nobody -- use them for demo and sample data, never real-looking ones.
FICTIONAL_SERIAL_MALE = 480
FICTIONAL_SERIAL_FEMALE = 980


def fictional(day: int, month: int, year: int, female: bool, n: int = 0) -> str:
    """A checksum-valid JMBG that no real person holds (see above).

    `n` picks among the 20 fictional serials for the same birth date."""
    base = FICTIONAL_SERIAL_FEMALE if female else FICTIONAL_SERIAL_MALE
    for k in range(20):
        first12 = f"{day:02d}{month:02d}{year % 1000:03d}77{base + (n + k) % 20:03d}"
        remainder = sum(int(c) * w for c, w in zip(first12, _WEIGHTS)) % 11
        if remainder == 1:
            continue
        return first12 + str(0 if remainder == 0 else 11 - remainder)
    raise ValueError("no fictional serial fits this date")


def is_fictional(jmbg: object) -> bool:
    """True for numbers made by `fictional()`."""
    s = normalize(jmbg)
    if not is_valid(s):
        return False
    serial = int(s[9:12])
    return 480 <= serial <= 499 or 980 <= serial <= 999


def excel_validation_formula(cell_ref: str) -> str:
    """Excel formula returning TRUE iff cell_ref holds a valid JMBG.

    Used by Phase 1 to drop conditional formatting + the paste-resistant
    Провера column formula into per-party files so users get green/red
    feedback while filling in.

    The formula mirrors `is_valid`: 13-digit check, weighted sum, MOD 11.
    Wrapped in IFERROR because Excel's AND() does NOT short-circuit —
    when `cell_ref` is shorter than 13 chars, `VALUE(MID(cell_ref,13,1))`
    raises #VALUE! and propagates through AND, which then propagates
    through the consumer's IF, ending up as #VALUE! in the Провера
    column. With IFERROR, any internal error collapses to FALSE so the
    cell shows "✗" / red and the operator sees the JMBG as invalid
    instead of seeing nothing.
    """
    parts: list[str] = []
    for i, w in enumerate(_WEIGHTS):
        parts.append(f"{w}*VALUE(MID({cell_ref},{i + 1},1))")
    weighted_sum = "+".join(parts)
    return (
        f'=IFERROR(AND('
        f'LEN({cell_ref})=13,'
        f'ISNUMBER(VALUE({cell_ref})),'
        f'MOD({weighted_sum},11)<>1,'
        f'VALUE(MID({cell_ref},13,1))=IF(MOD({weighted_sum},11)=0,0,11-MOD({weighted_sum},11))'
        f'),FALSE)'
    )
