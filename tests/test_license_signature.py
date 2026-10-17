"""Ed25519 licence tokens: a licence verifies offline against the public
key built into the app, a forged or tampered license.dat drops to demo
mode, pre-switch HS256 tokens keep working, and the re-issued token the
server sends at an update check replaces license.dat (only if it
verifies and is for this machine).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from biracki_odbor.licensing import hid, keys
from biracki_odbor.licensing.state import Mode, load_license, save_refreshed_token
from biracki_odbor.licensing.token import TokenSignatureError, verify_token
from biracki_odbor.updates import LicensedManualChecker, LicensedUpdateChecker

URL = "https://license.example.com"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def _payload(**over) -> dict:
    return {
        "sub": "license-1",
        "license_code": "AAAA-BBBB-CCCC-DDDD",
        "issued_to": "Општина Уб",
        "hid": hid.compute_hid(),
        "updates_until": "2027-06-02",
        "modules": ["full"],
        "issued_at": "2026-10-16",
    } | over


def _eddsa(key: Ed25519PrivateKey, payload: dict) -> str:
    """A JWT signed exactly as PyJWT's EdDSA does it on the server."""
    head = _b64(b'{"alg":"EdDSA","typ":"JWT"}')
    body = _b64(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sig = key.sign(f"{head}.{body}".encode("ascii"))
    return f"{head}.{body}.{_b64(sig)}"


def _hs256(payload: dict) -> str:
    head = _b64(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return f"{head}.{body}.{_b64(b'server-only-hmac')}"


@pytest.fixture
def server_key(monkeypatch) -> Ed25519PrivateKey:
    """The app trusts this key instead of the production one."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "ACCEPTED_PUBLIC_KEYS", (_public_b64(key),))
    return key


def _load(tmp_path: Path, token: str):
    path = tmp_path / "license.dat"
    path.write_text(token, encoding="utf-8")
    return load_license(licensing_server_url=URL, license_dat_path=path)


# ── loading license.dat ────────────────────────────────────────────

def test_signed_licence_is_licensed_offline(tmp_path, server_key) -> None:
    lic = _load(tmp_path, _eddsa(server_key, _payload()))
    assert lic.mode == Mode.LICENSED
    assert lic.issued_to == "Општина Уб"
    assert not lic.legacy_token


def test_edited_licence_falls_to_demo(tmp_path, server_key) -> None:
    """Changing anything in a signed token (here: extending updates)
    breaks the signature."""
    head, _, sig = _eddsa(server_key, _payload()).split(".")
    body = _b64(json.dumps(_payload(updates_until="2099-01-01")).encode())
    lic = _load(tmp_path, f"{head}.{body}.{sig}")
    assert lic.mode == Mode.DEMO
    assert lic.reason == "license_invalid_signature"


def test_licence_signed_by_someone_else_falls_to_demo(tmp_path, server_key) -> None:
    lic = _load(tmp_path, _eddsa(Ed25519PrivateKey.generate(), _payload()))
    assert lic.mode == Mode.DEMO
    assert lic.reason == "license_invalid_signature"


def test_unknown_algorithm_is_rejected(server_key) -> None:
    head = _b64(b'{"alg":"none","typ":"JWT"}')
    body = _b64(json.dumps(_payload()).encode())
    with pytest.raises(TokenSignatureError):
        verify_token(f"{head}.{body}.")


def test_pre_switch_hs256_licence_still_works(tmp_path, server_key) -> None:
    lic = _load(tmp_path, _hs256(_payload()))
    assert lic.mode == Mode.LICENSED
    assert lic.legacy_token


def test_production_key_is_a_valid_ed25519_key() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    assert keys.ACCEPTED_PUBLIC_KEYS
    for k in keys.ACCEPTED_PUBLIC_KEYS:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(k))


# ── adopting the re-issued token ───────────────────────────────────

def test_refreshed_token_replaces_legacy_licence(tmp_path, server_key) -> None:
    path = tmp_path / "license.dat"
    path.write_text(_hs256(_payload()), encoding="utf-8")
    new = _eddsa(server_key, _payload())
    assert save_refreshed_token(path, new)
    assert path.read_text(encoding="utf-8") == new
    lic = load_license(licensing_server_url=URL, license_dat_path=path)
    assert lic.mode == Mode.LICENSED and not lic.legacy_token


@pytest.mark.parametrize("bad", [
    "forged", "other_machine", "legacy", "garbage",
])
def test_unverifiable_refresh_never_overwrites_licence(tmp_path, server_key, bad) -> None:
    path = tmp_path / "license.dat"
    original = _hs256(_payload())
    path.write_text(original, encoding="utf-8")
    token = {
        "forged": _eddsa(Ed25519PrivateKey.generate(), _payload()),
        "other_machine": _eddsa(server_key, _payload(hid="f" * 64)),
        "legacy": _hs256(_payload(updates_until="2099-01-01")),
        "garbage": "not-a-token",
    }[bad]
    assert not save_refreshed_token(path, token)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("checker_cls", [LicensedUpdateChecker, LicensedManualChecker])
@pytest.mark.parametrize("ok,reason", [(True, ""), (False, "updates_expired")])
def test_update_check_saves_token_and_signals_reload(
    _qapp_session, tmp_path, monkeypatch, server_key, checker_cls, ok, reason,
) -> None:
    """Both the startup check and the About-page button adopt the token,
    including for licences whose update window has ended."""
    path = tmp_path / "license.dat"
    path.write_text(_hs256(_payload()), encoding="utf-8")
    from biracki_odbor import app_paths
    monkeypatch.setattr(app_paths, "license_dat_path", lambda: path)

    new = _eddsa(server_key, _payload())
    result = SimpleNamespace(
        ok=ok, reason=reason, expired_on="2026-01-01", latest_version="",
        download_url="", release_notes="", token=new,
    )
    checker = checker_cls(URL, "old")
    reloads = []
    checker.token_refreshed.connect(lambda: reloads.append(1))
    checker._handle_result(SimpleNamespace(error=None, result=result))

    assert reloads == [1]
    assert path.read_text(encoding="utf-8") == new


def test_update_check_without_token_leaves_licence_alone(_qapp_session, tmp_path, monkeypatch) -> None:
    path = tmp_path / "license.dat"
    path.write_text("unchanged", encoding="utf-8")
    from biracki_odbor import app_paths
    monkeypatch.setattr(app_paths, "license_dat_path", lambda: path)
    checker = LicensedUpdateChecker(URL, "old")
    reloads = []
    checker.token_refreshed.connect(lambda: reloads.append(1))
    result = SimpleNamespace(ok=True, reason="", latest_version="", download_url="",
                             release_notes="", expired_on="", token="")
    checker._handle_result(SimpleNamespace(error=None, result=result))
    assert reloads == [] and path.read_text(encoding="utf-8") == "unchanged"
