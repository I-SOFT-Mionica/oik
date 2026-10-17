"""Reusable input-validator factories for editable fields.

Two flavors live here:

  * **Qt QValidator subclasses** (`IntValidator`, `SeparatorValidator`,
    `JmbgValidator`) for `QLineEdit`. Qt enforces these at keystroke
    time — invalid input never lands in the field.
  * **Pure check functions** (`is_valid_jmbg`, `is_valid_separator`,
    `validate_email`) for when the caller needs to decide later (form
    submission, popup OK-button gating, server-side rejection).

Why both: Qt's `QValidator` runs character-by-character with an
`Intermediate / Acceptable / Invalid` state machine; some checks
(JMBG MOD-11, email shape) only make sense once the user is done
typing. We expose the same rule in both shapes so a JMBG field can
**both** prevent non-digits at keystroke time **and** be checked for
MOD-11 correctness on submit.

The factories return Qt validators by default because that's the
99% use case (`QLineEdit.setValidator(...)`); the pure functions are
imported separately when needed.
"""

from __future__ import annotations

import re
from typing import Callable

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QIntValidator, QRegularExpressionValidator, QValidator,
)


# ── Integer fields (session number, sub-broj start, etc.) ─────────


def int_validator(*, min_value: int = 0, max_value: int = 999999) -> QValidator:
    """Digit-only validator with a numeric range cap.

    Used for `Број седнице` (1..99 in practice) and `Почетни подброј`
    (0..999999). The range cap keeps the operator from typing wildly
    out-of-spec values; Qt rejects keystrokes that would exceed it.
    """
    return QIntValidator(min_value, max_value)


# ── Separator field on Phase 3 (one char from a small whitelist) ──


_SEPARATOR_CHARS = "-/_."


def separator_validator() -> QValidator:
    """Accept exactly one character from the allow-list.

    The municipal-archive convention varies across OIK offices:
    most use `-`, Belgrade uses `/`, occasionally `.` or `_`. We
    don't accept letters, digits, or whitespace — those would
    produce malformed broj-resenja like `013-5-30a200/2026`.
    """
    pattern = QRegularExpression(f"^[{re.escape(_SEPARATOR_CHARS)}]$")
    return QRegularExpressionValidator(pattern)


def is_valid_separator(text: str) -> bool:
    """Pure check — for submit-time gating in popup dialogs."""
    return len(text) == 1 and text in _SEPARATOR_CHARS


# ── JMBG validators ───────────────────────────────────────────────


def jmbg_validator() -> QValidator:
    """13-digit field that accepts only the digits while typing.

    Doesn't run MOD-11 here — that requires the full 13 digits and is
    expensive to recompute on every keystroke. Use `is_valid_jmbg`
    on form submission for the correctness check.
    """
    return QRegularExpressionValidator(QRegularExpression(r"^[0-9]{0,13}$"))


def is_valid_jmbg(text: str) -> bool:
    """Submit-time MOD-11 + format check — delegates to `core.jmbg.is_valid`.

    Keeping the validator-module thin wrapper so callers don't have to
    learn two import paths; `core.jmbg` is the single source of truth
    for the actual rule (matches what Phase 2 enforces at import time).
    """
    from biracki_odbor.core.jmbg import is_valid
    return is_valid(text)


# ── E-mail (popup submit-time check) ──────────────────────────────


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(text: str) -> bool:
    """Loose RFC-5321 shape check, not full RFC validation.

    Catches the typical operator typos (missing @, missing TLD,
    embedded spaces) without false-rejecting legitimate addresses
    like `info+ku@gov.rs` or `mail@xn--something.com`. Empty string
    is treated as valid — addresses are optional fields.
    """
    if not text:
        return True
    return bool(_EMAIL_RE.match(text.strip()))


# ── Phone (popup submit-time check) ───────────────────────────────


def is_valid_phone(text: str) -> bool:
    """Valid once cleaned up by `core.phone.normalize`: spaces, dashes,
    slashes and +381 are fine; letters or a pasted note are not.
    Empty string is treated as valid — phone is an optional field.
    """
    from biracki_odbor.core import phone
    return phone.is_valid(text)


# ── Composite validator for free-form callable use ────────────────


CheckFn = Callable[[str], bool]


def is_valid_int_in_range(min_value: int, max_value: int) -> CheckFn:
    """Submit-time variant of `int_validator` — pure function form."""
    def check(text: str) -> bool:
        text = (text or "").strip()
        if not text:
            # Empty is treated as valid by callers; required-field
            # rules live elsewhere (the form decides what's required).
            return True
        try:
            value = int(text)
        except ValueError:
            return False
        return min_value <= value <= max_value
    return check
