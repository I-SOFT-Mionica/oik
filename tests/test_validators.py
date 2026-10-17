"""Tests for the reusable input-validator factories.

Two layers covered:
  - Pure check functions (`is_valid_jmbg`, `is_valid_separator`,
    `is_valid_email`, `is_valid_int_in_range`) verify acceptance
    rules without any Qt involvement.
  - Qt `QValidator` factories (`int_validator`, `separator_validator`,
    `jmbg_validator`) verify keystroke-time acceptance behavior via
    `validate(text, pos)`.

Also covers the `SingleLineEdit(check=…)` hook: an invalid value
makes `is_valid()` return False and stamps the dynamic `invalid`
property so QSS can paint the red border.
"""

from __future__ import annotations

import pytest

from PySide6.QtGui import QValidator

from biracki_odbor.gui.widgets.validators import (
    int_validator, is_valid_email, is_valid_int_in_range,
    is_valid_jmbg, is_valid_phone, is_valid_separator, jmbg_validator,
    separator_validator,
)


# ── Pure check functions ──────────────────────────────────────────


def test_is_valid_jmbg_accepts_real_mod11_jmbg() -> None:
    """Real JMBGs (taken from the existing test fixtures) must pass."""
    assert is_valid_jmbg("1605991774818")
    assert is_valid_jmbg("2706994779807")
    assert is_valid_jmbg("0610987774803")


def test_is_valid_jmbg_rejects_bad_checksum() -> None:
    """Same first 12 digits but wrong checksum must fail."""
    # 1605991774818 ends in 2; swap to 3 to break MOD-11.
    assert not is_valid_jmbg("1605991770023")


def test_is_valid_jmbg_rejects_wrong_length() -> None:
    """JMBG must be exactly 13 digits — too short or too long fails."""
    assert not is_valid_jmbg("123")
    assert not is_valid_jmbg("12345678901234")  # 14 digits


def test_is_valid_jmbg_rejects_non_digits() -> None:
    """Letters / whitespace / punctuation never pass MOD-11."""
    assert not is_valid_jmbg("abcdefghijklm")
    assert not is_valid_jmbg("1605 991770022")  # space
    assert not is_valid_jmbg("1605-991770022")  # hyphen


def test_is_valid_separator_accepts_known_chars() -> None:
    """The four municipal-archive conventions are the whole allow-list."""
    for ch in ("-", "/", "_", "."):
        assert is_valid_separator(ch), f"expected {ch!r} to be valid"


def test_is_valid_separator_rejects_letters_digits_multichar() -> None:
    assert not is_valid_separator("a")
    assert not is_valid_separator("1")
    assert not is_valid_separator("//")  # multi-char never matches
    assert not is_valid_separator("")     # empty fails too (caller decides if optional)


def test_is_valid_email_loose_shape() -> None:
    """Catches typical typos without false-rejecting real addresses."""
    assert is_valid_email("info@gov.rs")
    assert is_valid_email("user.name+tag@sub.domain.org")
    assert is_valid_email("")  # empty = treated as valid (optional)


def test_is_valid_email_rejects_obvious_errors() -> None:
    assert not is_valid_email("no-at-sign.com")
    assert not is_valid_email("missing-tld@host")
    assert not is_valid_email("with space@host.rs")


def test_is_valid_phone_accepts_digits_and_leading_plus() -> None:
    assert is_valid_phone("0641234567")
    assert is_valid_phone("+381641234567")
    assert is_valid_phone("")  # empty = treated as valid (optional)


def test_is_valid_phone_rejects_letters_and_symbols() -> None:
    assert not is_valid_phone("064-abc-1234")
    assert is_valid_phone("064/1234567")  # separators are cleaned up (core.phone)
    assert is_valid_phone("064 123 4567")
    assert not is_valid_phone("06412345+67")  # '+' only valid as a leading char


