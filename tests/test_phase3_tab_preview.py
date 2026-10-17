"""Regression tests: Phase3Tab's live preview panel (`_refresh_preview`)
must show the disposition's closing points (2. објављује се / 3. ступа на
снагу) and the УПУТСТВО О ПРАВНОМ СРЕДСТВУ block — the real generated
.docx (core/phase3_docx.py) always includes all three, but the preview's
own hand-rolled HTML builder skipped straight from образложење to the
Број footer, silently dropping them from what the operator reviews before
generating."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))
    from biracki_odbor import _release_info
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "", raising=False)


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_state(tmp_path):
    from biracki_odbor.gui.app_state import AppState
    from tests.test_phase1 import _make_oik
    from tests.test_phase3 import _make_election

    state = AppState()
    state._oik = _make_oik(2)  # noqa: SLF001
    state._election = _make_election()  # noqa: SLF001
    return state


def test_preview_shows_objavljuje_se_and_stupa_na_snagu(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    state = _make_state(tmp_path)
    tab = Phase3Tab(state)
    try:
        text = tab._preview.to_plain_text()  # noqa: SLF001
        assert "објављује се на веб-презентацији" in text
        assert "ступа на снагу даном објављивања" in text
    finally:
        tab.deleteLater()


def test_preview_shows_legal_remedy_instruction(app, tmp_path) -> None:
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    state = _make_state(tmp_path)
    tab = Phase3Tab(state)
    try:
        text = tab._preview.to_plain_text()  # noqa: SLF001
        assert "УПУТСТВО О ПРАВНОМ СРЕДСТВУ" in text
        assert "48 часова" in text
    finally:
        tab.deleteLater()


def test_preview_title_block_is_grammatical_for_a_single_election_type(app, tmp_path) -> None:
    """"ЗА ИЗБОРА ЗА" (missing СПРОВОЂЕЊЕ) isn't grammatical Serbian —
    mirrors the same fix in core.phase3_docx's real generator."""
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    state = _make_state(tmp_path)
    tab = Phase3Tab(state)
    try:
        text = tab._preview.to_plain_text()  # noqa: SLF001
        assert "ЗА СПРОВОЂЕЊЕ ИЗБОРА ЗА НАРОДНЕ ПОСЛАНИКЕ НАРОДНЕ СКУПШТИНЕ" in text
        assert "ЗА ИЗБОРА ЗА" not in text
    finally:
        tab.deleteLater()


def test_last_card_anchor_resolves_even_when_earlier_optional_paragraphs_are_filtered(app, tmp_path) -> None:
    """Regression: the default seed has 2 optional (local-election-only)
    paragraphs sitting BEFORE the final "zakljucak" card. render() drops
    them when local_elections is False (the default _make_election()),
    so render()'s output is 2 items shorter than self._cards() --
    anchoring by plain position (card_<n-th card>) pointed at an anchor
    that was never written into the HTML at all, silently breaking the
    jump for every card after the first filtered one. "zakljucak" was
    the one a live operator actually hit this on."""
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    state = _make_state(tmp_path)
    tab = Phase3Tab(state)
    try:
        cards = tab._cards()
        ids = [c.paragraph_id for c in cards]
        assert "zakljucak" in ids  # sanity: default seed still has it
        zakljucak_idx = ids.index("zakljucak")
        # The bug only reproduces when something precedes it that gets
        # filtered -- confirm that precondition instead of assuming it.
        assert zakljucak_idx > 0

        # The old, wrong anchor (by plain position) must NOT exist --
        # it would only coincidentally work if nothing upstream had
        # been filtered, which isn't the case here.
        wrong_cursor = tab._preview._doc.find(f"⁣card_{zakljucak_idx}⁣")  # noqa: SLF001
        assert wrong_cursor.isNull()

        # The real, id-based anchor must exist and resolve.
        assert tab._preview.scroll_to_anchor("card_zakljucak") is True  # noqa: SLF001
    finally:
        tab.deleteLater()


def test_scroll_to_anchor_survives_immediate_teardown(app, tmp_path) -> None:
    """Regression: scroll_to_anchor() defers its actual scroll one
    event-loop tick (the target page label's geometry isn't reliably
    settled until any layout work queued by the same focus-change event
    has run). The first version used the bare QTimer.singleShot(0, ...)
    class method, whose timer isn't tied to the widget's lifetime --
    every test in this file (and test_phase3.py, test_izmene.py)
    constructs a tab, triggers a scroll, then calls deleteLater() with
    no explicit event-loop pumping in between, exactly like pytest's
    own implicit teardown. That reliably crashed the whole CI process
    (not a caught Python exception -- a native-level over-the-wall
    crash with no traceback) the one time this shipped as a plain
    singleShot: CI showed "1640 passed" immediately followed by a bare
    nonzero exit. Running MANY construct/scroll/teardown cycles here,
    each exactly matching every other test's own pattern, is the
    actual regression coverage -- a single cycle wasn't enough to
    reproduce it even locally before this fix."""
    from biracki_odbor.gui.tabs.phase3 import Phase3Tab

    for _ in range(15):
        state = _make_state(tmp_path)
        tab = Phase3Tab(state)
        cards = tab._cards()
        if cards:
            tab._on_focus_changed(None, cards[0])
        tab.deleteLater()
        app.processEvents()
    # If a dangling timer from an earlier iteration is still pending,
    # this is where it would fire against an already-deleted widget.
    for _ in range(20):
        app.processEvents()
