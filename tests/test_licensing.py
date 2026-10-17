"""Licensing client tests.

Pins:
  - HID computation is stable + non-empty across calls.
  - Token decoding accepts a real JWT-shaped string AND rejects garbage
    without ever raising past the documented error type.
  - load_license correctly identifies DISABLED / LICENSED / DEMO and
    populates `reason` for each demo path.
  - server_client speaks the agreed shape: posts JSON, returns
    ActivateResult / UpdateCheckResult, surfaces server-side errors
    as LicenseError with the right reason_code.

Server is fully mocked via httpx's MockTransport — no network. The
shape pinned here is the contract the I-SOFT license server has to
satisfy.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from biracki_odbor.licensing import hid, server_client
from biracki_odbor.licensing.state import License, Mode, load_license
from biracki_odbor.licensing.token import (
    TokenDecodeError, decode_token_payload,
)


def _make_token(payload: dict) -> str:
    """Build a fake JWT-shaped string. Header + signature are dummy
    bytes — we don't verify them in the client."""
    header_b64 = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(b"dummysig").rstrip(b"=").decode()
    return f"{header_b64}.{payload_b64}.{sig_b64}"


# ── HID ────────────────────────────────────────────────────────────


def test_compute_hid_returns_64_char_hex() -> None:
    """Output shape must be SHA-256 hex — that's what the server
    schema expects (`hid VARCHAR(64)`)."""
    h = hid.compute_hid()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h), (
        f"HID must be lowercase hex; got {h!r}"
    )


def test_compute_hid_is_deterministic_per_call() -> None:
    """Same machine, two calls → same HID. The license server stores
    the HID at activation and compares on every update check; any
    instability here breaks legitimate customers."""
    assert hid.compute_hid() == hid.compute_hid()


# ── Token decode ───────────────────────────────────────────────────


def test_decode_token_round_trip() -> None:
    payload = {
        "sub": "abc-123",
        "license_code": "AAAA-BBBB-CCCC-DDDD",
        "issued_to": "Општина Уб",
        "hid": "ff" * 32,
        "updates_until": "2027-06-02",
        "modules": ["full"],
    }
    token = _make_token(payload)
    out = decode_token_payload(token)
    assert out == payload


@pytest.mark.parametrize("bad", [
    "",
    "not.a.jwt",          # 2 segments
    "a.b.c.d",            # 4 segments
    "a.notbase64$.c",     # bad base64
])
def test_decode_token_rejects_garbage(bad: str) -> None:
    with pytest.raises(TokenDecodeError):
        decode_token_payload(bad)


# ── load_license ───────────────────────────────────────────────────


def test_load_license_disabled_when_url_blank(tmp_path: Path) -> None:
    """Empty licensing_server_url ⇒ Mode.DISABLED — the dev/CI
    default. Skips .dat parsing entirely; the file might not even
    exist."""
    lic = load_license(
        licensing_server_url="",
        license_dat_path=tmp_path / "nonexistent.dat",
    )
    assert lic.mode == Mode.DISABLED
    assert lic.is_full
    assert not lic.is_demo


def test_load_license_demo_when_no_license_file(tmp_path: Path) -> None:
    lic = load_license(
        licensing_server_url="https://license.example.com",
        license_dat_path=tmp_path / "absent.dat",
    )
    assert lic.mode == Mode.DEMO
    assert lic.reason == "no_license_file"
    assert lic.is_demo
    assert lic.machine_hid  # HID is computed even in demo


def test_load_license_demo_on_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.dat"
    path.write_text("not-a-jwt", encoding="utf-8")
    lic = load_license(
        licensing_server_url="https://license.example.com",
        license_dat_path=path,
    )
    assert lic.mode == Mode.DEMO
    assert lic.reason == "license_malformed"


def test_load_license_demo_on_machine_mismatch(tmp_path: Path) -> None:
    """Token has a HID that doesn't match the current machine —
    treated as DEMO with reason=machine_mismatch. Don't expose the
    full token contents in the reason; GUI gets just the flag."""
    other_hid = "00" * 32
    token = _make_token({
        "sub": "license-1",
        "license_code": "AAAA-BBBB-CCCC-DDDD",
        "issued_to": "Општина Други",
        "hid": other_hid,
        "updates_until": "2027-06-02",
        "modules": ["full"],
    })
    path = tmp_path / "license.dat"
    path.write_text(token, encoding="utf-8")
    lic = load_license(
        licensing_server_url="https://license.example.com",
        license_dat_path=path,
    )
    assert lic.mode == Mode.DEMO
    assert lic.reason == "machine_mismatch"
    # The original issued_to passes through so the GUI can say
    # "license is for X, this machine is Y".
    assert lic.issued_to == "Општина Други"


