"""Tests for the About page's in-app changelog version filtering.

Field report: the "Шта је ново" list was showing its one static entry
to every user regardless of what version they had installed -- there
was no filtering at all (`self._cl_entries = _CHANGELOG` unconditional).
Intended behavior: an operator only sees entries strictly newer than
the version they're currently running -- a preview of "what updating
gets you", not a permanent history."""

from __future__ import annotations

import json

import pytest

from biracki_odbor.gui.about_page import (
    _changelog_since, _load_cached_changelog, _merge_changelog, _version_tuple,
)


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """AboutPage now reads the server-changelog cache via app_paths.home()
    on every construction (see _build_hero) -- without this, every test
    in this file would touch the real ~/OIK/cache/ directory."""
    monkeypatch.setenv("BIRACKI_ODBOR_HOME", str(tmp_path))


def test_version_tuple_basic() -> None:
    assert _version_tuple("0.72.0") == (0, 72, 0)
    assert _version_tuple("1.2.3") == (1, 2, 3)


def test_version_tuple_orders_correctly_past_single_digits() -> None:
    """Lexicographic string comparison would get "0.9.0" > "0.10.0"
    wrong -- the tuple comparison must not."""
    assert _version_tuple("0.10.0") > _version_tuple("0.9.0")


def test_version_tuple_malformed_segment_degrades_to_zero() -> None:
    """Must not raise on a stray pre-release suffix or garbage input --
    a version-parsing glitch shouldn't be able to crash the About page."""
    assert _version_tuple("0.72.0-rc1") == (0, 72, 0)
    assert _version_tuple("not-a-version") == (0,)


def _entries():
    return [
        ("0.73.1", "20.7.2026.", ["c"]),
        ("0.73.0", "18.7.2026.", ["b"]),
        ("0.60.0", "7.7.2026.", ["a"]),
    ]


def test_changelog_since_old_install_sees_everything_newer() -> None:
    result = _changelog_since(_entries(), "0.60.0")
    versions = [v for v, _, _ in result]
    assert versions == ["0.73.1", "0.73.0"]


def test_changelog_since_recent_install_sees_only_the_diff() -> None:
    result = _changelog_since(_entries(), "0.73.0")
    versions = [v for v, _, _ in result]
    assert versions == ["0.73.1"]


def test_changelog_since_up_to_date_sees_nothing() -> None:
    result = _changelog_since(_entries(), "0.73.1")
    assert result == []


def test_changelog_since_never_includes_installed_versions_own_entry() -> None:
    """A version's own entry must not reappear once you're actually
    running it -- only strictly-newer entries qualify."""
    result = _changelog_since(_entries(), "0.73.0")
    versions = [v for v, _, _ in result]
    assert "0.73.0" not in versions


def test_up_to_date_install_hides_the_changelog_button(app, monkeypatch) -> None:
    import biracki_odbor.gui.about_page as about_page_mod

    latest = about_page_mod._CHANGELOG[0][0]
    monkeypatch.setattr(about_page_mod, "__version__", latest)
    page = about_page_mod.AboutPage()
    try:
        assert page._cl_entries == []  # noqa: SLF001
        assert not page.btn_changelog.isVisibleTo(page)
    finally:
        page.deleteLater()


def test_outdated_install_shows_the_changelog_button(app, monkeypatch) -> None:
    import biracki_odbor.gui.about_page as about_page_mod

    monkeypatch.setattr(about_page_mod, "__version__", "0.1.0")
    page = about_page_mod.AboutPage()
    try:
        assert page._cl_entries  # noqa: SLF001
        assert page.btn_changelog.isVisibleTo(page)
    finally:
        page.deleteLater()


# ── _merge_changelog / _load_cached_changelog ─────────────────────────
# Server-hosted changelog (fetched best-effort, cached to disk) lets
# copy be corrected/expanded post-release without a client update.


def test_merge_changelog_remote_wins_on_version_collision() -> None:
    local = [("0.73.1", "28.7.2026.", ["stale local bullet"])]
    remote = [("0.73.1", "28.7.2026.", ["corrected server bullet"])]
    result = _merge_changelog(local, remote)
    assert result == [("0.73.1", "28.7.2026.", ["corrected server bullet"])]