def test_is_valid_int_in_range_factory() -> None:
    """The factory returns a check that respects the configured range."""
    check = is_valid_int_in_range(1, 999)
    assert check("1")
    assert check("999")
    assert check("")  # empty treated as valid; required-ness is the form's job
    assert not check("0")
    assert not check("1000")
    assert not check("not-a-number")


# ── Qt QValidator factories (keystroke-time) ──────────────────────


def test_int_validator_accepts_digits() -> None:
    v = int_validator(min_value=1, max_value=999)
    state, _text, _pos = v.validate("5", 1)
    assert state == QValidator.Acceptable


def test_int_validator_rejects_letters() -> None:
    v = int_validator(min_value=1, max_value=999)
    state, _, _ = v.validate("5a", 2)
    assert state == QValidator.Invalid


def test_separator_validator_accepts_allowed_chars() -> None:
    v = separator_validator()
    for ch in ("-", "/", "_", "."):
        state, _, _ = v.validate(ch, 1)
        assert state == QValidator.Acceptable, f"expected {ch!r} acceptable"


def test_separator_validator_rejects_letters_and_multichar() -> None:
    v = separator_validator()
    # Qt regex validator returns Invalid when the pattern doesn't match
    # at all, Intermediate when a longer input could still match — for
    # this anchored single-char pattern, both letters and multichar are
    # Invalid.
    bad_state, _, _ = v.validate("a", 1)
    assert bad_state == QValidator.Invalid
    multi_state, _, _ = v.validate("--", 2)
    assert multi_state == QValidator.Invalid


def test_jmbg_validator_accepts_digit_prefix() -> None:
    """The keystroke validator accepts partial digit strings — the
    full MOD-11 check happens at submit time via is_valid_jmbg."""
    v = jmbg_validator()
    state, _, _ = v.validate("16", 2)
    assert state == QValidator.Acceptable
    state, _, _ = v.validate("1605991774818", 13)
    assert state == QValidator.Acceptable


def test_jmbg_validator_rejects_letters() -> None:
    v = jmbg_validator()
    state, _, _ = v.validate("16a", 3)
    assert state == QValidator.Invalid


def test_jmbg_validator_rejects_too_long() -> None:
    """Anything past 13 digits is invalid — the spec is fixed-width."""
    v = jmbg_validator()
    state, _, _ = v.validate("1234567890123" + "4", 14)
    assert state == QValidator.Invalid


# ── SingleLineEdit(check=…) hook ──────────────────────────────────


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_single_line_edit_is_valid_no_check(app) -> None:
    """Without a check argument, is_valid() must always return True —
    we don't penalize legacy callers that don't opt in."""
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit
    ed = SingleLineEdit("anything goes")
    assert ed.is_valid()


def test_single_line_edit_with_check_reflects_validity(app) -> None:
    """Passing `check=…` turns is_valid() into a live read of the
    validator. The invalid dynamic property flips accordingly so the
    QSS rule can paint the border red."""
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit
    ed = SingleLineEdit("16059", check=is_valid_jmbg)
    # Partial JMBG fails MOD-11 — property should be set.
    assert not ed.is_valid()
    assert ed.property("invalid") is True
    # Now type a valid JMBG.
    ed.setText("1605991774818")
    assert ed.is_valid()
    assert ed.property("invalid") is False


def test_single_line_edit_reserves_room_for_scrollbar_without_overlap(app) -> None:
    """Regression: the horizontal scrollbar (shown once text overflows
    the visible width) used to render overlapping the last line of
    text — the fixed height budget only counted font height + scrollbar
    height + 16px, but QTextDocument's own margin (4px top+bottom by
    default) sat INSIDE that same padding box, uncounted, eating into
    the reserved space. Zeroing the document margin removes the one
    unknowable factor, so the fixed height should now equal exactly
    font height + scrollbar height + the QSS box (16px padding + 2px
    border) — no slack, no shortfall."""
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    ed = SingleLineEdit("Дужи текст који прелази видљиву ширину поља")
    assert ed.document().documentMargin() == 0

    fm = ed.fontMetrics()
    sb_h = ed.horizontalScrollBar().sizeHint().height()
    expected = fm.height() + sb_h + 16 + 2
    assert ed.height() == expected


