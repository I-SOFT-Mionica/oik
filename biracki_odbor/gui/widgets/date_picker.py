"""V1-styled date picker + popup calendar with a Today button.

Two call sites today (Изборна конфигурација datum + Phase 3 session
date) both want the same setup: QDateEdit with a calendar popup, sane
display format, generous popup size, and a "Данас" footer button.

The Today button is appended to the QCalendarWidget's own QVBoxLayout
so it sits below the day grid inside the popup window. Clicking it
sets the selected date to today AND emits `activated`, which is the
signal QDateEdit listens for to close the popup and commit the
value — mirroring the user's natural double-click on a day cell.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QCalendarWidget, QDateEdit, QPushButton, QWidget

from biracki_odbor.gui.widgets.spinbox import inset_spinbox_text


_DEFAULT_DISPLAY_FORMAT = "dd.MM.yyyy."
_DEFAULT_MIN_WIDTH = 180
_POPUP_MIN_SIZE = QSize(360, 320)


class _WheelSafeDateEdit(QDateEdit):
    """QDateEdit that ignores mouse-wheel scrolling.

    QAbstractSpinBox silently bumps whichever date segment has focus on
    every wheel tick by default — the exact failure mode a legal
    document's date field can't have: the operator scrolls past the
    field while reading the form and the date silently changes with no
    confirmation step. Typing and the calendar popup are unaffected;
    ignoring (not accepting) the event also lets it bubble up so the
    containing scroll area still scrolls normally.
    """

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


def make_date_picker(
    initial: QDate | None = None,
    *,
    display_format: str = _DEFAULT_DISPLAY_FORMAT,
    min_width: int = _DEFAULT_MIN_WIDTH,
    parent: QWidget | None = None,
) -> QDateEdit:
    """Return a QDateEdit with V1 styling + a Today-button popup calendar.

    Defaults to today when `initial` is None. The caller still wires
    `dateChanged` / `dateTime` etc. as usual — this helper only handles
    construction + popup decoration.
    """
    dt = _WheelSafeDateEdit(initial if initial is not None else QDate.currentDate(),
                             parent)
    dt.setCalendarPopup(True)
    dt.setDisplayFormat(display_format)
    dt.setMinimumWidth(min_width)
    inset_spinbox_text(dt)
    cal = dt.calendarWidget()
    if cal is not None:
        _decorate_calendar(cal)
    return dt


def _decorate_calendar(cal: QCalendarWidget) -> None:
    """Size the popup, drop the row-numbers gutter, append a Today button.

    Safe to call multiple times on the same calendar (idempotent — the
    button is only added if one with the same objectName isn't already
    a child).
    """
    cal.setMinimumSize(_POPUP_MIN_SIZE)
    cal.setGridVisible(True)
    # Week numbers gutter is noise for the 60+ target user — never used,
    # eats horizontal space.
    cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)

    if cal.findChild(QPushButton, "CalendarTodayButton") is not None:
        return  # already decorated

    layout = cal.layout()
    if layout is None:
        return  # shouldn't happen in practice; bail safely

    btn = QPushButton("Данас", cal)
    btn.setObjectName("CalendarTodayButton")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip("Изабери данашњи датум")
    btn.clicked.connect(lambda: _go_to_today(cal))
    layout.addWidget(btn)


def _go_to_today(cal: QCalendarWidget) -> None:
    today = QDate.currentDate()
    cal.setSelectedDate(today)
    # `activated` is what QDateEdit listens for to close its popup and
    # accept the date as the new value. Emitting it manually makes the
    # Today button behave like a double-click on the day cell.
    cal.activated.emit(today)
