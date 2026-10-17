"""Tests for _QuotaSpinBox — numeric-only quota entry, no arrows/wheel."""

from __future__ import annotations

import pytest

from biracki_odbor.gui.tabs.settings_election import _QuotaSpinBox


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_no_up_down_buttons(app) -> None:
    from biracki_odbor.gui.widgets.spinbox import NO_BUTTONS_PROPERTY
    sb = _QuotaSpinBox()
    try:
        # Hidden via style.py's [noButtons="true"] rule, NOT
        # setButtonSymbols(NoButtons) -- see widgets/spinbox.py.
        assert sb.property(NO_BUTTONS_PROPERTY) is True
    finally:
        sb.deleteLater()


def test_wheel_event_ignored_does_not_change_value(app) -> None:
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import Qt

    sb = _QuotaSpinBox()
    try:
        sb.setValue(5)
        event = QWheelEvent(
            QPointF(0, 0), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        sb.wheelEvent(event)
        assert sb.value() == 5
        assert not event.isAccepted()
    finally:
        sb.deleteLater()
