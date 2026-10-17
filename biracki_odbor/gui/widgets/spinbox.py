"""Wheel-safe spin boxes — shared by settings_oik.py, phase3.py, izmene.py.

A stray mouse-wheel scroll while reading the page shouldn't silently
change a value that feeds a generated решење. Same fix as
date_picker.py's _WheelSafeDateEdit and settings_election.py's
_QuotaSpinBox, extracted here once three call sites needed it.

PySide6 6.12 layout regression (the "blank Пре/После" field report):
with an app stylesheet applied, 6.12's QStyleSheetStyle ignores the
spin box's horizontal QSS padding when placing the inner QLineEdit, and
with setButtonSymbols(NoButtons) it collapses that QLineEdit to 1 px
wide at x=0 -- the digits get clipped into a sliver over the box's left
border. It only showed in CI-built exes because CI installs the newest
PySide6 while local dev was still on 6.11. So: never use NoButtons;
mark the widget with the `noButtons` property instead (style.py hides
the up/down buttons for it), and inset the text via setTextMargins
rather than QSS padding, which both versions honour identically.
"""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QSpinBox

NO_BUTTONS_PROPERTY = "noButtons"
TEXT_INSET_PX = 11


def inset_spinbox_text(sb: QAbstractSpinBox, px: int = TEXT_INSET_PX) -> None:
    """Horizontal text inset for any spin box / date edit (style.py
    zeroes the horizontal QSS padding -- see module docstring)."""
    sb.lineEdit().setTextMargins(px, 0, px, 0)


def hide_spinbox_buttons(sb: QAbstractSpinBox) -> None:
    """Replacement for setButtonSymbols(NoButtons) -- see module docstring."""
    sb.setProperty(NO_BUTTONS_PROPERTY, True)


class _WheelSafeMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        hide_spinbox_buttons(self)
        inset_spinbox_text(self)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class WheelSafeSpinBox(_WheelSafeMixin, QSpinBox):
    """Integer spin box — use this one whenever the field is
    conceptually whole numbers."""


class WheelSafeDoubleSpinBox(_WheelSafeMixin, QDoubleSpinBox):
    """For fields that genuinely need fractional precision (e.g.
    header/footer distance in cm, 0.1 steps). Formats with plain Python
    instead of Qt's QLocale-based default so the decimal separator
    doesn't depend on the OS locale."""

    def textFromValue(self, value: float) -> str:  # noqa: N802
        return f"{value:.{self.decimals()}f}"

    def valueFromText(self, text: str) -> float:  # noqa: N802
        s = text.strip()
        prefix, suffix = self.prefix(), self.suffix()
        if prefix and s.startswith(prefix):
            s = s[len(prefix):]
        if suffix and s.endswith(suffix):
            s = s[:len(s) - len(suffix)]
        try:
            return float(s.strip())
        except ValueError:
            return self.value()
