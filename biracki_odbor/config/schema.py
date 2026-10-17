"""Shared config-validation helpers (no third-party deps)."""

from __future__ import annotations

from typing import Any


def require_keys(d: Any, keys: list[str], where: str) -> list[str]:
    """Return Cyrillic error strings for any missing/empty keys."""
    errors: list[str] = []
    if not isinstance(d, dict):
        return [f"{where}: очекиван објекат, добијено {type(d).__name__}"]
    for k in keys:
        if k not in d:
            errors.append(f"{where}: недостаје поље '{k}'")
        elif d[k] in (None, "", []):
            errors.append(f"{where}: поље '{k}' је празно")
    return errors


def coerce_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def coerce_int(v: Any, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default


def coerce_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
