"""Tests for the StatusBanner auto-hide behaviour.

The banner auto-hides success messages after a short delay so an
operator-acknowledged "Saved." doesn't linger as visual noise. Warnings
and errors stay until the next banner action — they often flag
something the operator should fix before moving on, and silently
auto-hiding them could mask a real problem.

These tests trigger the QTimer's `timeout` signal directly instead of
waiting 5 real seconds. We're testing the wiring (timer running yes/no,
banner state after timeout), not the actual ~5 s wall-clock delay,
which is hard-coded and trivial to read in the source.
"""

from __future__ import annotations

import pytest

from biracki_odbor.gui.widgets.banner import StatusBanner


@pytest.fixture
def banner():
    """A fresh banner per test. _qapp_session (conftest) keeps QApplication alive."""
    b = StatusBanner()
    yield b
    b.deleteLater()


def test_show_ok_starts_autohide_timer(banner: StatusBanner) -> None:
    """show_ok must (a) display the banner and (b) start the auto-hide timer."""
    banner.show_ok("Сачувано.")
    assert banner.isVisibleTo(banner.parentWidget() or banner)
    # isVisible() returns False until shown by an event loop pass; isHidden()
    # is the reliable check for "show() has been called".
    assert not banner.isHidden()
    assert banner._autohide.isActive(), "show_ok must arm the auto-hide timer"
    assert banner._autohide.isSingleShot()


def test_autohide_timeout_clears_banner(banner: StatusBanner) -> None:
    """Firing the timer's timeout signal must clear + hide the banner."""
    banner.show_ok("Сачувано.")
    assert not banner.isHidden()
    # Pretend the 5 s elapsed.
    banner._autohide.timeout.emit()
    assert banner.isHidden(), "banner must hide once the auto-hide timer fires"
    assert banner._label.text() == "", "banner text must be cleared on auto-hide"


def test_show_warn_does_not_autohide(banner: StatusBanner) -> None:
    """Warnings stay until the next action — operator must see them."""
    banner.show_warn("Нема података.")
    assert not banner.isHidden()
    assert not banner._autohide.isActive(), (
        "warnings must NOT auto-hide — they often flag work-in-progress issues"
    )


def test_show_error_does_not_autohide(banner: StatusBanner) -> None:
    """Errors stay until explicitly cleared — auto-hide could mask real failures."""
    banner.show_error("Грешка при чувању.")
    assert not banner.isHidden()
    assert not banner._autohide.isActive(), "errors must NOT auto-hide"


def test_show_warn_after_show_ok_cancels_autohide(banner: StatusBanner) -> None:
    """A warning replacing an OK must cancel the pending auto-hide,
    or the warning would silently vanish after 5 s — exactly the
    behaviour we don't want."""
    banner.show_ok("Сачувано.")
    assert banner._autohide.isActive()
    banner.show_warn("Али нешто није у реду.")
    assert not banner._autohide.isActive(), (
        "show_warn following show_ok must stop the pending auto-hide so the"
        " warning doesn't silently disappear"
    )


def test_clear_stops_pending_autohide(banner: StatusBanner) -> None:
    """Manual clear() must stop the timer so a stale fire doesn't
    re-hide a future banner."""
    banner.show_ok("Сачувано.")
    assert banner._autohide.isActive()
    banner.clear()
    assert not banner._autohide.isActive()
    assert banner.isHidden()


def test_show_info_autohides_like_ok(banner: StatusBanner) -> None:
    """show_info uses the same styling + auto-hide as show_ok."""
    banner.show_info("Учитано 312 ставки.")
    assert not banner.isHidden()
    assert banner._autohide.isActive()
