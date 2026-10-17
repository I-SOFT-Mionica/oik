"""Resolves a field_key to its printable value — shared by
`overlay_fill` (one voter's declaration) and `generic_export` (many
voters' cumulative roster), so a field means the same thing whichever
one is reading it.

The same value pool a print position draws from: VoterEntry's own
attributes/composites, and any "universal" custom-field value typed
once for the session (see models.SessionInfo.custom_values) — a list
name, a certifier, a municipality, or whatever else a given document
needs fixed for the whole sitting, named by the operator rather than a
handful of concepts hardcoded onto SessionInfo itself.
"""

from __future__ import annotations

from typing import Any

from formalizator.core.models import SessionInfo, VoterEntry


def resolve_values(entry: VoterEntry, session_info: SessionInfo | None = None) -> dict[str, Any]:
    values = entry.to_dict()
    if session_info is not None:
        values.update(session_info.custom_values)
    return values
