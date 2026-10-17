"""Guards for the 2026-10-16 signal decoupling: an edit must only wake
the screens that depend on it. Each broad cascade used to re-render every
preview, rebuild the RIK cards and re-copy generated files on every
keystroke-level save."""

from __future__ import annotations

import pytest


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path / "home"))
    from biracki_odbor.gui.app_state import AppState
    return AppState()


def _record(state, *names):
    fired: list[str] = []
    for n in names:
        getattr(state, n).connect(lambda n=n: fired.append(n))
    return fired


_ALL = ("election_changed", "oik_changed", "generation_log_changed",
        "resenja_fields_changed", "document_format_changed")


def test_resenja_field_save_does_not_wake_the_whole_app(state) -> None:
    fired = _record(state, *_ALL)
    state.save_resenja_fields()
    assert fired == ["resenja_fields_changed"]


def test_document_format_save_does_not_emit_oik_changed(state) -> None:
    fired = _record(state, *_ALL)
    state.save_document_format()
    assert fired == ["document_format_changed"]


def test_election_save_reloads_generation_log_only_on_new_cycle(state) -> None:
    state.save_election()  # fresh install: the first save assigns the cycle UUID
    fired = _record(state, "generation_log_changed")
    state.save_election()
    assert fired == []

    state.election.election_uuid = "new-cycle-uuid"
    state.save_election()
    assert fired == ["generation_log_changed"]
    assert state.generation_log.election_uuid == "new-cycle-uuid"


def test_hidden_preview_defers_painting_until_shown(state) -> None:
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.gui.widgets.paginated_preview import PaginatedPreview
    p = PaginatedPreview()
    p.set_html("<p>РЕШЕЊЕ</p>")
    assert "РЕШЕЊЕ" in p.to_plain_text()
    assert p._page_labels == []  # noqa: SLF001
    p.show()
    QApplication.processEvents()
    assert len(p._page_labels) == p.page_count  # noqa: SLF001
    p.close()


def test_open_button_check_never_copies_files(state, tmp_path) -> None:
    from biracki_odbor import app_paths
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab
    export_root = tmp_path / "export"
    state.app_settings.default_files_dir = str(export_root)
    tab = Phase3Tab(state)
    out = app_paths.resenja_dir_for(tab._spec)  # noqa: SLF001
    out.mkdir(parents=True, exist_ok=True)
    (out / "1 resenje.docx").write_bytes(b"x")
    before = sorted(export_root.rglob("*.docx")) if export_root.exists() else []
    tab._restore_open_btn()  # noqa: SLF001
    after = sorted(export_root.rglob("*.docx")) if export_root.exists() else []
    assert tab.btn_open.isEnabled()
    assert after == before
    tab.deleteLater()
