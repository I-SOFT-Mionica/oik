"""Tests for the Алати → Formalizator tab.

The behaviour that matters is mostly about what the tab must *not* do:
not quit OIK after launching the companion installer, not show a raw
HTTP code when the installer is not on the server yet, and not claim an
install it cannot start.
"""

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


def _page(app, monkeypatch, install=None):
    from biracki_odbor.gui.app_state import AppState
    from biracki_odbor.gui.tabs import formalizator_tool
    from biracki_odbor.integrations import formalizator_app

    monkeypatch.setattr(formalizator_app, "find_install", lambda: install)
    return formalizator_tool.FormalizatorPage(AppState())


def _fake_install(tmp_path: Path):
    from biracki_odbor.integrations.formalizator_app import FormalizatorInstall

    exe = tmp_path / "Formalizator" / "Formalizator.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    return FormalizatorInstall(exe=exe, base_dir=exe.parent, version="1.2.3", source="registry")


def test_an_installed_app_offers_to_start_it(app, monkeypatch, tmp_path) -> None:
    page = _page(app, monkeypatch, _fake_install(tmp_path))
    try:
        assert "1.2.3" in page.lbl_status.text()
        assert page.btn_install.text() != page.btn_launch.text()
    finally:
        page.deleteLater()


def test_a_missing_app_offers_the_download_and_says_how_big(app, monkeypatch) -> None:
    """200 MB over a municipal connection is worth warning about before
    the operator starts it, not after."""
    page = _page(app, monkeypatch, None)
    try:
        assert "MB" in page.lbl_status.text()
    finally:
        page.deleteLater()


def test_starting_uses_the_launcher_with_the_located_executable(
    app, monkeypatch, tmp_path,
) -> None:
    from biracki_odbor.integrations import formalizator_app

    install = _fake_install(tmp_path)
    page = _page(app, monkeypatch, install)
    launched = []
    monkeypatch.setattr(formalizator_app, "launch", launched.append)
    try:
        page.btn_launch.click()

        assert launched == [install]
    finally:
        page.deleteLater()


def test_a_failure_to_start_is_reported_not_swallowed(app, monkeypatch, tmp_path) -> None:
    from biracki_odbor.integrations import formalizator_app

    page = _page(app, monkeypatch, _fake_install(tmp_path))

    def boom(_install):
        raise OSError("access denied")

    monkeypatch.setattr(formalizator_app, "launch", boom)
    try:
        page.btn_launch.click()

        assert "access denied" in page.lbl_status.text()
    finally:
        page.deleteLater()


def test_finishing_a_download_never_quits_oik(app, monkeypatch, tmp_path) -> None:
    """The one line deliberately not copied from the About page's update
    flow. OIK quits for its own installer because that installer
    replaces the running exe; Formalizator's writes elsewhere entirely,
    and quitting would drop whatever the operator had open."""
    from PySide6.QtWidgets import QApplication

    from biracki_odbor.gui.tabs import formalizator_tool

    page = _page(app, monkeypatch, None)
    started = []
    monkeypatch.setattr(formalizator_tool.subprocess, "Popen", started.append)
    quit_called = []
    monkeypatch.setattr(QApplication, "quit", lambda *_a: quit_called.append(True))
    try:
        installer = tmp_path / "Formalizator_Setup.exe"
        installer.write_bytes(b"MZ")

        page._on_finished(str(installer))  # noqa: SLF001

        assert started == [[str(installer)]], "the installer must actually be launched"
        assert quit_called == [], "OIK must keep running"
    finally:
        page.deleteLater()


def test_a_missing_installer_on_the_server_reads_as_a_sentence(app, monkeypatch) -> None:
    """404 is the expected answer until the companion installer is
    published server-side, so it must not surface as an HTTP code."""
    page = _page(app, monkeypatch, None)
    try:
        message = page._humanise("HTTP Error 404: Not Found")  # noqa: SLF001

        assert "404" not in message
        assert "support" in message.lower() or "подршк" in message.lower()
    finally:
        page.deleteLater()


def test_a_certificate_failure_points_at_the_diagnostics(app, monkeypatch) -> None:
    from biracki_odbor.updates import TLS_ERROR_MARKER

    page = _page(app, monkeypatch, None)
    try:
        message = page._humanise(f"{TLS_ERROR_MARKER}certificate verify failed")  # noqa: SLF001

        assert "certificate" in message.lower() or "сертификат" in message.lower()
    finally:
        page.deleteLater()


def test_a_build_without_a_server_says_so_instead_of_failing(app, monkeypatch) -> None:
    """Dev builds bake in no server URL; pressing the button must explain
    that rather than attempt an empty URL."""
    page = _page(app, monkeypatch, None)
    monkeypatch.setattr(page, "_server_url", lambda: "")
    try:
        page.btn_install.click()

        assert "server" in page.lbl_status.text().lower()
        assert page.btn_install.isEnabled()
    finally:
        page.deleteLater()


def test_a_lookup_failure_leaves_the_buttons_usable(app, monkeypatch) -> None:
    """A failed attempt must not strand the operator with dead buttons."""
    from biracki_odbor.licensing import server_client

    page = _page(app, monkeypatch, None)
    monkeypatch.setattr(page, "_server_url", lambda: "https://api.isoft.rs")

    def boom(_url):
        raise server_client.LicenseError("network_error", "unreachable")

    monkeypatch.setattr(server_client, "fetch_release_manifest", boom)
    try:
        page.btn_install.click()

        assert page.btn_install.isEnabled()
        assert page.lbl_status.text()
    finally:
        page.deleteLater()
