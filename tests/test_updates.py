"""Tests for biracki_odbor.updates — version comparison + opt-out behavior."""

from __future__ import annotations

import time

import pytest

from biracki_odbor import _release_info, updates


def _pump(predicate, timeout: float = 15.0) -> None:
    """Process Qt events until predicate() is True or timeout elapses.

    Used to drive the real QThread + QTimer polling in the checker
    classes end-to-end (not mocked) — regression coverage for the
    2026-07-11 fix where these classes emitted signals directly from
    the worker thread instead of polling, which packaged builds were
    observed to silently drop.

    15s (not 5s): the underlying poll fires every 200ms and the mocked
    fetch_latest() returns instantly, so the normal case resolves in
    well under a second regardless of this ceiling — it only matters
    when CI is under enough load that the QThread/QTimer doesn't get
    scheduled promptly. Seen timing out at 5s on a slow/contended CI
    runner (~18 min full-suite run vs. ~10 min locally) even though
    the same test passes instantly in isolation every time.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {predicate}")
        app.processEvents()
        time.sleep(0.01)


@pytest.mark.parametrize(
    "latest, current, expected",
    [
        ("v0.2.0", "0.1.0", True),
        ("0.2.0", "v0.1.0", True),
        ("v1.0.0", "v1.0.0", False),
        ("v1.0.0", "v1.0.1", False),
        ("v1.2.0", "v1.1.99", True),
        ("v1.0.0", "v1.0.0-rc1", True),   # final beats prerelease
        ("v1.0.0-rc2", "v1.0.0-rc1", True),
        ("v1.0.0-rc1", "v1.0.0", False),
        ("garbage", "0.1.0", False),       # unparseable → 0.0.0 → not newer
    ],
)
def test_is_newer(latest, current, expected) -> None:
    assert updates.is_newer(latest, current) is expected


def test_disabled_when_repo_empty(monkeypatch) -> None:
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", None)
    assert updates._feed_url() is None
    # fetch_latest must return None silently
    assert updates.fetch_latest() is None


def test_feed_url_uses_github(monkeypatch) -> None:
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", None)
    url = updates._feed_url()
    assert url == "https://api.github.com/repos/owner/repo/releases/latest"


def test_feed_url_override(monkeypatch) -> None:
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", "https://example.com/feed.json")
    url = updates._feed_url()
    assert url == "https://example.com/feed.json"


def test_fetch_returns_none_on_network_error(monkeypatch) -> None:
    """Network failures must never bubble up — silent skip is the contract."""
    import urllib.error
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")

    def boom(*_a, **_kw):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    assert updates.fetch_latest() is None


def test_fetch_extracts_setup_exe_asset(monkeypatch) -> None:
    """fetch_latest() uses the Setup.exe asset URL as a direct download when present."""
    import io
    import json

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", None)
    monkeypatch.setattr(updates, "__version__", "0.1.0", raising=False)

    payload = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/owner/repo/releases/tag/v0.2.0",
        "body": "notes",
        "assets": [
            {"name": "OIK_Setup.exe", "browser_download_url": "https://github.com/owner/repo/releases/download/v0.2.0/OIK_Setup.exe"},
            {"name": "OIK.exe", "browser_download_url": "https://github.com/owner/repo/releases/download/v0.2.0/OIK.exe"},
        ],
    }

    class _FakeResp:
        headers = {"Content-Length": "0"}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return json.dumps(payload).encode()

    # json.load reads from the response object — patch urlopen to return FakeResp
    import contextlib
    @contextlib.contextmanager
    def fake_urlopen(*_a, **_kw):
        class _R:
            headers = type("H", (), {"get": staticmethod(lambda k, d=None: d)})()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        yield _R()

    # Patch json.load inside the module to return our payload
    original_json_load = updates.json.load
    monkeypatch.setattr(updates.json, "load", lambda _resp: payload)
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())

    info = updates.fetch_latest()
    assert info is not None
    assert info.latest == "v0.2.0"
    assert info.is_direct is True
    assert info.url.endswith("OIK_Setup.exe")


def test_fetch_falls_back_to_html_url_when_no_setup_asset(monkeypatch) -> None:
    """When no _Setup.exe asset exists, url falls back to html_url and is_direct=False."""
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", None)
    monkeypatch.setattr(updates, "__version__", "0.1.0", raising=False)

    payload = {
        "tag_name": "v0.2.0",
        "html_url": "https://github.com/owner/repo/releases/tag/v0.2.0",
        "body": "",
        "assets": [],
    }

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *_): pass

    monkeypatch.setattr(updates.json, "load", lambda _resp: payload)
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **kw: _FakeResp())
    info = updates.fetch_latest()
    assert info is not None
    assert info.is_direct is False
    assert info.url == "https://github.com/owner/repo/releases/tag/v0.2.0"


# ── Checker classes: real QThread + QTimer polling, end to end ─────────
#
# Regression coverage for 2026-07-11: these classes used to emit signals
# directly from inside run() on the worker thread (moveToThread pattern).
# Packaged builds silently dropped those signals even though the call
# completed correctly — DownloadWorker and gui/worker.py's Worker had the
# identical bug, fixed earlier in the same session. These tests exercise
# the real QThread + QTimer poll, not a mock, so a regression back to
# direct cross-thread emit() would still pass (Qt handles it fine
# in-process) — the point is confirming the poll-based contract works,
# not proving the old pattern is broken (that needs a packaged build).


def test_manual_checker_emits_update_info(monkeypatch) -> None:
    info = updates.UpdateInfo(current="0.1.0", latest="0.2.0", url="https://x/y.exe", is_direct=True)
    monkeypatch.setattr(updates, "fetch_latest_result", lambda: updates.FetchResult(info=info))

    checker = updates.manual_check_for_update()
    received = []
    checker.finished.connect(received.append)

    _pump(lambda: len(received) == 1)
    assert received[0] is info


def test_manual_checker_emits_none_when_no_update(monkeypatch) -> None:
    monkeypatch.setattr(updates, "fetch_latest_result", lambda: updates.FetchResult())

    checker = updates.manual_check_for_update()
    received = []
    checker.finished.connect(received.append)

    _pump(lambda: len(received) == 1)
    assert received[0] is None


def test_update_checker_only_emits_on_real_update(monkeypatch) -> None:
    info = updates.UpdateInfo(current="0.1.0", latest="0.2.0", url="https://x/y.exe")
    monkeypatch.setattr(updates, "fetch_latest", lambda: info)
    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(_release_info, "UPDATE_FEED_URL", None)

    checker = updates.UpdateChecker()
    received = []
    checker.update_available.connect(received.append)
    checker.start()

    _pump(lambda: len(received) == 1)
    assert received[0] is info


def test_licensed_manual_checker_status_text_on_up_to_date(monkeypatch) -> None:
    from biracki_odbor.licensing import server_client

    result = server_client.UpdateCheckResult(ok=True, latest_version="0.1.0")
    monkeypatch.setattr(server_client, "check_update", lambda *a, **kw: result)
    monkeypatch.setattr(updates, "__version__", "0.1.0", raising=False)

    checker = updates.LicensedManualChecker("https://x", "token")
    statuses: list[str] = []
    finished: list[object] = []
    checker.status_text.connect(statuses.append)
    checker.finished.connect(finished.append)
    checker.start()

    _pump(lambda: statuses or finished)
    assert statuses == ["Имате најновију верзију."]
    assert finished == []


def test_licensed_manual_checker_emits_update_when_newer(monkeypatch) -> None:
    from biracki_odbor.licensing import server_client

    result = server_client.UpdateCheckResult(
        ok=True, latest_version="0.9.0", download_url="https://x/setup.exe",
    )
    monkeypatch.setattr(server_client, "check_update", lambda *a, **kw: result)
    monkeypatch.setattr(updates, "__version__", "0.1.0", raising=False)

    checker = updates.LicensedManualChecker("https://x", "token")
    finished: list[object] = []
    checker.finished.connect(finished.append)
    checker.start()

    _pump(lambda: len(finished) == 1)
    assert finished[0].latest == "0.9.0"
    assert finished[0].is_direct is True


def test_licensed_manual_checker_network_error_shows_status(monkeypatch) -> None:
    from biracki_odbor.licensing import server_client

    def boom(*_a, **_kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(server_client, "check_update", boom)

    checker = updates.LicensedManualChecker("https://x", "token")
    statuses: list[str] = []
    checker.status_text.connect(statuses.append)
    checker.start()

    _pump(lambda: len(statuses) == 1)
    assert "интернет" in statuses[0].lower() or "није успела" in statuses[0].lower()


def test_licensed_update_checker_emits_updates_expired(monkeypatch) -> None:
    from biracki_odbor.licensing import server_client

    result = server_client.UpdateCheckResult(ok=False, reason="updates_expired", expired_on="2026-01-01")
    monkeypatch.setattr(server_client, "check_update", lambda *a, **kw: result)

    checker = updates.LicensedUpdateChecker("https://x", "token")
    expired: list[str] = []
    checker.updates_expired.connect(expired.append)
    checker.start()

    _pump(lambda: len(expired) == 1)
    assert expired[0] == "2026-01-01"


# ── TLS trust anchor ─────────────────────────────────────────────────
#
# The field failure this guards: the update check (httpx, certifi) said a
# new version existed while the download (bare urllib, Windows cert
# store) failed CERTIFICATE_VERIFY_FAILED against the same host in the
# same session, because api.isoft.rs's ISRG Root X2 chain reaches Windows
# only via the root-certificate sync service, stale on municipal PCs.


class _FakeResponse:
    def __init__(self, payload: bytes = b"") -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}
        self._read = False

    def read(self, _n: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def test_the_download_uses_a_verifying_context(monkeypatch, tmp_path) -> None:
    """The actual fix: without context= urlopen falls back to the Windows
    certificate store, which is what rejected the server in the field."""
    import ssl

    captured = {}

    def fake_urlopen(_req, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(b"MZ")

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    worker = updates.DownloadWorker("https://api.isoft.rs/downloads/v1/OIK_Setup.exe")
    worker.run()

    assert worker.error is None, worker.error
    assert isinstance(captured.get("context"), ssl.SSLContext)
    assert captured["context"].verify_mode is ssl.CERT_REQUIRED
    assert captured["context"].check_hostname is True


def test_the_check_uses_a_verifying_context(monkeypatch) -> None:
    import json
    import ssl

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    captured = {}

    def fake_urlopen(_req, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(json.dumps({"tag_name": "v999.0.0"}).encode())

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    updates.fetch_latest_result()

    assert isinstance(captured.get("context"), ssl.SSLContext)
    assert captured["context"].verify_mode is ssl.CERT_REQUIRED


def test_a_wrapped_certificate_error_is_classified_as_tls(monkeypatch) -> None:
    """urlopen does not raise ssl.SSLError directly — it wraps it in a
    URLError whose .reason is the SSL error. That wrapped shape is what
    actually occurs, so missing it leaves the whole diagnostic dead."""
    import ssl
    import urllib.error

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")

    def boom(*_a, **_kw):
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")
        )

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)

    result = updates.fetch_latest_result()

    assert result.error_kind == "tls", "a cert failure must not be reported as a network error"
    assert result.info is None


def test_a_bare_certificate_error_is_classified_as_tls(monkeypatch) -> None:
    import ssl

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")

    def boom(*_a, **_kw):
        raise ssl.SSLCertVerificationError(1, "certificate verify failed")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)

    assert updates.fetch_latest_result().error_kind == "tls"


def test_a_plain_network_error_is_not_mistaken_for_tls(monkeypatch) -> None:
    import urllib.error

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")

    def boom(*_a, **_kw):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)

    assert updates.fetch_latest_result().error_kind == "network"


def test_being_up_to_date_is_distinguishable_from_a_failed_check(monkeypatch) -> None:
    """The whole point of FetchResult: 'no update' and 'could not ask'
    used to be the same bare None, so a certificate failure displayed as
    'you have the latest version'."""
    import json

    monkeypatch.setattr(_release_info, "GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(
        updates.urllib.request, "urlopen",
        lambda *_a, **_kw: _FakeResponse(json.dumps({"tag_name": "v0.0.1"}).encode()),
    )

    result = updates.fetch_latest_result()

    assert result.info is None
    assert result.error_kind == ""  # genuinely up to date


def test_a_download_certificate_failure_is_tagged_for_the_gui(monkeypatch) -> None:
    import ssl

    def boom(*_a, **_kw):
        raise ssl.SSLCertVerificationError(1, "certificate verify failed")

    monkeypatch.setattr(updates.urllib.request, "urlopen", boom)
    worker = updates.DownloadWorker("https://api.isoft.rs/x.exe")
    worker.run()

    assert worker.error is not None
    assert worker.error.startswith(updates.TLS_ERROR_MARKER)


def test_the_manual_check_reports_a_certificate_failure_instead_of_silence(monkeypatch) -> None:
    """A failed check must not emit finished(None): the About page shows
    that as "you have the latest version", which is precisely how a
    certificate failure went unnoticed in the field."""
    monkeypatch.setattr(
        updates, "fetch_latest_result",
        lambda: updates.FetchResult(error_kind="tls", detail="certificate has expired"),
    )

    checker = updates.manual_check_for_update()
    finished, statuses = [], []
    checker.finished.connect(finished.append)
    checker.status_text.connect(statuses.append)

    _pump(lambda: len(statuses) == 1)

    assert finished == [], "a failed check must not look like 'up to date'"
    assert "сертификат" in statuses[0].lower()


def test_the_manual_check_reports_a_network_failure_distinctly(monkeypatch) -> None:
    monkeypatch.setattr(
        updates, "fetch_latest_result",
        lambda: updates.FetchResult(error_kind="network", detail="unreachable"),
    )

    checker = updates.manual_check_for_update()
    finished, statuses = [], []
    checker.finished.connect(finished.append)
    checker.status_text.connect(statuses.append)

    _pump(lambda: len(statuses) == 1)

    assert finished == []
    assert "интернет" in statuses[0].lower()
