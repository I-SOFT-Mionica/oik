"""HTTP wrapper around the I-SOFT license server endpoints.

Two operations:

  - `activate(server_url, license_code, hid)` →  saves the returned
    JWT to `license_dat_path()` and returns it. Called by the
    Activation dialog on first launch.
  - `check_update(server_url, token, current_version)` → consults
    the server for the latest available version; respects
    `updates_until`. Called by the in-app updater when
    licensing_server_url is set.

Network failures and 4xx/5xx responses are wrapped in `LicenseError`
with a human-friendly `reason_code` the GUI maps to a Cyrillic
message. No retry — the operator decides whether to retry from the
dialog. Timeouts are short (10 s) so a flaky network doesn't freeze
the app indefinitely.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx


log = logging.getLogger(__name__)


_TIMEOUT_SECONDS = 10.0


@dataclass
class LicenseError(RuntimeError):
    """Raised by activate / check_update on any failure.

    `reason_code` is a stable string the GUI maps to a translated
    message. `detail` is a one-liner safe to show to the operator
    (no stack traces, no internal IDs).
    """

    reason_code: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover — debug only
        return f"{self.reason_code}: {self.detail}"


@dataclass
class ActivateResult:
    token: str


@dataclass
class UpdateCheckResult:
    """Returned by `check_update`.

    `ok=True` means the server accepted the token AND there's
    something available to download (might be the same version the
    client already has — that's the GUI's call). `ok=False` means
    the server explicitly refused (expired updates / revoked /
    machine mismatch); the GUI shows the renewal banner.
    """

    ok: bool
    latest_version: str = ""
    download_url: str = ""
    release_notes: str = ""
    reason: str = ""           # "updates_expired" / "revoked" / ...
    expired_on: str = ""       # ISO date when reason == updates_expired
    token: str = ""            # re-issued Ed25519 token for an HS256 install


def activate(
    server_url: str,
    license_code: str,
    hid: str,
    *,
    client: httpx.Client | None = None,
) -> ActivateResult:
    """POST /api/v1/biracki/activate.

    `client` is for tests — production callers pass None and we
    construct an httpx.Client with our timeout. Tests inject a
    pre-configured client with a mock transport.
    """
    url = _join(server_url, "/api/v1/biracki/activate")
    payload = {"license_code": license_code, "hid": hid}
    try:
        resp = _post(url, payload, client=client)
    except httpx.RequestError as e:
        raise LicenseError("network_error", str(e)) from e

    if resp.status_code == 200:
        data = resp.json()
        token = data.get("token", "")
        if not token:
            raise LicenseError(
                "bad_response", "Сервер није вратио токен"
            )
        return ActivateResult(token=token)

    raise _error_from_response(resp)


def fetch_changelog(
    server_url: str, *, client: httpx.Client | None = None,
) -> list[tuple[str, str, list[str]]]:
    """GET /downloads/changelog.json — public, unauthenticated.

    Returns (version, date, bullets) tuples, newest first — same shape
    as about_page.py's built-in `_CHANGELOG` list, which it's merged
    with (server entries win on version collision, letting copy be
    corrected/expanded post-release without a client update).

    Best-effort "what's new" content only, never a license-critical
    path: raises `LicenseError` on network/HTTP/shape failure so the
    caller can fall back to the last cached copy or the built-in list
    rather than surfacing an error to the operator.
    """
    url = _join(server_url, "/downloads/changelog.json")
    try:
        resp = _get(url, client=client)
    except httpx.RequestError as e:
        raise LicenseError("network_error", str(e)) from e

    if resp.status_code != 200:
        raise _error_from_response(resp)

    try:
        raw = resp.json()["entries"]
        return [
            (str(e["version"]), str(e["date"]), [str(b) for b in e["bullets"]])
            for e in raw
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise LicenseError("bad_response", f"Неисправан формат changelog.json: {e}") from e


@dataclass
class ReleaseManifest:
    """What `/downloads/latest.json` advertises.

    One manifest per server, not per product: it names the current tag
    and the OIK installer built from it. The companion Formalizator
    installer is published alongside under the same tag, so its URL is
    derived from this one rather than announced separately (see
    integrations.formalizator_app.installer_url).
    """

    tag: str
    download_url: str = ""


def fetch_release_manifest(
    server_url: str, *, client: httpx.Client | None = None,
) -> ReleaseManifest:
    """GET /downloads/latest.json — public, unauthenticated.

    Used to find the current release tag without a license token, which
    the Formalizator tab needs: it offers a companion-app download to
    every operator, licensed or not.
    """
    url = _join(server_url, "/downloads/latest.json")
    try:
        resp = _get(url, client=client)
    except httpx.RequestError as e:
        raise LicenseError("network_error", str(e)) from e

    if resp.status_code != 200:
        raise _error_from_response(resp)

    try:
        data = resp.json()
        tag = str(data["tag"]).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise LicenseError("bad_response", f"Неисправан формат latest.json: {e}") from e
    if not tag:
        raise LicenseError("bad_response", "latest.json не садржи ознаку издања.")
    return ReleaseManifest(tag=tag, download_url=str(data.get("download_url") or ""))


def check_update(
    server_url: str,
    token: str,
    current_version: str,
    *,
    client: httpx.Client | None = None,
) -> UpdateCheckResult:
    """POST /api/v1/biracki/check-update.

    On success returns the latest-version info (the GUI compares
    against `current_version` to decide whether to surface an
    update prompt). On rejection returns ok=False with `reason`
    populated so the GUI can show the right Cyrillic message.

    `LicenseError` is raised only for transport / 5xx — these
    are the cases where "try again later" is the right operator
    response.
    """
    url = _join(server_url, "/api/v1/biracki/check-update")
    payload = {"token": token, "current_version": current_version}
    try:
        resp = _post(url, payload, client=client)
    except httpx.RequestError as e:
        raise LicenseError("network_error", str(e)) from e

    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok"):
            return UpdateCheckResult(
                ok=True,
                latest_version=str(data.get("latest_version") or ""),
                download_url=str(data.get("download_url") or ""),
                release_notes=str(data.get("release_notes") or ""),
                token=str(data.get("token") or ""),
            )
        return UpdateCheckResult(
            ok=False,
            reason=str(data.get("reason") or "unknown"),
            expired_on=str(data.get("expired_on") or ""),
            token=str(data.get("token") or ""),
        )

    raise _error_from_response(resp)


# ── Internals ──────────────────────────────────────────────────────


def _join(server_url: str, path: str) -> str:
    """Concatenate server URL + path, tolerating trailing slashes."""
    base = server_url.rstrip("/")
    suffix = path if path.startswith("/") else "/" + path
    return base + suffix


def _post(
    url: str, payload: dict[str, Any], *, client: httpx.Client | None,
) -> httpx.Response:
    if client is not None:
        return client.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as c:
        return c.post(url, json=payload)


def _get(url: str, *, client: httpx.Client | None) -> httpx.Response:
    if client is not None:
        return client.get(url, timeout=_TIMEOUT_SECONDS)
    with httpx.Client(timeout=_TIMEOUT_SECONDS) as c:
        return c.get(url)


def _error_from_response(resp: httpx.Response) -> LicenseError:
    """Translate a non-2xx response into a LicenseError the GUI can
    show. The server returns `{"error": "machine_mismatch", ...}` on
    expected refusals; we surface that string as `reason_code`.
    """
    try:
        data = resp.json()
        reason_code = str(data.get("error") or f"http_{resp.status_code}")
        detail = str(data.get("detail") or data.get("message") or "")
    except (ValueError, json.JSONDecodeError):
        reason_code = f"http_{resp.status_code}"
        detail = (resp.text or "")[:200]
    return LicenseError(reason_code=reason_code, detail=detail)