def test_single_line_edit_wrap_mode_shows_full_lines_not_horizontal_scroll(app) -> None:
    """`wrap=True` (for long-by-nature fields like full names/addresses)
    must wrap text across ~3 visible lines instead of scrolling
    sideways — the horizontal scrollbar must never appear in this mode."""
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    ed = SingleLineEdit(
        "ИВИЦА ЛАЧИЋ - Социјалистичка партија Србије и остале коалиционе странке",
        wrap=True,
    )
    assert ed.lineWrapMode() == SingleLineEdit.WidgetWidth
    from PySide6.QtCore import Qt
    assert ed.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert ed.document().documentMargin() == 0

    fm = ed.fontMetrics()
    expected = fm.height() * 3 + 16 + 2
    assert ed.height() == expected


def test_single_line_edit_wrap_mode_still_blocks_newlines(app) -> None:
    """Wrap mode is visual only — the stored value must stay one
    continuous string, same contract as the non-wrap mode, so
    downstream code (decision text, Excel round-trip) never has to
    special-case embedded newlines."""
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    ed = SingleLineEdit("почетак", wrap=True)
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    ed.keyPressEvent(event)
    assert ed.text() == "почетак"


def test_single_line_edit_multiline_mode_wraps_and_is_taller_than_wrap_mode(app) -> None:
    """multiline=True: same no-horizontal-scroll layout as wrap=True,
    but a taller box (_MULTILINE_LINES > _WRAP_LINES) — real paragraph
    breaks need more visible room than a single long value that just
    happens to wrap."""
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit
    from PySide6.QtCore import Qt

    ed = SingleLineEdit("line one\nline two\nline three", multiline=True)
    assert ed.lineWrapMode() == SingleLineEdit.WidgetWidth
    assert ed.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert ed.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    fm = ed.fontMetrics()
    expected = fm.height() * SingleLineEdit._MULTILINE_LINES + 16 + 2  # noqa: SLF001
    assert ed.height() == expected

    wrap_ed = SingleLineEdit("Дуг назив", wrap=True)
    assert ed.height() > wrap_ed.height()


def test_single_line_edit_multiline_mode_keeps_real_newlines_on_enter(app) -> None:
    """The whole point of multiline=True: unlike wrap mode, Enter must
    actually insert a line break — an operator entering a coalition
    list's official multi-line name needs this to work like a normal
    text box."""
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    ed = SingleLineEdit("почетак", multiline=True)
    cursor = ed.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    ed.setTextCursor(cursor)
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    ed.keyPressEvent(event)
    ed.insertPlainText("крај")
    assert ed.text() == "почетак\nкрај"


def test_single_line_edit_multiline_mode_keeps_pasted_newlines(app) -> None:
    from PySide6.QtCore import QMimeData
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit

    ed = SingleLineEdit(multiline=True)
    mime = QMimeData()
    mime.setText("прва линија\nдруга линија")
    ed.insertFromMimeData(mime)
    assert ed.text() == "прва линија\nдруга линија"


def test_row_edit_dialog_wrap_keys_applies_to_named_fields(app) -> None:
    from biracki_odbor.gui.widgets.searchable_table import RowEditDialog

    dlg = RowEditDialog(
        "Test",
        [("Кратки назив:", "abbrev", "СНС"), ("Пун назив:", "full", "Дуг назив")],
        wrap_keys={"full"},
    )
    assert dlg._edits["abbrev"].lineWrapMode() != dlg._edits["full"].lineWrapMode()  # noqa: SLF001
    from biracki_odbor.gui.widgets.searchable_table import SingleLineEdit
    assert dlg._edits["full"].lineWrapMode() == SingleLineEdit.WidgetWidth  # noqa: SLF001
    assert dlg._edits["abbrev"].lineWrapMode() == SingleLineEdit.NoWrap  # noqa: SLF001
