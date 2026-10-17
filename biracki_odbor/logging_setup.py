"""Application-wide logging setup.

Configures stdlib logging once at startup. File handler **rotates at
midnight** under `~/Biracki_Odbor/log/`, producing one file per day,
each named with its ISO date — `2026-05-25.log`, `2026-05-26.log`, …
Every file is self-identifying at a glance; no need to open it to
discover which day it covers. Keeps 30 days of history, then the
oldest gets deleted automatically.

Console handler is harmless in the bundled .exe (PyInstaller
`console=False` discards it) and useful when running `python -m
biracki_odbor` from a terminal.

Daily rotation is the right shape for Windows installs because there's
no `logrotate` daemon — the in-process `TimedRotatingFileHandler`
handles the roll itself.

Default level is INFO. Set `debug_logging=True` in `app_settings.json` (or
toggle the "Опширно логовање" checkbox in OIK Settings) to drop to DEBUG —
takes effect on next launch.
"""

from __future__ import annotations

import datetime as _dt
import logging
import logging.handlers
import time
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from biracki_odbor import app_paths


F = TypeVar("F", bound=Callable)


def log_timing(name: str | None = None) -> Callable[[F], F]:
    """Decorator: log wall-clock duration of the wrapped function as INFO.

    Use sparingly on suspected hotspots — output appears in app.log so we
    can spot bottlenecks without intrusive profiling.
    """
    def deco(fn: F) -> F:
        label = name or fn.__qualname__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            t = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - t) * 1000
                logging.getLogger(fn.__module__).info(
                    "timing %s: %.0f ms", label, elapsed,
                )
        return wrapper  # type: ignore[return-value]
    return deco


_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _dated_rotation_namer(default_name: str) -> str:
    """Convert TimedRotatingFileHandler's rotated filename to a clean dated form.

    By default the handler builds `<base>.<suffix>` — for our base
    `2026-05-25.log` and suffix `%Y-%m-%d` that produces
    `2026-05-25.log.2026-05-25`. We rewrite to just `<date>.log` so the
    rotated file shares the same naming shape as the active one.
    """
    p = Path(default_name)
    # `default_name` is e.g. "<dir>/2026-05-25.log.2026-05-25". The trailing
    # token after the last '.' is the rotation date. Replace the whole name
    # with `<rotation-date>.log` so every file in the directory matches the
    # `YYYY-MM-DD.log` pattern, regardless of when it rotated.
    rotation_date = p.suffix.lstrip(".")  # e.g. "2026-05-25"
    if rotation_date and rotation_date.replace("-", "").isdigit():
        return str(p.with_name(f"{rotation_date}.log"))
    return default_name


def configure(level: str = "INFO") -> Path:
    """Wire up the root logger. Returns the log file path."""
    log_dir = app_paths.log_dir()
    # Active log filename carries today's date — `<HOME>/log/2026-05-25.log`.
    # On midnight rollover the handler closes today's file and reopens
    # tomorrow's; both are self-named correctly by ISO date.
    today_iso = _dt.date.today().isoformat()
    log_path = log_dir / f"{today_iso}.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Drop any pre-existing handlers so re-configuration during tests stays clean.
    for h in list(root.handlers):
        root.removeHandler(h)

    # One file per day. 30-day retention spans an election cycle's
    # intensive phase (Phase 1 → Phase 3 typically 30-60 days) without
    # growing unbounded. `when="midnight"` rolls at local midnight.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", interval=1, backupCount=30,
        encoding="utf-8", utc=False,
    )
    # Empty suffix — the rolled file's name is `<HOME>/log/<rotation-time>.log`,
    # which TimedRotatingFileHandler builds by stripping our base extension
    # and appending its own. To get dated rotated files cleanly we override
    # the namer below.
    file_handler.suffix = "%Y-%m-%d"
    file_handler.namer = _dated_rotation_namer
    file_handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "logging configured: level=%s file=%s", level, log_path,
    )
    return log_path
