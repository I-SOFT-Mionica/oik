"""Tests for ElectionSettingsTab's RIK import action:
`_import_from_rik_files` (dispatch) + `_on_rik_import_finished`/
`_on_rik_import_failed` (applying the background worker's result).

Same testing strategy as `test_pdf_import_progress.py` — the only other
start_worker()-backed action with a progress bar in this codebase: mock
`start_worker` itself (no real QThread/timing involved) to test dispatch
+ immediate UI state, and call the finished/failed handlers directly
with synthetic results to test the "apply to state" logic. Keeps these
tests fast and deterministic instead of pumping a real background
thread's event loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixtures.rik_raspodela import build_raspodela_workbook, build_ukupno_workbook


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    yield


def _make_tab(sifra: str = ""):
    from PySide6.QtWidgets import QApplication
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs.settings_election import ElectionSettingsTab

    QApplication.instance() or QApplication([])

    state = AppState()
    state.oik.municipality.name = "Уб"
    state.oik.municipality.sifra_opstine = sifra
    tab = ElectionSettingsTab(state)
    return tab


class _FakeSignal:
    def connect(self, slot):
        pass


class _FakeWorker:
    def __init__(self):
        self.progress = _FakeSignal()
        self.finished = _FakeSignal()
        self.failed = _FakeSignal()


def _mock_open_dialogs(monkeypatch, *paths: str) -> None:
    """Each call to getOpenFileName returns the next path in order."""
    it = iter(paths)

    def _fake(*_a, **_kw):
        return next(it, ""), ""

    monkeypatch.setattr(
        "biracki_odbor.gui.tabs.settings_election.QFileDialog.getOpenFileName", _fake,
    )


def test_import_without_municipality_selected_shows_error() -> None:
    tab = _make_tab(sifra="")
    try:
        tab._import_from_rik_files()  # noqa: SLF001
        assert "municipality" in tab.banner._label.text().lower()
    finally:
        tab.deleteLater()


def test_import_dispatches_worker_ukupno_first_then_raspodela(monkeypatch) -> None:
    """Field report: UKUPNO (parliamentary group names) must be picked
    BEFORE the RASPODELA file, and the actual parsing must run through
    start_worker (background thread + progress bar), not synchronously
    on the GUI thread."""
    import biracki_odbor.gui.tabs.settings_election as mod

    calls = []

    def fake_start_worker(parent, fn, *args, **kwargs):
        calls.append((parent, fn, args, kwargs))
        return _FakeWorker(), object()

    monkeypatch.setattr(mod, "start_worker", fake_start_worker)
    _mock_open_dialogs(monkeypatch, "C:/fake_ukupno.xlsx", "C:/fake_raspodela.xlsx")
    # Bypass the file-safety check (a fake path won't pass it) so we can
    # focus purely on dispatch order/args.
    monkeypatch.setattr(
        "biracki_odbor.core.popunjeni_io.check_file_safety",
        lambda _p: type("S", (), {"ok": True, "code": "", "detail": ""})(),
    )

    tab = _make_tab(sifra="71218")
    try:
        assert not tab.rik_import_progress.isVisibleTo(tab)
        assert tab.btn_import_rik.isEnabled()

        tab._import_from_rik_files()  # noqa: SLF001

        assert len(calls) == 1
        _, fn, args, kwargs = calls[0]
        assert fn is mod.rik_raspodela_mod.import_municipality
        assert args == ("C:/fake_raspodela.xlsx", "71218")
        assert kwargs == {"ukupno_path": "C:/fake_ukupno.xlsx"}

        # Progress bar + disabled button appear synchronously, before
        # any parsing happens — same contract pdf_import_dialog.py's
        # test pins for its own start_worker() action.
        assert tab.rik_import_progress.isVisibleTo(tab)
        assert not tab.btn_import_rik.isEnabled()
    finally:
        tab.deleteLater()


def test_import_skips_ukupno_when_cancelled(monkeypatch) -> None:
    import biracki_odbor.gui.tabs.settings_election as mod

    calls = []

    def fake_start_worker(parent, fn, *args, **kwargs):
        calls.append((parent, fn, args, kwargs))
        return _FakeWorker(), object()

    monkeypatch.setattr(mod, "start_worker", fake_start_worker)
    _mock_open_dialogs(monkeypatch, "", "C:/fake_raspodela.xlsx")  # Cancel on UKUPNO
    monkeypatch.setattr(
        "biracki_odbor.core.popunjeni_io.check_file_safety",
        lambda _p: type("S", (), {"ok": True, "code": "", "detail": ""})(),
    )

    tab = _make_tab(sifra="71218")
    try:
        tab._import_from_rik_files()  # noqa: SLF001
        _, _fn, args, kwargs = calls[0]
        assert args == ("C:/fake_raspodela.xlsx", "71218")
        assert kwargs == {"ukupno_path": None}
    finally:
        tab.deleteLater()


def test_on_rik_import_failed_recovers_ui(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: warned.append(True))

    tab = _make_tab(sifra="71218")
    try:
        tab.rik_import_progress.setVisible(True)
        tab.btn_import_rik.setEnabled(False)

        tab._on_rik_import_failed("boom")  # noqa: SLF001

        assert warned
        assert not tab.rik_import_progress.isVisibleTo(tab)
        assert tab.btn_import_rik.isEnabled()
    finally:
        tab.deleteLater()


def test_on_rik_import_finished_applies_result(tmp_path: Path) -> None:
    from biracki_odbor.core.rik_raspodela_import import read_municipality_allocation

    raspodela = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    ukupno = build_ukupno_workbook(tmp_path / "ukupno.xlsx")
    from biracki_odbor.core.rik_raspodela_import import read_party_full_names
    result = read_municipality_allocation(raspodela, "71218")
    result.party_full_names = read_party_full_names(ukupno)

    tab = _make_tab(sifra="71218")
    try:
        tab.rik_import_progress.setVisible(True)
        tab.btn_import_rik.setEnabled(False)

        tab._on_rik_import_finished(result)  # noqa: SLF001

        assert not tab.rik_import_progress.isVisibleTo(tab)
        assert tab.btn_import_rik.isEnabled()

        assert [s.bm_number for s in tab.state.oik.polling_stations] == [1, 2, 3]
        assert set(tab.state.election.party_quotas) == {"СНС", "СПС", "ССП"}
        full_by_abbrev = {r["abbrev"]: r["full"] for r in tab._parties_rows}
        assert full_by_abbrev["СНС"] == "Посланичка група СНС — пуни назив"

        from biracki_odbor import app_paths
        from biracki_odbor.core.template import read_template
        canonical = app_paths.sablon_dir() / "Stalni_sastav.xlsx"
        assert canonical.exists()
        tpl_data, report = read_template(canonical)
        assert report.ok
        assert len(tpl_data.allocations) == 3 * 6
    finally:
        tab.deleteLater()


def test_on_rik_import_finished_with_errors_shows_banner() -> None:
    from biracki_odbor.core.rik_raspodela_import import RikMunicipalityImport

    tab = _make_tab(sifra="71218")
    try:
        result = RikMunicipalityImport(errors=["нешто није у реду"])
        tab._on_rik_import_finished(result)  # noqa: SLF001
        assert "нешто није у реду" in tab.banner._label.text()
        assert tab.state.oik.polling_stations == []
    finally:
        tab.deleteLater()


def test_on_rik_import_finished_merges_into_already_declared_group(tmp_path: Path) -> None:
    """A parliamentary group already declared by hand (e.g. with contact
    info) keeps its row — the importer only adds NEW abbreviations, and
    always merges quota numbers rather than skipping known groups."""
    from biracki_odbor.core.rik_raspodela_import import read_municipality_allocation

    raspodela = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(raspodela, "71218")

    tab = _make_tab(sifra="71218")
    try:
        tab._append_party_row("СНС", "Ручно унети пуни назив", "sns@example.rs", "")
        tab._refresh_parties_view()

        tab._on_rik_import_finished(result)  # noqa: SLF001

        rows_by_abbrev = {r["abbrev"]: r for r in tab._parties_rows}
        assert rows_by_abbrev["СНС"]["full"] == "Ручно унети пуни назив"
        assert rows_by_abbrev["СНС"]["email"] == "sns@example.rs"
        assert "СНС" in tab.state.election.party_quotas
        assert "СПС" in rows_by_abbrev
        assert "ССП" in rows_by_abbrev
    finally:
        tab.deleteLater()


def test_on_rik_import_finished_preserves_existing_bm_names(tmp_path: Path) -> None:
    """Field report: "it would seem that we are erasing the saved bm
    names" — confirmed. RIK's RASPODELA export is a party-allocation
    matrix, not a polling-station directory: core.rik_raspodela_import.
    _read_allocation_grid only ever constructs PollingStation(bm_number=
    ...), never name/address/full_name — RIK's own data structurally
    cannot supply those. The old code did a flat
    `self.state.oik.polling_stations = result.stations`, which wiped
    out every already-entered BM name/address on every single import,
    with no way for RIK's import to ever produce a better one. Existing
    name/address/full_name must survive, matched by bm_number; only a
    genuinely new BM (one RIK reports that wasn't configured before)
    gets the blank ones RIK itself provides."""
    from biracki_odbor.core.models import PollingStation
    from biracki_odbor.core.rik_raspodela_import import read_municipality_allocation

    raspodela = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    result = read_municipality_allocation(raspodela, "71218")  # 3 BMs: 1, 2, 3

    tab = _make_tab(sifra="71218")
    try:
        # Operator already entered real names/addresses for BM 1 and 2
        # (e.g. typed in by hand before ever touching RIK import). BM 3
        # doesn't exist yet — RIK's import will introduce it fresh.
        tab.state.oik.polling_stations = [
            PollingStation(bm_number=1, name="ОШ Дринка", address="Улица 1", full_name="ОШ Дринка (пуна)"),
            PollingStation(bm_number=2, name="Дом културе", address="Улица 2", full_name="Дом културе (пуна)"),
        ]

        tab._on_rik_import_finished(result)  # noqa: SLF001

        by_bm = {s.bm_number: s for s in tab.state.oik.polling_stations}
        assert by_bm[1].name == "ОШ Дринка"
        assert by_bm[1].address == "Улица 1"
        assert by_bm[1].full_name == "ОШ Дринка (пуна)"
        assert by_bm[2].name == "Дом културе"
        # BM 3 is genuinely new — RIK never had a name for it, so blank
        # is correct (not a regression — there's nothing to preserve).
        assert by_bm[3].name == ""
        assert set(by_bm) == {1, 2, 3}
    finally:
        tab.deleteLater()


def test_on_rik_import_finished_backfills_blank_full_name(tmp_path: Path) -> None:
    """Field report: "Пуни назив" stayed empty even after re-importing
    with a file that actually carries the party-name legend. Root
    cause: the merge loop only ever called _append_party_row() for an
    abbreviation NOT already in self._parties_rows — an abbreviation
    added by an earlier RASPODELA-only import (no UKUPNO file supplied
    that time) already existed with full="", so a later re-import could
    never fill it in, no matter how many times it ran. An existing row
    with SOME full name (manually typed, or from a prior successful
    import) must still be left untouched — see
    test_on_rik_import_finished_merges_into_already_declared_group."""
    from biracki_odbor.core.rik_raspodela_import import read_municipality_allocation

    raspodela = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    ukupno = build_ukupno_workbook(tmp_path / "ukupno.xlsx")
    from biracki_odbor.core.rik_raspodela_import import read_party_full_names
    result = read_municipality_allocation(raspodela, "71218")
    result.party_full_names = read_party_full_names(ukupno)

    tab = _make_tab(sifra="71218")
    try:
        # Simulates an earlier RASPODELA-only import: the abbreviation
        # is already on file, with no full name and no contact info.
        tab._append_party_row("СНС", "", "", "")
        tab._refresh_parties_view()

        tab._on_rik_import_finished(result)  # noqa: SLF001

        rows_by_abbrev = {r["abbrev"]: r for r in tab._parties_rows}
        assert rows_by_abbrev["СНС"]["full"] == "Посланичка група СНС — пуни назив"
        # Still only one СНС row — backfilled in place, not duplicated.
        assert sum(1 for r in tab._parties_rows if r["abbrev"] == "СНС") == 1
    finally:
        tab.deleteLater()


def test_import_municipality_is_plain_python_no_qt(tmp_path: Path) -> None:
    """The background function itself must be callable without a
    QApplication — it runs inside a worker thread, not the GUI thread."""
    from biracki_odbor.core.rik_raspodela_import import import_municipality

    raspodela = build_raspodela_workbook(tmp_path / "raspodela.xlsx")
    ukupno = build_ukupno_workbook(tmp_path / "ukupno.xlsx")

    seen = []
    result = import_municipality(
        raspodela, "71218", ukupno_path=ukupno,
        progress=lambda label, cur, total: seen.append((label, cur, total)),
    )
    assert result.errors == []
    assert len(result.stations) == 3
    assert result.party_full_names["СНС"] == "Посланичка група СНС — пуни назив"
    # Progress must report at least a start and a done step.
    assert seen[0][1:] == (0, 2)
    assert seen[-1][1:] == (2, 2)
