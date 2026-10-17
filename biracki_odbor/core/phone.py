"""Phone number clean-up — one canonical form wherever a number comes in.

Parties type numbers every way imaginable ("064 123-4567", "064/123 45 67",
"+381 64 1234567"), and Excel turns a number typed without a text format
into 641234567, dropping the leading zero. Everything is stored as digits
in Serbian national format: 0641234567.

  - spaces, dashes, slashes, dots and brackets are removed
  - +381 / 00381 / a bare 381 country prefix becomes 0
  - 8–9 digits with no leading 0 (Excel ate it) get the 0 back
  - other international numbers keep their leading +

Anything that still isn't digits after that (letters, a note pasted into
the cell) is returned stripped but otherwise unchanged, so the validator
can point at it instead of the data silently changing.
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s\-/.() ]+")
_DIGITS = re.compile(r"^\+?\d+$")


def normalize(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if not value.is_integer():
            return str(value).strip()
        value = int(value)
    raw = str(value).strip()
    s = _SEPARATORS.sub("", raw)
    if not _DIGITS.match(s):
        return raw
    if s.startswith("+381"):
        s = "0" + s[4:]
    elif s.startswith("00381"):
        s = "0" + s[5:]
    elif s.startswith("381") and len(s) in (11, 12):
        s = "0" + s[3:]
    elif not s.startswith(("0", "+")) and len(s) in (8, 9):
        s = "0" + s
    return s


def is_valid(value: object) -> bool:
    """Empty, or digits (optionally with a leading +) once normalized."""
    s = normalize(value)
    return not s or bool(_DIGITS.match(s))
