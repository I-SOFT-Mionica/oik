"""Formalizator — voter-support signature collection companion app.

Named after `Celik/Formalizator.py`, the original single-municipality
prototype this grew out of; "Čelik" now refers only to MUP's own eID
card API (`reader/eid_reader.py`), not to the product.

Reads a Serbian eID card (or accepts manual entry for older, chip-less
IDs), fills the official per-voter declaration (NPRS-3) via a PDF
overlay on a frozen background, and — if configured for the session,
an optional step right after a template is picked — exports the
session's cumulative roster (e.g. NPRS-4) via an operator-defined
export template (`core.generic_export`) instead of a hardcoded layout.

Separate app from `biracki_odbor` (different actor, different timing —
signature collection happens before an OIK for a cycle exists), but
shares this repo's GUI code (`biracki_odbor.gui.style`, `.widgets`) and
JMBG validation (`biracki_odbor.core.jmbg`) so it looks and behaves
like the same product family.
"""

from __future__ import annotations

__version__ = "0.1.0"
