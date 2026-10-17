"""In-app update checker.

Calls the GitHub Releases API on a background thread, compares the
latest tag against the running version, and surfaces a non-modal notice
when a newer release exists.

Design choices for the 60+ user audience:
  - Never blocks the GUI: runs in a QThread, fails silently on network errors.
  - Opt-out by setting `update_check.enabled = false` in oik_constants.json
    (or by clearing `_release_info.GITHUB_REPO`).
  - Doesn't auto-download or auto-install. Operator clicks a link to the
    GitHub Release page in their browser. They keep control.
  - No telemetry — only the GitHub URL is hit, with no identifying headers.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from biracki_odbor import __version__, _release_info
from biracki_odbor.ssl_support import create_ssl_context


log = logging.getLogger(__name__)

USER_AGENT = f"biracki-odbor/{__version__}"

# DownloadWorker.run() names every temp file with this prefix regardless
# of which product it's downloading (OIK's own installer or Formalizator's)
# -- it's just a unique-name prefix, not a product label.
_INSTALLER_TEMP_PREFIX = "OIK_Setup_"


def cleanup_stale_installer_downloads() -> None:
    """Delete leftover `OIK_Setup_*.exe` temp files from earlier runs.

    DownloadWorker.run() downloads straight to a fresh mkstemp() file and
    the GUI launches it with subprocess.Popen() -- but never deletes it
    afterwards (about_page.py quits OIK shortly after launching its own
    update installer, so there's no later point in that run to clean up
    from; formalizator_tool.py's install never touches it either). Left
    alone, every single update check/retry leaves another ~200MB behind
    forever. Confirmed in the field: 54 accumulated copies after repeated
    retries in one day.

    Called right before starting a new download so retries don't keep
    piling up. A file still locked by an installer that's genuinely
    still running fails to delete and is silently skipped -- it'll be
    swept on the next call instead."""
    import os
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.gettempdir())
    for p in tmp.glob(f"{_INSTALLER_TEMP_PREFIX}*.exe"):
        try:
            os.unlink(p)
        except OSError:
            pass


TIMEOUT_SECONDS = 5

# Prefix on DownloadWorker.error when the transfer failed TLS verification,
# so the GUI can name the cause rather than print an OpenSSL string.
TLS_ERROR_MARKER = "[TLS] "


@dataclass
class UpdateInfo:
    current: str
    latest: str
    url: str
    body: str = ""
    is_direct: bool = False  # True = url is a direct installer (.exe) download


# ── Version comparison ────────────────────────────────────────────

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.+))?$")


def _parse(v: str) -> tuple[int, int, int, str]:
    """Lenient semver-ish parse. Unparseable → (0,0,0,''). Prerelease
    component sorts BEFORE no-prerelease at the same numeric version."""
    m = _VERSION_RE.match(v.strip())
    if not m:
        return (0, 0, 0, "")
    major = int(m.group(1) or 0)
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    pre = m.group(4) or ""
    return (major, minor, patch, pre)


def is_newer(latest: str, current: str) -> bool:
    """True iff latest > current under our lenient ordering."""
    lt = _parse(latest)
    cu = _parse(current)
    # Compare numeric triple first
    if lt[:3] != cu[:3]:
        return lt[:3] > cu[:3]
    # Numeric tied. No-prerelease beats prerelease (e.g. 1.0.0 > 1.0.0-rc1)
    if not lt[3] and cu[3]:
        return True
    if lt[3] and not cu[3]:
        return False
    return lt[3] > cu[3]


# ── Network ───────────────────────────────────────────────────────

def _feed_url() -> Optional[str]:
    if _release_info.UPDATE_FEED_URL:
        return _release_info.UPDATE_FEED_URL
    if _release_info.GITHUB_REPO:
        return f"https://api.github.com/repos/{_release_info.GITHUB_REPO}/releases/latest"
    return None


def _is_tls_failure(exc: BaseException) -> bool:
    """True for a certificate/TLS error, including the wrapped form.

    `urlopen` does not raise `ssl.SSLError` directly — it wraps it in a
    `urllib.error.URLError` whose `.reason` is the SSL error. That
    wrapped shape is the one that actually occurs in the field, so
    missing it would leave the whole diagnostic dead.
    """
    if isinstance(exc, ssl.SSLError):
        return True
    return isinstance(getattr(exc, "reason", None), ssl.SSLError)


@dataclass
class FetchResult:
    """Why a check produced no update — "up to date" and "we could not
    ask" used to be the same answer (a bare None), which is how a
    certificate failure spent months looking like "you have the latest
    version"."""

    info: UpdateInfo | None = None
    error_kind: str = ""  # "" | "tls" | "network" | "bad_response"
    detail: str = ""


def fetch_latest_result() -> FetchResult:
    """Blocking fetch — call from a worker thread, not the GUI thread."""
    url = _feed_url()
    if not url:
        return FetchResult()
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(  # noqa: S310 — https feed URL, verified context
            req, timeout=TIMEOUT_SECONDS, context=create_ssl_context(),
        ) as resp:
            data = json.load(resp)
    # Order matters, and not obviously: ssl.SSLCertVerificationError
    # inherits from SSLError, OSError *and* ValueError, so it matches
    # every arm below. It has to be caught first or a certificate
    # failure is filed as a malformed response or a network blip —
    # which is the exact class of bug this function exists to end.
    except ssl.SSLError as exc:
        log.warning("update check: TLS failure against %s: %s", url, exc)
        return FetchResult(error_kind="tls", detail=str(exc))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # urlopen wraps the SSL error rather than raising it directly.
        if _is_tls_failure(exc):
            log.warning("update check: TLS failure against %s: %s", url, exc)
            return FetchResult(error_kind="tls", detail=str(exc))
        log.info("update check: network failure against %s: %s", url, exc)
        return FetchResult(error_kind="network", detail=str(exc))
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("update check: malformed response from %s: %s", url, exc)
        return FetchResult(error_kind="bad_response", detail=str(exc))

    latest_tag = data.get("tag_name") or data.get("name")
    html_url = data.get("html_url", "")
    body = data.get("body", "") or ""
    if not latest_tag:
        return FetchResult(error_kind="bad_response", detail="no tag in response")
    if not is_newer(latest_tag, __version__):
        return FetchResult()  # genuinely up to date
    installer_url = ""
    for asset in data.get("assets", []):
        if str(asset.get("name", "")).endswith("_Setup.exe"):
            installer_url = asset.get("browser_download_url", "")
            break
    return FetchResult(info=UpdateInfo(
        current=__version__, latest=latest_tag,
        url=installer_url or html_url, body=body,
        is_direct=bool(installer_url),
    ))


def fetch_latest() -> Optional[UpdateInfo]:
    """Back-compat shim: an UpdateInfo, or None for any other outcome.

    Callers that need to tell "up to date" from "could not check" want
    `fetch_latest_result()` instead.
    """
    return fetch_latest_result().info


# ── Qt worker ─────────────────────────────────────────────────────
#
# All four checkers below share one pattern: run a blocking call() on a
# QThread, expose its result/error as plain attributes, and let a
# main-thread QTimer poll for completion — NOT cross-thread Signal.emit()
# from inside run(). Packaged (PyInstaller) builds have been observed to
# silently drop signals emitted from a QThread even though the call
# completed correctly underneath (confirmed via DownloadWorker and
# gui/worker.py's Worker earlier); these four update-checkers used the
# old moveToThread()+emit() pattern too and were never fixed alongside
# those — this closes that gap (2026-07-11).


class _BlockingCallWorker(QThread):
    """Runs a zero-arg blocking callable on a background thread.

    `result` / `error` are polled from the GUI thread via a QTimer once
    `isRunning()` goes False (thread-safe to call from any thread).
    """

    def __init__(self, fn, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self.result: object = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.result = self._fn()
        except Exception as exc:  # noqa: BLE001 — network / server errors
            self.error = str(exc)


def _poll_call(
    worker: _BlockingCallWorker, parent: QObject, on_done,
) -> QTimer:
    """Poll `worker` every 200ms; call on_done(worker) once, on the GUI
    thread, as soon as it finishes. Caller must keep the returned QTimer
    referenced (e.g. as an attribute) for the duration of the poll."""
    timer = QTimer(parent)
    timer.setInterval(200)

    def _tick() -> None:
        if worker.isRunning():
            return
        timer.stop()
        on_done(worker)

    timer.timeout.connect(_tick)
    timer.start()
    return timer


class UpdateChecker(QObject):
    """Background update poll. Emits `update_available` exactly once on success.

    Usage:
        self._checker = UpdateChecker(self)
        self._checker.update_available.connect(self._on_update)
        self._checker.start()
    """

    update_available = Signal(object)  # UpdateInfo

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: _BlockingCallWorker | None = None
        self._timer: QTimer | None = None

    def start(self) -> None:
        if _feed_url() is None:
            return  # disabled
        self._worker = _BlockingCallWorker(fetch_latest, self)
        self._worker.start()
        self._timer = _poll_call(self._worker, self, self._handle_result)

    def _handle_result(self, worker: _BlockingCallWorker) -> None:
        info = worker.result
        if isinstance(info, UpdateInfo):
            self.update_available.emit(info)


# ── Manual on-demand check (used by the About page) ────────────────


class _ManualChecker(QObject):
    """One-shot worker that always emits a result — UpdateInfo or None.

    Different from `UpdateChecker` (which only fires when an update is
    actually available) because the on-demand caller wants to distinguish
    "up to date" from "network failure" from "newer release exists".
    """

    finished = Signal(object)  # UpdateInfo | None
    # Emitted instead of `finished` when the check could not be made at
    # all. Without this a certificate failure arrived as `finished(None)`
    # and was displayed as "you have the latest version".
    status_text = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: _BlockingCallWorker | None = None
        self._timer: QTimer | None = None

    def start(self) -> None:
        self._worker = _BlockingCallWorker(fetch_latest_result, self)
        self._worker.start()
        self._timer = _poll_call(self._worker, self, self._handle_result)

    def _handle_result(self, worker: _BlockingCallWorker) -> None:
        result = worker.result
        if not isinstance(result, FetchResult):
            self.finished.emit(None)
            return
        if result.error_kind == "tls":
            self.status_text.emit(
                "Провера није успела — сертификат сервера није прихваћен"
                " на овом рачунару. Преузмите инсталацију ручно."
            )
            return
        if result.error_kind:
            self.status_text.emit("Провера није успела. Проверите интернет везу.")
            return
        self.finished.emit(result.info)


def manual_check_for_update(parent: QObject | None = None) -> _ManualChecker:
    """Start an on-demand update check. Connect to `finished(info)`.

    Returns the checker so callers can keep it alive (parent it to a widget).
    `info` is an `UpdateInfo` if a newer release exists, otherwise None.
    """
    checker = _ManualChecker(parent)
    checker.start()
    return checker


def _adopt_refreshed_token(checker: QObject, result) -> None:
    """Save a re-issued (Ed25519) licence token from /check-update and
    tell the app to reload the licence. Verified before it is written."""
    token = getattr(result, "token", "")
    if not token:
        return
    from biracki_odbor import app_paths
    from biracki_odbor.licensing.state import save_refreshed_token
    if save_refreshed_token(app_paths.license_dat_path(), token):
        checker.token_refreshed.emit()


# ── Licensed manual check (server-gated, one-shot) ───────────────────


class LicensedManualChecker(QObject):
    """On-demand update check that hits the licensing server, not GitHub.

    Used by the «Провери ажурирање» button when the app is in LICENSED
    mode. Mirrors _ManualChecker's contract but routes through the JWT-
    authenticated /check-update endpoint so the server can honour the
    updates_until window and serve the locally-hosted installer URL.

    Signals:
      finished(UpdateInfo | None) — update available, or None (no update)
      status_text(str)            — human-readable message for all other
                                    outcomes (up to date, expired, network error)
      token_refreshed()           — license.dat was replaced by a re-issued token
    """

    finished = Signal(object)    # UpdateInfo when newer version available
    status_text = Signal(str)    # for up-to-date / expired / error outcomes
    token_refreshed = Signal()

    def __init__(
        self, server_url: str, token: str, parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_url = server_url
        self._token = token
        self._worker: _BlockingCallWorker | None = None
        self._timer: QTimer | None = None

    def start(self) -> None:
        from biracki_odbor.licensing import server_client

        def _call():
            return server_client.check_update(self._server_url, self._token, __version__)

        self._worker = _BlockingCallWorker(_call, self)
        self._worker.start()
        self._timer = _poll_call(self._worker, self, self._handle_result)

    def _handle_result(self, worker: _BlockingCallWorker) -> None:
        if worker.error is not None:
            self.status_text.emit("Провера није успела. Проверите интернет везу.")
            return

        r = worker.result
        _adopt_refreshed_token(self, r)
        if not r.ok:
            if r.reason == "updates_expired":
                self.status_text.emit(
                    f"Ажурирања истекла ({r.expired_on}). Контактирајте подршку за обнову."
                )
            else:
                self.status_text.emit("Имате најновију верзију.")
            return

        if r.latest_version and is_newer(r.latest_version, __version__):
            self.finished.emit(UpdateInfo(
                current=__version__,
                latest=r.latest_version,
                url=r.download_url or "",
                body=r.release_notes or "",
                is_direct=bool(r.download_url),
            ))
        else:
            self.status_text.emit("Имате најновију верзију.")


# ── Licensed (server-gated) variant ─────────────────────────────────


class LicensedUpdateChecker(QObject):
    """Update checker that hits the licensing server instead of GitHub.

    Used when the app is in LICENSED mode (licensing_server_url is
    set AND a valid license.dat exists). The server checks the
    token's `updates_until` field before deciding what to return —
    customers past their updates window get no offer + the GUI shows
    "renew subscription" instead of an update prompt.

    Emits exactly one of:
      - `update_available(UpdateInfo)` — newer version available + URL
      - `updates_expired(str expired_on)` — server refused; renewal needed
      - nothing (transient network failure or no newer version)

    Mirrors `UpdateChecker`'s "fail silently" contract so a flaky
    network doesn't pop modals at startup.
    """

    update_available = Signal(object)  # UpdateInfo
    updates_expired = Signal(str)      # "YYYY-MM-DD" expired_on
    token_refreshed = Signal()         # license.dat replaced by a re-issued token

    def __init__(
        self,
        server_url: str,
        token: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_url = server_url
        self._token = token
        self._worker: _BlockingCallWorker | None = None
        self._timer: QTimer | None = None

    def start(self) -> None:
        if not (self._server_url and self._token):
            return
        from biracki_odbor.licensing import server_client

        def _call():
            return server_client.check_update(self._server_url, self._token, __version__)

        self._worker = _BlockingCallWorker(_call, self)
        self._worker.start()
        self._timer = _poll_call(self._worker, self, self._handle_result)

    def _handle_result(self, worker: _BlockingCallWorker) -> None:
        if worker.error is not None:
            # Silent failure — same contract as the GitHub path. The
            # user can manually retry via the About page.
            return

        result = worker.result
        _adopt_refreshed_token(self, result)
        if not result.ok:
            if result.reason == "updates_expired":
                self.updates_expired.emit(result.expired_on)
            return

        if result.latest_version and is_newer(result.latest_version, __version__):
            self.update_available.emit(UpdateInfo(
                current=__version__,
                latest=result.latest_version,
                url=result.download_url,
                body=result.release_notes,
                is_direct=bool(result.download_url),
            ))


# ── Installer download worker ────────────────────────────────────────


class DownloadWorker(QThread):
    """Downloads a URL to a local temp file.

    Progress and terminal state are exposed as plain attributes
    (`bytes_downloaded`, `bytes_total`, `error`, `result_path`), meant to
    be polled from a QTimer on the GUI thread — NOT via cross-thread
    `Signal.emit()`. On the packaged (PyInstaller) build, signals emitted
    from this thread were observed to be silently dropped: the download
    completed correctly on disk (verified via the resulting temp file)
    but the connected GUI slot never fired, even once. Reading/writing a
    single attribute is atomic under the GIL, so no lock is needed.
    Callers should poll `isRunning()` (thread-safe) to detect completion,
    then check `error` vs `result_path`.
    """

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self.bytes_downloaded = 0
        self.bytes_total = 0
        self.error: str | None = None
        self.result_path: str | None = None

    def run(self) -> None:
        import os
        import tempfile
        log.info("DownloadWorker.run() starting: %s", self._url)
        try:
            req = urllib.request.Request(self._url, headers={"User-Agent": USER_AGENT})
            log.debug("DownloadWorker: opening connection")
            # context= is the whole fix: without it urlopen verifies
            # against the Windows certificate store, which on a municipal
            # PC with stale root updates rejects api.isoft.rs's ISRG Root
            # X2 chain — while the httpx-based check of the same host in
            # the same session succeeds on certifi. See ssl_support.
            with urllib.request.urlopen(  # noqa: S310 — https installer URL, verified context
                req, timeout=120, context=create_ssl_context(),
            ) as resp:
                self.bytes_total = int(resp.headers.get("Content-Length") or 0)
                log.info("DownloadWorker: connected, content-length=%d", self.bytes_total)
                fd, path = tempfile.mkstemp(suffix=".exe", prefix="OIK_Setup_")
                try:
                    with os.fdopen(fd, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            self.bytes_downloaded += len(chunk)
                except Exception:
                    log.exception(
                        "DownloadWorker: failed mid-transfer at %d bytes", self.bytes_downloaded,
                    )
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                    raise
            log.info("DownloadWorker: finished, %d bytes -> %s", self.bytes_downloaded, path)
            self.result_path = path
        except Exception as exc:
            log.exception("DownloadWorker: failed before/opening connection")
            # Tag TLS failures so the GUI can explain the cause and the
            # workaround instead of showing a raw OpenSSL string.
            self.error = f"{TLS_ERROR_MARKER}{exc}" if _is_tls_failure(exc) else str(exc)
