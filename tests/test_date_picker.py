"""Tests for the make_date_picker helper.

Verifies the popup calendar's Today button:
  1. exists with the agreed objectName so the QSS targets it,
  2. sets the calendar selection to today's date,
  3. emits `activated` so QDateEdit closes the popup + commits the date.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCalendarWidget, QDateEdit, QPushButton

from biracki_odbor.gui.widgets.date_picker import make_date_picker


def _today_button(cal: QCalendarWidget) -> QPushButton | None:
    return cal.findChild(QPushButton, "CalendarTodayButton")


@pytest.fixture
def picker():
    dt = make_date_picker(QDate(2026, 1, 1))
    yield dt
    dt.deleteLater()


def test_make_date_picker_uses_initial_date() -> None:
    dt = make_date_picker(QDate(2026, 1, 1))
    try:
        assert dt.date() == QDate(2026, 1, 1)
        assert dt.calendarPopup() is True
        assert dt.displayFormat() == "dd.MM.yyyy."
    finally:
        dt.deleteLater()


def test_make_date_picker_defaults_to_today() -> None:
    dt = make_date_picker()
    try:
        assert dt.date() == QDate.currentDate()
    finally:
        dt.deleteLater()


def test_calendar_has_today_button(picker: QDateEdit) -> None:
    """A 'Данас' QPushButton must exist as a child of the calendar
    popup, with the agreed objectName so QSS can target it."""
    cal = picker.calendarWidget()
    assert cal is not None
    btn = _today_button(cal)
    assert btn is not None, "make_date_picker must inject a Today button"
    assert btn.text() == "Данас"


def test_today_button_sets_selection_to_today(picker: QDateEdit) -> None:
    """Clicking 'Данас' must select today's date inside the calendar."""
    cal = picker.calendarWidget()
    assert cal is not None
    # Start far from today so the assertion is meaningful.
    cal.setSelectedDate(QDate(2026, 1, 1))
    assert cal.selectedDate() == QDate(2026, 1, 1)

    btn = _today_button(cal)
    assert btn is not None
    btn.click()
    assert cal.selectedDate() == QDate.currentDate()


def test_today_button_emits_activated_to_close_popup(picker: QDateEdit) -> None:
    """The 'activated' signal is what QDateEdit listens for to close
    its popup and commit the selected date — emitting it manually
    makes the Today button feel like a double-click on the day cell.
    Without this the popup would stay open after the user clicked
    Today, which is the opposite of what they meant."""
    cal = picker.calendarWidget()
    assert cal is not None
    received: list[QDate] = []
    cal.activated.connect(received.append)

    btn = _today_button(cal)
    assert btn is not None
    btn.click()

    assert received == [QDate.currentDate()], (
        "Today button must emit `activated(today)` so QDateEdit's popup"
        " commits + closes — mirrors the user's natural day-cell gesture."
    )


def test_decorate_calendar_is_idempotent(picker: QDateEdit) -> None:
    """Re-running make_date_picker (or another decoration pass) on the
    same calendar must NOT stack multiple Today buttons. Guards against
    a future caller that calls cal.setMinimumSize() and re-runs the
    decorate helper."""
    cal = picker.calendarWidget()
    assert cal is not None
    from biracki_odbor.gui.widgets.date_picker import _decorate_calendar
    _decorate_calendar(cal)
    _decorate_calendar(cal)
    buttons = cal.findChildren(QPushButton, "CalendarTodayButton")
    assert len(buttons) == 1, (
        f"expected exactly 1 Today button after repeated decoration; got {len(buttons)}"
    )


def test_week_numbers_gutter_is_hidden(picker: QDateEdit) -> None:
    """Week-number column is noise for our 60+ user demographic. The
    helper hides it to save horizontal space in the popup."""
    from PySide6.QtWidgets import QCalendarWidget as _Cal
    cal = picker.calendarWidget()
    assert cal is not None
    assert cal.verticalHeaderFormat() == _Cal.NoVerticalHeader


def test_wheel_scroll_does_not_change_the_date(picker: QDateEdit) -> None:
    """Field report: a legal-document date field that silently changes
    value on an incidental mouse-wheel scroll (e.g. the operator's mouse
    passes over it while reading the form) is unacceptable — there must
    be no way to alter a date without an explicit type or calendar-click
    action. QAbstractSpinBox's default wheelEvent bumps the focused
    segment on every tick; make_date_picker must suppress that."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    before = picker.date()
    event = QWheelEvent(
        QPointF(0, 0), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    picker.wheelEvent(event)
    assert picker.date() == before, "wheel scroll must never change the date"
    assert not event.isAccepted(), "event must be ignored, not swallowed, so page scroll still works"
