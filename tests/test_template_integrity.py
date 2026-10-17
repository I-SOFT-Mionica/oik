"""Integration tests for the Stalni_sastav.xlsx integrity wiring.

Covers: a GUI-driven import records a fingerprint, an out-of-band
change is detected on the next read (AppState.template_path and the
Phase1Tab/Phase2Tab preflight paths that call it), and restoring the
verified snapshot clears the block.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "", raising=False)
    yield


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.core.models import PollingStation

    state = AppState()
    state.oik.polling_stations = [PollingStation(bm_number=1, name="БМ 1")]
    state.save_oik()
    return state


def _import_template(tab, path: str) -> None:
    """`_on_template_chosen()` without `silent=True` runs the same
    BM-cross-validation as a real external import — and a freshly
    `build_blank_template()`-generated file always has zero filled
    allocations (that's the whole point, it's for the operator to fill
    in), which always trips the "BM missing from template" warning.
    `_save_matrix()` dodges this with `silent=True` for exactly this
    reason (see its own docstring) — these tests aren't testing that
    warning, so stub it out rather than block CI on a real modal with
    nobody there to click it (confirmed: this hung a GitHub Actions run
    for hours before being caught here)."""
    import unittest.mock as mock
    from PySide6.QtWidgets import QMessageBox
    with mock.patch.object(QMessageBox, "warning"):
        tab._on_template_chosen(path)  # noqa: SLF001


def test_import_records_fingerprint_and_read_passes(app, tmp_path) -> None:
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.core import file_integrity
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    src = tmp_path / "external_Stalni_sastav.xlsx"
    build_blank_template(src, stations=state.oik.polling_stations)

    tab = ElectionSettingsTab(state)
    try:
        _import_template(tab, str(src))

        canonical = state.template_path()
        assert canonical is not None
        assert file_integrity.has_verified_copy(canonical)
        # A second read right after import must not raise.
        assert state.template_path() == canonical
    finally:
        tab.deleteLater()


def test_out_of_band_change_raises_on_next_read(app, tmp_path) -> None:
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.core.file_integrity import IntegrityMismatchError
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    src = tmp_path / "external_Stalni_sastav.xlsx"
    build_blank_template(src, stations=state.oik.polling_stations)

    tab = ElectionSettingsTab(state)
    try:
        _import_template(tab, str(src))
        canonical = state.template_path()
        assert canonical is not None

        # Simulate tampering / corruption / a ransomware pass — anything
        # that touches the file outside the app's own write path.
        canonical.write_bytes(b"PK\x03\x04 not the original content anymore")

        with pytest.raises(IntegrityMismatchError):
            state.template_path()
    finally:
        tab.deleteLater()


def test_phase1_and_phase2_preflight_block_on_mismatch_without_crashing(app, tmp_path) -> None:
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab
    from biracki_odbor.gui.tabs.phase1 import Phase1Tab
    from biracki_odbor.gui.tabs.phase2 import Phase2Tab

    state = _make_state(tmp_path)
    src = tmp_path / "external_Stalni_sastav.xlsx"
    build_blank_template(src, stations=state.oik.polling_stations)

    settings_tab = ElectionSettingsTab(state)
    try:
        _import_template(settings_tab, str(src))
        canonical = state.template_path()
        assert canonical is not None
        canonical.write_bytes(b"tampered content, not through the app")

        p1 = Phase1Tab(state)
        p2 = Phase2Tab(state)
        try:
            # Must not raise — Phase1Tab/Phase2Tab catch the mismatch
            # internally and disable the Run button instead of crashing.
            p1._refresh_preflight()  # noqa: SLF001
            p2._refresh_preflight()  # noqa: SLF001
            assert not p1.btn_run.isEnabled()
            assert not p2.btn_run.isEnabled()
            assert p1._template_integrity_error is not None  # noqa: SLF001
            assert p2._template_integrity_error is not None  # noqa: SLF001
        finally:
            p1.deleteLater()
            p2.deleteLater()
    finally:
        settings_tab.deleteLater()


def test_restore_verified_clears_the_block(app, tmp_path) -> None:
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.core import file_integrity
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    state = _make_state(tmp_path)
    src = tmp_path / "external_Stalni_sastav.xlsx"
    build_blank_template(src, stations=state.oik.polling_stations)

    tab = ElectionSettingsTab(state)
    try:
        _import_template(tab, str(src))
        canonical = state.template_path()
        assert canonical is not None
        good_content = canonical.read_bytes()

        canonical.write_bytes(b"tampered")
        assert file_integrity.restore_verified(canonical) is True
        assert canonical.read_bytes() == good_content

        # Must read cleanly again after restore.
        assert state.template_path() == canonical
    finally:
        tab.deleteLater()


def test_new_cycle_reset_does_not_crash_on_tampered_template(app, tmp_path) -> None:
    """§ New election cycle rewrites the template's allocations in
    place — must not crash if the pre-existing file fails integrity."""
    from biracki_odbor.core.template import build_blank_template
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab
    import biracki_odbor.gui.dialogs.backup_flow as backup_flow_mod

    state = _make_state(tmp_path)
    src = tmp_path / "external_Stalni_sastav.xlsx"
    build_blank_template(src, stations=state.oik.polling_stations)

    tab = ElectionSettingsTab(state)
    try:
        _import_template(tab, str(src))
        canonical = state.template_path()
        assert canonical is not None
        canonical.write_bytes(b"tampered before a new cycle reset")

        import unittest.mock as mock
        from PySide6.QtWidgets import QMessageBox
        # _on_new_cycle() calls run_backup_flow(self) first — its own
        # interactive dialog, unrelated to the tampered-template path
        # this test targets — bypass it the same way
        # tests/test_new_election_cycle.py does, or it hangs waiting
        # for a click that never comes (no QMessageBox mock covers it).
        with mock.patch.object(backup_flow_mod, "run_backup_flow", lambda parent: "backup ok"), \
             mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes), \
             mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            tab._on_new_cycle()  # noqa: SLF001 — must not raise
    finally:
        tab.deleteLater()
