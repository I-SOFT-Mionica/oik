"""Regression tests: the License card must not show a real license's
"● Активна" pill for an internal TEST license -- the server has no
formal test/production flag, issued_to is the only signal available.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_page_with_license(**license_kwargs):
    from biracki_odbor.gui import about_page as about_page_mod
    from biracki_odbor.licensing.state import License, Mode

    class _FakeState:
        license = License(mode=Mode.LICENSED, **license_kwargs)

    page = about_page_mod.AboutPage.__new__(about_page_mod.AboutPage)
    page._state = _FakeState()
    return page


def _pill_text(card) -> str:
    from PySide6.QtWidgets import QLabel
    # The status pill is the QLabel passed to _card()'s header slot --
    # find it among the card's children by its distinctive pill styling.
    for lbl in card.findChildren(QLabel):
        if "border-radius:999px" in lbl.styleSheet():
            return lbl.text()
    raise AssertionError("status pill not found in license card")


def test_real_license_shows_active_pill(app) -> None:
    page = _make_page_with_license(issued_to="Општина Уб", updates_until="2027-07-01")
    card = page._build_license_card()  # noqa: SLF001
    assert _pill_text(card) == "● Активна"


def test_test_license_shows_test_pill_not_active(app) -> None:
    page = _make_page_with_license(issued_to="TEST", updates_until="2027-07-01")
    card = page._build_license_card()  # noqa: SLF001
    text = _pill_text(card)
    assert text != "● Активна"
    assert "Тест" in text


def test_test_license_match_is_case_insensitive(app) -> None:
    page = _make_page_with_license(issued_to="test", updates_until="2027-07-01")
    card = page._build_license_card()  # noqa: SLF001
    assert _pill_text(card) != "● Активна"


def test_real_customer_named_with_test_substring_still_shows_active(app) -> None:
    """Exact match only -- a real org whose name merely contains "test"
    must not be misflagged."""
    page = _make_page_with_license(issued_to="Testomir DOO", updates_until="2027-07-01")
    card = page._build_license_card()  # noqa: SLF001
    assert _pill_text(card) == "● Активна"
