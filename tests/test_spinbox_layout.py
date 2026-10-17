"""Regression: button-less spin boxes must keep a usable text field
under the app stylesheet.

PySide6 6.12 collapses a styled spin box's inner QLineEdit to 1 px when
setButtonSymbols(NoButtons) is used -- the value is there but painted
into a sliver over the left border (field report: blank Пре/После in
the CI-built exe). See biracki_odbor/gui/widgets/spinbox.py.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QHBoxLayout, QWidget

from biracki_odbor.gui.style import _QSS
from biracki_odbor.gui.tabs.settings_election import _QuotaSpinBox
from biracki_odbor.gui.widgets.date_picker import make_date_picker
from biracki_odbor.gui.widgets.spinbox import WheelSafeDoubleSpinBox, WheelSafeSpinBox


@pytest.fixture
def styled_app():
    app = QApplication.instance() or QApplication([])
    previous = app.styleSheet()
    app.setStyleSheet(_QSS)
    yield app
    app.setStyleSheet(previous)


def _laid_out(app, sb: QAbstractSpinBox) -> QWidget:
    host = QWidget()
    QHBoxLayout(host).addWidget(sb)
    host.resize(300, 80)
    host.show()
    app.processEvents()
    return host


def _spacing_like() -> WheelSafeSpinBox:
    sb = WheelSafeSpinBox()
    sb.setRange(0, 72)
    sb.setSuffix(" pt")
    sb.setValue(12)
    return sb


@pytest.mark.parametrize("factory", [
    _spacing_like,
    WheelSafeDoubleSpinBox,
    _QuotaSpinBox,
    make_date_picker,
])
def test_text_field_keeps_usable_width(styled_app, factory) -> None:
    sb = factory()
    host = _laid_out(styled_app, sb)
    try:
        assert sb.buttonSymbols() != QAbstractSpinBox.ButtonSymbols.NoButtons
        assert sb.lineEdit().width() >= 40, sb.lineEdit().geometry()
    finally:
        host.close()
