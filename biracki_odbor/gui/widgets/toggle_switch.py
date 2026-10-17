"""Custom toggle switch widget — red=off, blue=on.

Drop-in replacement for QCheckBox. Supported API:
  isChecked(), setChecked(), toggle(), text(), setText(),
  toggled(bool), stateChanged(int), blockSignals().
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QSize, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget


class ToggleSwitch(QWidget):
    """Pill-shaped animated toggle: red when off, blue when on."""

    toggled = Signal(bool)
    stateChanged = Signal(int)   # Qt.CheckState compat: 2=checked, 0=unchecked

    _TW  = 44    # track width
    _TH  = 24    # track height
    _TD  = 18    # thumb diameter
    _TP  = 3     # thumb padding from track edge
    _GAP = 8     # gap between track and label text

    _COL_OFF   = QColor("#DC2626")   # red-600
    _COL_ON    = QColor("#2563EB")   # blue-600
    _COL_THUMB = QColor("#FFFFFF")

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._text = text
        self._anim_x: float = float(self._TP)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.valueChanged.connect(self._on_anim_value)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    # ── Public API ────────────────────────────────────────────────────

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._start_anim()
        if not self.signalsBlocked():
            self.toggled.emit(checked)
            self.stateChanged.emit(2 if checked else 0)

    def toggle(self) -> None:
        self.setChecked(not self._checked)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        # Base QWidget already blocks mouse/key events while disabled —
        # this just makes that state visible, since paintEvent draws the
        # same full-saturation colours regardless of isEnabled() otherwise.
        # Without it, a locked/always-on switch (e.g. a fixed backup-scope
        # declaration) is indistinguishable from a live, clickable one.
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    # ── Animation ─────────────────────────────────────────────────────

    def _thumb_x_on(self) -> float:
        return float(self._TW - self._TD - self._TP)

    def _thumb_x_off(self) -> float:
        return float(self._TP)

    def _start_anim(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._anim_x)
        self._anim.setEndValue(
            self._thumb_x_on() if self._checked else self._thumb_x_off()
        )
        self._anim.start()

    def _on_anim_value(self, value: object) -> None:
        self._anim_x = float(value)  # type: ignore[arg-type]
        self.update()

    # ── Sizing ────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text_w = (fm.horizontalAdvance(self._text) + self._GAP) if self._text else 0
        return QSize(self._TW + text_w, max(self._TH, fm.height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Interpolate track colour from off→on based on thumb position
        span = self._thumb_x_on() - self._thumb_x_off()
        t = max(0.0, min(1.0, (self._anim_x - self._thumb_x_off()) / span if span else 0.0))
        off, on = self._COL_OFF, self._COL_ON
        track_col = QColor(
            int(off.red()   + t * (on.red()   - off.red())),
            int(off.green() + t * (on.green() - off.green())),
            int(off.blue()  + t * (on.blue()  - off.blue())),
        )
        if not self.isEnabled():
            # Desaturate toward grey rather than just lowering alpha —
            # alpha alone still reads as a normal, brighter switch over
            # a light background (most of this app's chrome is white/
            # near-white), which defeats the point of signalling "fixed,
            # not clickable".
            grey = QColor("#9AA1B0")
            track_col = QColor(
                int(track_col.red()   * 0.35 + grey.red()   * 0.65),
                int(track_col.green() * 0.35 + grey.green() * 0.65),
                int(track_col.blue()  * 0.35 + grey.blue()  * 0.65),
            )

        # Track
        track_y = (self.height() - self._TH) // 2
        path = QPainterPath()
        path.addRoundedRect(
            0.0, float(track_y), float(self._TW), float(self._TH),
            self._TH / 2, self._TH / 2,
        )
        p.fillPath(path, track_col)

        # Thumb
        thumb_y = track_y + (self._TH - self._TD) // 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._COL_THUMB)
        p.drawEllipse(int(self._anim_x), thumb_y, self._TD, self._TD)

        # Focus ring
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            focus_pen = self.palette().highlight().color()
            focus_pen.setAlpha(180)
            p.setPen(focus_pen)
            p.drawRoundedRect(
                1, track_y + 1, self._TW - 2, self._TH - 2,
                (self._TH - 2) / 2, (self._TH - 2) / 2,
            )

        # Label text
        if self._text:
            p.setPen(self.palette().windowText().color())
            fm = self.fontMetrics()
            text_x = self._TW + self._GAP
            text_y = (self.height() + fm.ascent() - fm.descent()) // 2
            p.drawText(text_x, text_y, self._text)

        p.end()

    # ── Input ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.toggle()
        else:
            super().keyPressEvent(event)
