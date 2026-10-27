"""The updater runs only installers that match a manifest signed with
the release key -- whatever the server or the network hands it."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from biracki_odbor import release_manifest, updates
from biracki_odbor.licensing import keys

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = b"MZ genuine installer bytes" * 1000
URL = "https://api.isoft.rs/downloads/v0.103.0/OIK_Setup.exe"


def _seed(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                            serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def _pub(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


@pytest.fixture
def release_key(monkeypatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "RELEASE_PUBLIC_KEYS", (_pub(key),))
    return key


def _manifest(tmp_path, key, tag="v0.103.0", content=INSTALLER) -> bytes:
    f = tmp_path / "OIK_Setup.exe"
    f.write_bytes(content)
    return json.dumps(release_manifest.build(tag, [f], _seed(key))).encode()


# ── manifest itself ───────────────────────────────────────────────

def test_production_release_key_is_a_valid_ed25519_key() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    assert keys.RELEASE_PUBLIC_KEYS
    assert set(keys.RELEASE_PUBLIC_KEYS).isdisjoint(keys.ACCEPTED_PUBLIC_KEYS), \
        "release key must not be the licence key"
    for k in keys.RELEASE_PUBLIC_KEYS:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(k))


def test_signed_manifest_verifies_and_matches_the_file(tmp_path, release_key) -> None:
    m = release_manifest.parse(_manifest(tmp_path, release_key))
    release_manifest.verify_download(m, "OIK_Setup.exe", tmp_path / "OIK_Setup.exe", "0.103.0")


def test_editing_the_manifest_breaks_the_signature(tmp_path, release_key) -> None:
    doc = json.loads(_manifest(tmp_path, release_key))
    doc["files"]["OIK_Setup.exe"]["sha256"] = "0" * 64
    with pytest.raises(release_manifest.ManifestError, match="signature"):
        release_manifest.parse(json.dumps(doc).encode())


def test_manifest_signed_with_another_key_is_rejected(tmp_path, release_key) -> None:
    with pytest.raises(release_manifest.ManifestError, match="signature"):
        release_manifest.parse(_manifest(tmp_path, Ed25519PrivateKey.generate()))


def test_licence_key_cannot_sign_releases(tmp_path, release_key, monkeypatch) -> None:
    """A stolen licence-server key must not be able to sign an update."""
    licence_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(keys, "ACCEPTED_PUBLIC_KEYS", (_pub(licence_key),))
    with pytest.raises(release_manifest.ManifestError):
        release_manifest.parse(_manifest(tmp_path, licence_key))


@pytest.mark.parametrize("raw", [b"", b"not json", b'{"tag": "v1"}', b"[]"])
def test_garbage_is_rejected(raw) -> None:
    with pytest.raises(release_manifest.ManifestError):
        release_manifest.parse(raw)


# ── DownloadWorker end to end ─────────────────────────────────────

class _Resp(io.BytesIO):
    def __init__(self, body: bytes, url: str) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _serve(monkeypatch, *, manifest: bytes | None, installer: bytes,
           installer_final_url: str | None = None) -> None:
    def fake_urlopen(req, timeout=None, context=None):
        url = req.full_url
        assert context is not None, "every download must use the verifying TLS context"
        if url.endswith(release_manifest.MANIFEST_NAME):
            if manifest is None:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return _Resp(manifest, url)
        return _Resp(installer, installer_final_url or url)
    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)


def _run(url=URL, tag="v0.103.0") -> updates.DownloadWorker:
    w = updates.DownloadWorker(url, expected_tag=tag)
    w.run()  # synchronously, same code the thread runs
    return w


@pytest.fixture
def tmp_downloads(tmp_path, monkeypatch):
    d = tmp_path / "dl"
    d.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(d))
    return d


def test_genuine_release_is_handed_over(tmp_path, tmp_downloads, release_key, monkeypatch) -> None:
    _serve(monkeypatch, manifest=_manifest(tmp_path, release_key), installer=INSTALLER)
    w = _run()
    assert w.error is None
    assert Path(w.result_path).read_bytes() == INSTALLER


def test_tampered_installer_is_deleted_and_never_run(tmp_path, tmp_downloads, release_key, monkeypatch) -> None:
    _serve(monkeypatch, manifest=_manifest(tmp_path, release_key), installer=INSTALLER[:-4] + b"EVIL")
    w = _run()
    assert w.result_path is None
    assert w.error.startswith(updates.UNVERIFIED_MARKER)
    assert list(tmp_downloads.iterdir()) == [], "the unverified file must not be left behind"


def test_missing_manifest_refuses_the_update(tmp_downloads, release_key, monkeypatch) -> None:
    _serve(monkeypatch, manifest=None, installer=INSTALLER)
    w = _run()
    assert w.result_path is None and w.error.startswith(updates.UNVERIFIED_MARKER)


def test_old_genuine_release_cannot_pose_as_the_new_one(tmp_path, tmp_downloads, release_key, monkeypatch) -> None:
    _serve(monkeypatch, manifest=_manifest(tmp_path, release_key, tag="v0.90.0"), installer=INSTALLER)
    w = _run(tag="v0.103.0")
    assert w.result_path is None and "expected" in w.error


def test_forged_manifest_from_a_compromised_server_is_refused(tmp_path, tmp_downloads, release_key, monkeypatch) -> None:
    evil = b"MZ malware"
    _serve(monkeypatch, manifest=_manifest(tmp_path, Ed25519PrivateKey.generate(), content=evil),
           installer=evil)
    w = _run()
    assert w.result_path is None and w.error.startswith(updates.UNVERIFIED_MARKER)
    assert list(tmp_downloads.iterdir()) == []


def test_plain_http_is_refused_before_connecting(release_key, monkeypatch) -> None:
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("must not connect"))
    w = _run(url="http://api.isoft.rs/downloads/v0.103.0/OIK_Setup.exe")
    assert w.result_path is None and w.error.startswith(updates.UNVERIFIED_MARKER)


def test_redirect_off_https_is_refused(tmp_path, tmp_downloads, release_key, monkeypatch) -> None:
    _serve(monkeypatch, manifest=_manifest(tmp_path, release_key), installer=INSTALLER,
           installer_final_url="http://evil.example/OIK_Setup.exe")
    w = _run()
    assert w.result_path is None and w.error.startswith(updates.UNVERIFIED_MARKER)
    assert list(tmp_downloads.iterdir()) == []


# ── the CI signing tool ───────────────────────────────────────────

def test_sign_release_tool_writes_a_manifest_the_app_accepts(tmp_path, release_key) -> None:
    inst = tmp_path / "OIK_Setup.exe"
    inst.write_bytes(INSTALLER)
    out = tmp_path / release_manifest.MANIFEST_NAME
    env = {**os.environ, "RELEASE_SIGNING_KEY": _seed(release_key)}
    # The tool self-checks against the app's built-in key; point it at
    # the test key the same way the fixture does.
    code = (
        "import sys, runpy; from biracki_odbor.licensing import keys; "
        f"keys.RELEASE_PUBLIC_KEYS = ({_pub(release_key)!r},); "
        f"sys.argv = ['sign_release', '--tag', 'v0.103.0', '--out', {str(out)!r}, {str(inst)!r}]; "
        f"runpy.run_path({str(ROOT / 'tools' / 'sign_release.py')!r}, run_name='__main__')"
    )
    r = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = release_manifest.parse(out.read_bytes())
    release_manifest.verify_download(m, "OIK_Setup.exe", inst, "v0.103.0")


def test_sign_release_tool_fails_without_the_key(tmp_path) -> None:
    inst = tmp_path / "OIK_Setup.exe"
    inst.write_bytes(INSTALLER)
    env = {k: v for k, v in os.environ.items() if k != "RELEASE_SIGNING_KEY"}
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "sign_release.py"), "--tag", "v1",
                        "--out", str(tmp_path / "m.json"), str(inst)],
                       env=env, cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and not (tmp_path / "m.json").exists()
