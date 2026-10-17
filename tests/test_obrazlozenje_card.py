"""Tests for gui.widgets.obrazlozenje_card — auto-resizing paragraph editor."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from biracki_odbor.config.obrazlozenje import Paragraph, Segment
from biracki_odbor.gui.widgets.obrazlozenje_card import ObrazlozenjeCard

# Some other test modules call apply_global_style() on the shared,
# session-wide QApplication, which sets a global stylesheet with
# `QPlainTextEdit { font-size: 14pt }` plus an app-wide QFont. Once set,
# it leaks into whichever test happens to run after them in the same
# process (test order is not guaranteed) — and a QSS font-size rule
# overrides a plain widget.setFont() call, so pinning a QFont alone
# isn't enough; the stylesheet itself must be cleared too. Both are
# reset in _make_card() so wrap/height math here is deterministic
# regardless of what ran before it.
_TEST_FONT = QFont("Arial", 10)


def _pump() -> None:
    """Let Qt actually process the pending layout/resize before measuring
    .height() — setFixedHeight()/setFixedWidth() on a layout-managed
    widget don't take effect synchronously without an event-loop turn."""
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()


def _make_card(text: str) -> ObrazlozenjeCard:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet("")  # drop any global QSS leaked in by other tests
    paragraph = Paragraph(id="p1", segments=[Segment(text=text)], optional=False)
    card = ObrazlozenjeCard(
        paragraph,
        on_changed=lambda: None,
        on_remove=lambda _c: None,
        on_move_up=lambda _c: None,
        on_move_down=lambda _c: None,
    )
    card.resize(520, 200)
    card.editor.setFont(_TEST_FONT)
    card.show()
    card.editor.setFixedWidth(500)  # stable width so wrapping is deterministic
    _pump()
    card.editor.fit_to_content()
    _pump()
    return card


def test_short_paragraph_sits_at_minimum_height() -> None:
    card = _make_card("Кратак пасус.")
    try:
        assert card.editor.height() == ObrazlozenjeCard._MIN_EDITOR_HEIGHT
    finally:
        card.deleteLater()


def test_long_paragraph_grows_taller_than_minimum() -> None:
    long_text = "\n".join(f"Ред број {i} у дугачком пасусу." for i in range(30))
    card = _make_card(long_text)
    try:
        assert card.editor.height() > ObrazlozenjeCard._MIN_EDITOR_HEIGHT
    finally:
        card.deleteLater()


def test_extremely_long_paragraph_is_capped_at_maximum() -> None:
    huge_text = "\n".join(f"Ред број {i}." for i in range(500))
    card = _make_card(huge_text)
    try:
        assert card.editor.height() == ObrazlozenjeCard._MAX_EDITOR_HEIGHT
    finally:
        card.deleteLater()


def test_height_grows_as_user_types_more_text() -> None:
    card = _make_card("Почетак.")
    try:
        short_height = card.editor.height()
        card.editor.setPlainText("\n".join(f"Линија {i}" for i in range(25)))
        card.editor.fit_to_content()
        _pump()
        assert card.editor.height() > short_height
    finally:
        card.deleteLater()


def test_height_shrinks_back_when_text_is_removed() -> None:
    card = _make_card("\n".join(f"Линија {i}" for i in range(25)))
    try:
        tall_height = card.editor.height()
        card.editor.setPlainText("Кратко.")
        card.editor.fit_to_content()
        _pump()
        assert card.editor.height() < tall_height
        assert card.editor.height() == ObrazlozenjeCard._MIN_EDITOR_HEIGHT
    finally:
        card.deleteLater()


def test_narrowing_width_rewraps_and_grows_height_via_resize_event() -> None:
    """A single long line wraps into more visual lines when the editor is
    narrowed (e.g. window resize) — resizeEvent must recompute, not just
    textChanged. Uses a single very long line (no explicit \\n) so the
    only way line count increases is width-driven rewrapping.
    """
    long_line = "реч " * 200
    card = _make_card(long_line)
    try:
        card.editor.setFixedWidth(900)
        _pump()
        card.editor.fit_to_content()
        _pump()
        wide_height = card.editor.height()

        card.editor.setFixedWidth(200)
        _pump()  # resizeEvent fires -> QTimer.singleShot(0, fit_to_content)
        assert card.editor.height() > wide_height
    finally:
        card.deleteLater()