def test_merge_changelog_keeps_local_only_versions() -> None:
    local = [("0.60.0", "7.7.2026.", ["a"])]
    remote = [("0.74.0", "1.8.2026.", ["b"])]
    result = _merge_changelog(local, remote)
    versions = [v for v, _, _ in result]
    assert versions == ["0.74.0", "0.60.0"]  # newest-first


def test_merge_changelog_empty_remote_returns_local_unchanged() -> None:
    local = [("0.73.1", "28.7.2026.", ["a"]), ("0.60.0", "7.7.2026.", ["b"])]
    assert _merge_changelog(local, []) == local


def test_load_cached_changelog_missing_file_returns_empty(tmp_path) -> None:
    assert _load_cached_changelog(tmp_path / "nope.json") == []


def test_load_cached_changelog_corrupt_json_returns_empty(tmp_path) -> None:
    p = tmp_path / "changelog.json"
    p.write_text("not json at all", encoding="utf-8")
    assert _load_cached_changelog(p) == []


def test_load_cached_changelog_valid_file_parses_entries(tmp_path) -> None:
    p = tmp_path / "changelog.json"
    p.write_text(json.dumps({
        "entries": [{"version": "0.74.0", "date": "1.8.2026.", "bullets": ["x", "y"]}],
    }), encoding="utf-8")
    assert _load_cached_changelog(p) == [("0.74.0", "1.8.2026.", ["x", "y"])]


# ── AboutPage integration: cached-on-init + background refresh ───────


def test_about_page_picks_up_cached_remote_entry_on_init(app, monkeypatch) -> None:
    """A previously-cached server entry newer than the running version
    must show up immediately, before any network round-trip."""
    import biracki_odbor.gui.about_page as about_page_mod
    from biracki_odbor import app_paths

    latest = about_page_mod._CHANGELOG[0][0]
    monkeypatch.setattr(about_page_mod, "__version__", latest)
    app_paths.changelog_cache_path().write_text(json.dumps({
        "entries": [{"version": "9.9.9", "date": "1.8.2026.", "bullets": ["ново"]}],
    }), encoding="utf-8")

    page = about_page_mod.AboutPage()
    try:
        assert page._cl_entries == [("9.9.9", "1.8.2026.", ["ново"])]  # noqa: SLF001
        assert page.btn_changelog.isVisibleTo(page)
    finally:
        page.deleteLater()


def test_refresh_changelog_from_server_noop_without_state(app) -> None:
    """No AppState (as in every other test here) -> no server URL to
    call -> must not attempt any network I/O."""
    import biracki_odbor.gui.about_page as about_page_mod

    page = about_page_mod.AboutPage()
    try:
        assert page._changelog_worker is None  # noqa: SLF001
    finally:
        page.deleteLater()


def test_on_changelog_fetched_updates_ui_and_writes_cache(app, monkeypatch) -> None:
    import biracki_odbor.gui.about_page as about_page_mod
    from biracki_odbor import app_paths

    latest = about_page_mod._CHANGELOG[0][0]
    monkeypatch.setattr(about_page_mod, "__version__", latest)
    page = about_page_mod.AboutPage()
    try:
        assert page._cl_entries == []  # noqa: SLF001 — up to date before fetch

        page._on_changelog_fetched([  # noqa: SLF001
            ("9.9.9", "1.8.2026.", ["Нова функција"]),
        ])

        assert page._cl_entries == [("9.9.9", "1.8.2026.", ["Нова функција"])]  # noqa: SLF001
        assert page.btn_changelog.isVisibleTo(page)
        cached = json.loads(app_paths.changelog_cache_path().read_text(encoding="utf-8"))
        assert cached["entries"][0]["version"] == "9.9.9"
    finally:
        page.deleteLater()


def test_on_changelog_fetch_failed_does_not_raise(app) -> None:
    import biracki_odbor.gui.about_page as about_page_mod

    page = about_page_mod.AboutPage()
    try:
        page._on_changelog_fetch_failed("network_error: timeout")  # noqa: SLF001 — must not raise
    finally:
        page.deleteLater()
