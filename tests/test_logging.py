"""Tests for biracki_odbor.logging_setup."""

from __future__ import annotations

import datetime as _dt
import logging
import logging.handlers
from pathlib import Path

import pytest

from biracki_odbor import logging_setup


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    yield
    # Tear down: drop handlers so the test's file isn't held open and
    # the tmp_path can be cleaned up by pytest.
    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            h.close()
        except OSError:
            pass
        root.removeHandler(h)


def test_active_log_file_carries_iso_date(tmp_path: Path) -> None:
    """`<HOME>/log/<YYYY-MM-DD>.log` is the active file — self-identifying."""
    log_path = logging_setup.configure("INFO")
    today_iso = _dt.date.today().isoformat()
    assert log_path.name == f"{today_iso}.log"
    assert log_path.parent.name == "log"


def test_handler_is_timed_rotating(tmp_path: Path) -> None:
    logging_setup.configure("INFO")
    root = logging.getLogger()
    timed = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(timed) == 1, "expected exactly one TimedRotatingFileHandler"
    h = timed[0]
    assert h.when == "MIDNIGHT"
    assert h.backupCount == 30
    assert h.encoding == "utf-8"


def test_rotation_namer_produces_dated_filename(tmp_path: Path) -> None:
    """`_dated_rotation_namer` rewrites the default `<base>.<suffix>` form
    into a clean `<date>.log` — so rotated files share the same shape as
    the active file."""
    default = "/home/user/log/2026-05-25.log.2026-05-26"
    renamed = logging_setup._dated_rotation_namer(default)
    assert renamed.endswith("2026-05-26.log")


def test_rotation_namer_passes_through_unrecognized(tmp_path: Path) -> None:
    """Anything that doesn't look like a date suffix gets returned as-is."""
    default = "/home/user/log/something.weird"
    assert logging_setup._dated_rotation_namer(default) == default


def test_configure_writes_a_line(tmp_path: Path) -> None:
    """End-to-end: configure → log a line → file exists with that line."""
    log_path = logging_setup.configure("INFO")
    logging.getLogger("test").info("hello")
    # Force flush by removing the handler (also drops the file lock).
    root = logging.getLogger()
    for h in list(root.handlers):
        h.flush()
    content = log_path.read_text(encoding="utf-8")
    assert "hello" in content
