"""Smoke tests for the Outlook integration module.

On CI (Ubuntu) and on most dev workstations without pywin32 installed,
`OUTLOOK_AVAILABLE` is False and the module should import cleanly +
the GUI button stays hidden. These tests pin that contract.

The win32com-side behavior (actually walking the Inbox, reading
ReceivedTime, saving attachments) is impossible to cover headlessly
and is exercised by manual smoke on a real Windows + Outlook box —
see the verification section in the V0.9.x audit-features plan.
"""

from __future__ import annotations

import sys

import pytest

from biracki_odbor.integrations import outlook as outlook_mod


def test_module_imports_cleanly() -> None:
    """The integration module must import on every supported platform —
    pywin32 is Windows-only, but the rest of the codebase needs to
    pull this module in without crashing on Linux CI."""
    assert hasattr(outlook_mod, "OUTLOOK_AVAILABLE")
    assert isinstance(outlook_mod.OUTLOOK_AVAILABLE, bool)
    # Re-export of OutlookUnavailable so callers can `except` it
    # without conditionally importing.
    assert issubclass(outlook_mod.OutlookUnavailable, RuntimeError)


def test_fetch_raises_when_unavailable() -> None:
    """When OUTLOOK_AVAILABLE is False (any non-Windows or
    no-pywin32 setup), calling fetch_inbox_messages must raise
    OutlookUnavailable — not crash with AttributeError on a missing
    win32com import."""
    if outlook_mod.OUTLOOK_AVAILABLE:
        pytest.skip("Outlook is available on this machine; nothing to assert.")
    with pytest.raises(outlook_mod.OutlookUnavailable):
        outlook_mod.fetch_inbox_messages()


class _FakePywinDatetime:
    """Mimics a pywintypes.datetime whose `.tzinfo` (or any tz-aware
    method) blows up with `ModuleNotFoundError: No module named
    'win32timezone'`. This is the real failure we hit in the field
    when pywin32 is installed via pip without the post-install step.

    Field access (year/month/day/hour/minute/second) works normally —
    that's how the production code now extracts the values."""

    def __init__(self, y, m, d, h, mi, s) -> None:
        self.year, self.month, self.day = y, m, d
        self.hour, self.minute, self.second = h, mi, s
        self.microsecond = 0

    @property
    def tzinfo(self):
        raise ModuleNotFoundError("No module named 'win32timezone'")

    def astimezone(self, *_a, **_kw):
        raise ModuleNotFoundError("No module named 'win32timezone'")

    def replace(self, *_a, **_kw):
        raise ModuleNotFoundError("No module named 'win32timezone'")


def test_to_utc_datetime_survives_missing_win32timezone() -> None:
    """Regression: _to_utc_datetime must not touch pywintypes.datetime's
    tz-aware path, because that path lazy-imports `win32timezone` and
    fails on installs missing the post-install step. We saw this in
    production logs as 'outlook: skipped message #0 (No module named
    "win32timezone")', causing the picker to show zero inbox messages."""
    fake = _FakePywinDatetime(2026, 6, 2, 18, 5, 41)
    result = outlook_mod._to_utc_datetime(fake)
    assert result.tzinfo is not None
    # Y/M/D round-trip via local→UTC; just confirm date components
    # came from our fake and not from datetime.now() fallback.
    assert result.year == 2026
    assert result.month == 6
    assert result.day in (1, 2, 3)  # depends on operator's local tz


def test_phase2_button_hidden_when_outlook_unavailable(tmp_path, monkeypatch) -> None:
    """The 'Увези из Outlook-а…' button on Phase 2 must be invisible
    when Outlook isn't available — otherwise non-Windows operators
    would see a button that always errors. Mirrors the
    OUTLOOK_AVAILABLE guard in `phase2.py:__init__`."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    from biracki_odbor import _release_info
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab
    from biracki_odbor.gui.style import apply_global_style

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    app = QApplication.instance() or QApplication([])
    apply_global_style(app)

    state = AppState()
    tab = Phase2Tab(state)
    try:
        if outlook_mod.OUTLOOK_AVAILABLE:
            # On a real Windows box, button must be visible.
            assert tab.btn_import_outlook.isVisible() or tab.btn_import_outlook.isHidden() is False
        else:
            # Visibility before show() returns False unconditionally;
            # the contract we care about is isHidden() vs setVisible.
            # When OUTLOOK_AVAILABLE is False, setVisible(False) was
            # called explicitly during __init__.
            assert tab.btn_import_outlook.isHidden()
    finally:
        tab.deleteLater()
