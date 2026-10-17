"""Tests for FileDropZone signal semantics.

The signal-loop regression that hung app startup in v0.9.x:
The template drop zone called FileDropZone.set_path() to reflect
the current template — set_path() emitted file_selected → the listener
called state.set_template_path() → that emitted template_changed →
which called the refresh handler again. ~100 reps per launch in the
wild, before Python's recursion limit broke the chain.

The fix: set_path() is display-only. `file_selected` fires only on
user actions (drag, drop, file picker). These tests pin that contract.
"""

from __future__ import annotations

import pytest

from biracki_odbor.gui.widgets.file_drop import FileDropZone


@pytest.fixture
def zone():
    z = FileDropZone()
    yield z
    z.deleteLater()


def test_set_path_does_not_emit_file_selected(zone: FileDropZone, tmp_path) -> None:
    """set_path is display-only — programmatic callers (e.g. the template
    drop zone restoring the current imported path) must not
    trigger file_selected and the signal chain it kicks off. If this
    test fails, app startup hangs in the loop that broke v0.9.0/v0.9.1."""
    received: list[str] = []
    zone.file_selected.connect(received.append)

    f = tmp_path / "template.xlsx"
    f.write_bytes(b"PK\x03\x04")  # path doesn't need to be a real .xlsx
    zone.set_path(f)

    assert received == [], (
        "set_path must NOT emit file_selected — that's how the v0.9.x"
        " sablon → template_changed → refresh loop self-perpetuated."
    )
    # But the visible state did update.
    assert zone.path == f
    assert str(f) in zone.path_label.text()
