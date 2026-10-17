"""Tests for the per-election subject-rider system.

Phase 1's send-to-parties stamps every outgoing message subject + body
with a `[ОИК-YYYYMMDD]` token derived from the election date. Phase 2's
Outlook inbox fetch uses the same token in its MAPI `Restrict` clause
so a busy inbox (every department's .xlsx mail in the last 14 days)
gets pared down to only replies to our own outgoing campaign.

Tests cover:
  - token generation from various date strings (valid, invalid, empty),
  - the `_build_restrict` helper that assembles the MAPI expression,
  - SendToPartiesDialog body/subject template rendering with the token.
"""

from __future__ import annotations

from datetime import datetime

from biracki_odbor.config.election import ElectionDates
from biracki_odbor.integrations.outlook import _build_restrict


# ── Token generation ──────────────────────────────────────────────


def test_subject_token_format() -> None:
    """Valid date → `[ОИК-YYYYMMDD]` with zero-padded month/day."""
    d = ElectionDates(date_full="3. фебруар 2027. године")
    assert d.subject_token == "[ОИК-20270203]"


def test_subject_token_full_two_digit_components() -> None:
    """A double-digit month and day must NOT get re-padded — confirms
    the format string handles both single and double-digit cases."""
    d = ElectionDates(date_full="17. децембар 2026. године")
    assert d.subject_token == "[ОИК-20261217]"


def test_subject_token_empty_when_date_unset() -> None:
    """No date → empty token. Callers must treat this as "no rider,
    fall back to date-only inbox filter" rather than building a
    token that matches nothing in the inbox."""
    assert ElectionDates().subject_token == ""


def test_subject_token_empty_when_date_unparseable() -> None:
    """A garbage date string falls back to empty rather than crashing
    or producing nonsense like `[ОИК-00000000]`. The send dialog
    silently omits the token; the inbox filter falls back to date-
    only behavior."""
    d = ElectionDates(date_full="not a real date")
    assert d.subject_token == ""


# ── _build_restrict ───────────────────────────────────────────────


def test_build_restrict_date_only_when_subject_empty() -> None:
    """When `subject_contains` is empty, the expression must be the
    original date-only filter — backwards compat for callers (and
    production behavior pre-rider)."""
    cutoff = datetime(2026, 6, 1, 0, 0)
    r = _build_restrict(cutoff, "")
    assert "[ReceivedTime] >=" in r
    assert "[Subject]" not in r
    assert "AND" not in r


def test_build_restrict_appends_subject_clause() -> None:
    """A non-empty token must AND-join a Subject phrase-match
    clause so the server-side filter drops mail without the rider."""
    cutoff = datetime(2026, 6, 1, 0, 0)
    r = _build_restrict(cutoff, "[ОИК-20260615]")
    assert "[ReceivedTime] >=" in r
    assert "AND" in r
    assert "[Subject] ci_phrasematch '[ОИК-20260615]'" in r


def test_build_restrict_escapes_single_quotes_in_subject() -> None:
    """A token containing a single quote (hypothetical — current
    format doesn't have any, but the function is the choke point)
    must double the quote so MAPI's parser doesn't choke."""
    cutoff = datetime(2026, 6, 1, 0, 0)
    r = _build_restrict(cutoff, "[ОИК-O'rly]")
    # MAPI's single-quote escape is doubling the character.
    assert "[Subject] ci_phrasematch '[ОИК-O''rly]'" in r


# ── Template rendering ────────────────────────────────────────────


def test_send_dialog_renders_token_in_subject_and_body() -> None:
    """The end-to-end smoke: open SendToPartiesDialog with a token,
    `prepared_drafts()` should produce subject + body containing the
    token verbatim. This is the contract Phase 2 relies on for the
    Subject filter to find replies."""
    # Avoid actually launching Qt — we just need the dialog logic.
    # PySide6 widgets need a QApplication; tests/conftest sets one up.
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])

    from pathlib import Path
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import (
        SendToPartiesDialog,
    )

    files = [Path("СНС.xlsx")]
    dlg = SendToPartiesDialog(
        files=files,
        party_full_names={"СНС": "Српска напредна странка"},
        party_emails={"СНС": "sns@example.rs"},
        subject_token="[ОИК-20270615]",
    )
    drafts = dlg.prepared_drafts()
    assert len(drafts) == 1
    draft = drafts[0]
    assert "[ОИК-20270615]" in draft.subject
    assert "[ОИК-20270615]" in draft.body
    # The body footer's instructional sentence must survive template
    # substitution — regression guard if someone edits the template
    # and breaks the helper text the recipient needs.
    assert "одговорите директно" in draft.body


def test_send_dialog_empty_token_renders_no_rider() -> None:
    """When no token is supplied (election date unset/unparseable),
    the {token} placeholder renders to "" and the subject/body still
    work — no `[ОИК-` substring anywhere."""
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])
    from pathlib import Path
    from biracki_odbor.gui.dialogs.send_to_parties_dialog import (
        SendToPartiesDialog,
    )

    dlg = SendToPartiesDialog(
        files=[Path("СНС.xlsx")],
        party_full_names={"СНС": "Српска напредна странка"},
        party_emails={"СНС": "sns@example.rs"},
        subject_token="",
    )
    drafts = dlg.prepared_drafts()
    assert len(drafts) == 1
    assert "[ОИК-" not in drafts[0].subject
    assert "[ОИК-" not in drafts[0].body