def test_load_license_licensed_when_hid_matches(tmp_path: Path) -> None:
    """Happy path: token's HID matches the local machine → LICENSED.

    We bake the actual `compute_hid()` value into the token so the
    match works on this exact runner without monkey-patching the HID
    function. That's also what production looks like — server stamps
    the HID into the JWT at activation time.
    """
    my_hid = hid.compute_hid()
    payload = {
        "sub": "license-1",
        "license_code": "AAAA-BBBB-CCCC-DDDD",
        "issued_to": "Општина Уб",
        "hid": my_hid,
        "updates_until": "2027-06-02",
        "modules": ["full"],
        "issued_at": "2026-06-02",
    }
    path = tmp_path / "license.dat"
    path.write_text(_make_token(payload), encoding="utf-8")
    lic = load_license(
        licensing_server_url="https://license.example.com",
        license_dat_path=path,
    )
    assert lic.mode == Mode.LICENSED
    assert lic.issued_to == "Општина Уб"
    assert lic.license_code == "AAAA-BBBB-CCCC-DDDD"
    assert lic.updates_until == "2027-06-02"
    assert lic.modules == ["full"]
    assert lic.machine_hid == my_hid
    assert lic.is_full
    assert not lic.is_demo


# ── server_client.activate ─────────────────────────────────────────


def _mock_client(handler):
    """Wrap a request-handler callable into an httpx.Client backed by
    MockTransport so the test asserts on the JSON we POSTed."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def test_activate_happy_path() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json={"token": "the-real-jwt"})

    client = _mock_client(handler)
    result = server_client.activate(
        "https://license.example.com",
        "AAAA-BBBB-CCCC-DDDD",
        "ff" * 32,
        client=client,
    )
    assert result.token == "the-real-jwt"
    assert captured["url"] == "https://license.example.com/api/v1/biracki/activate"
    assert captured["body"] == {
        "license_code": "AAAA-BBBB-CCCC-DDDD",
        "hid": "ff" * 32,
    }


def test_activate_machine_mismatch_raises_with_reason_code() -> None:
    """Server 403 + error=machine_mismatch → LicenseError with
    reason_code='machine_mismatch'. The activation dialog maps that
    to a Cyrillic message; if we strip the code, the dialog falls
    back to a generic message."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={
            "error": "machine_mismatch",
            "issued_to": "Општина Други",
        })

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.activate(
            "https://license.example.com", "X", "ff" * 32, client=client,
        )
    assert exc.value.reason_code == "machine_mismatch"


def test_activate_unknown_license_raises_with_reason_code() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "unknown_license"})

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.activate(
            "https://license.example.com", "X", "ff" * 32, client=client,
        )
    assert exc.value.reason_code == "unknown_license"


def test_activate_network_error_wraps_as_license_error() -> None:
    """A transport-level failure (timeout / DNS / connection refused)
    must surface as LicenseError(reason_code='network_error') so the
    dialog can show 'check your internet' rather than crashing."""
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.activate(
            "https://license.example.com", "X", "ff" * 32, client=client,
        )
    assert exc.value.reason_code == "network_error"


# ── server_client.check_update ─────────────────────────────────────


def test_check_update_ok_returns_latest_version() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode("utf-8"))
        assert body["token"] == "the-jwt"
        assert body["current_version"] == "v0.12.0"
        return httpx.Response(200, json={
            "ok": True,
            "latest_version": "v0.13.0",
            "download_url": "https://license.example.com/dl/v0.13.0",
            "release_notes": "bugfixes",
        })

    client = _mock_client(handler)
    result = server_client.check_update(
        "https://license.example.com", "the-jwt", "v0.12.0", client=client,
    )
    assert result.ok
    assert result.latest_version == "v0.13.0"
    assert result.download_url.endswith("/dl/v0.13.0")


def test_check_update_expired_subscription_returns_ok_false() -> None:
    """`updates_expired` is a HAPPY 200 response with ok=False — NOT
    a LicenseError. The GUI uses this to switch from 'update
    available' to 'renew subscription' messaging."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "ok": False,
            "reason": "updates_expired",
            "expired_on": "2027-06-02",
        })

    client = _mock_client(handler)
    result = server_client.check_update(
        "https://license.example.com", "the-jwt", "v0.12.0", client=client,
    )
    assert not result.ok
    assert result.reason == "updates_expired"
    assert result.expired_on == "2027-06-02"


# ── server_client.fetch_changelog ──────────────────────────────────


def test_fetch_changelog_happy_path() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://license.example.com/downloads/changelog.json"
        return httpx.Response(200, json={"entries": [
            {"version": "0.74.0", "date": "1.8.2026.", "bullets": ["a", "b"]},
        ]})

    client = _mock_client(handler)
    result = server_client.fetch_changelog("https://license.example.com", client=client)
    assert result == [("0.74.0", "1.8.2026.", ["a", "b"])]


def test_fetch_changelog_bad_shape_raises_bad_response() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_entries": []})

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.fetch_changelog("https://license.example.com", client=client)
    assert exc.value.reason_code == "bad_response"


def test_fetch_changelog_http_error_raises_license_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server_error"})

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.fetch_changelog("https://license.example.com", client=client)
    assert exc.value.reason_code == "server_error"


def test_fetch_changelog_network_error_wraps_as_license_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _mock_client(handler)
    with pytest.raises(server_client.LicenseError) as exc:
        server_client.fetch_changelog("https://license.example.com", client=client)
    assert exc.value.reason_code == "network_error"


# ── Phase 1 demo cap ───────────────────────────────────────────────


def test_phase1_demo_mode_limits_to_one_bm(tmp_path) -> None:
    """generate_party_files with demo_mode=True must restrict the
    output to a single BM. The GUI sets this flag based on
    state.license.is_demo so an unlicensed install can't generate
    a 50-BM template."""
    from biracki_odbor.core.phase1_generate import generate_party_files
    from biracki_odbor.validation.reports import Codes
    from tests.fixtures.stalni_sastav import build_template
    from tests.test_phase1 import _make_oik

    template = build_template(
        tmp_path / "t.xlsx", n_polling_stations=5, parties=("СНС", "СПС"),
    )
    out = tmp_path / "stranke"
    result = generate_party_files(
        template, out, _make_oik(5), demo_mode=True,
    )
    assert result.report.ok, [i.message_sr for i in result.report.issues]

    # An info-level DEMO_MODE_LIMIT must surface in the report so the
    # GUI can echo "demo: ограничено на БМ 1".
    demo_issues = [
        i for i in result.report.issues if i.code == Codes.DEMO_MODE_LIMIT
    ]
    assert len(demo_issues) == 1
    assert demo_issues[0].row == 1  # lowest bm_number

    # Inspect one of the generated files — it should have rows only
    # for BM 1, not 5. The template has 6 slots per BM; demo mode
    # → exactly 6 data rows per party.
    import openpyxl
    sample = sorted(result.files_written)[0]
    wb = openpyxl.load_workbook(sample)
    ws = wb.active
    bm_numbers_seen: set[int] = set()
    for row in ws.iter_rows(min_row=4, values_only=True):
        if not row or row[1] is None:
            continue
        try:
            bm_numbers_seen.add(int(row[1]))
        except (TypeError, ValueError):
            continue
    wb.close()
    assert bm_numbers_seen == {1}, (
        f"Demo mode must restrict to a single BM; saw {sorted(bm_numbers_seen)}"
    )


# ── Release manifest (public, unauthenticated) ───────────────────────
#
# Used by the Алати → Formalizator tab to find the current release tag
# without a license token: the companion app is offered to every
# operator, licensed or not.


def test_fetch_release_manifest_happy_path() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://license.example.com/downloads/latest.json"
        return httpx.Response(200, json={
            "tag": "v0.82.1",
            "sha256": "abc",
            "size_bytes": 211239854,
            "download_url": "https://license.example.com/downloads/v0.82.1/OIK_Setup.exe",
        })

    manifest = server_client.fetch_release_manifest(
        "https://license.example.com", client=_mock_client(handler),
    )

    assert manifest.tag == "v0.82.1"
    assert manifest.download_url.endswith("OIK_Setup.exe")


def test_fetch_release_manifest_tolerates_a_missing_download_url() -> None:
    """The tag alone is enough — the companion installer's URL can be
    built from it."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tag": "v1.0.0"})

    manifest = server_client.fetch_release_manifest(
        "https://license.example.com", client=_mock_client(handler),
    )

    assert manifest.tag == "v1.0.0"
    assert manifest.download_url == ""


def test_fetch_release_manifest_rejects_a_manifest_with_no_tag() -> None:
    """Without a tag there is nothing to build a download URL from, so
    this must fail loudly rather than yield an empty address."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"download_url": "https://x/y.exe"})

    with pytest.raises(server_client.LicenseError) as excinfo:
        server_client.fetch_release_manifest(
            "https://license.example.com", client=_mock_client(handler),
        )

    assert excinfo.value.reason_code == "bad_response"


def test_fetch_release_manifest_reports_a_network_failure() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    with pytest.raises(server_client.LicenseError) as excinfo:
        server_client.fetch_release_manifest(
            "https://license.example.com", client=_mock_client(handler),
        )

    assert excinfo.value.reason_code == "network_error"
