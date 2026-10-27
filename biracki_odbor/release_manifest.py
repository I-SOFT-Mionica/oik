"""Signed release manifests — the updater runs nothing it can't verify.

Every release build writes `release-manifest.json` next to its
installers: the tag plus each installer's SHA-256 and size, signed with
the release key (Ed25519). The private key exists only as a GitHub
Actions secret (RELEASE_SIGNING_KEY); the matching public key is in
`licensing/keys.py`. The update server merely stores the file, so even a
fully compromised server -- or a broken TLS connection -- can't get an
installer past `verify_download()`.

Manifest format (one file, signature included):

    {"tag": "v0.103.0",
     "files": {"OIK_Setup.exe": {"sha256": "<hex>", "size": 213818937}, ...},
     "signature": "<base64 Ed25519 over canonical(tag, files)>"}
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MANIFEST_NAME = "release-manifest.json"


class ManifestError(ValueError):
    """The manifest or the downloaded file can't be trusted."""


@dataclass(frozen=True)
class FileEntry:
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    tag: str
    files: dict[str, FileEntry]


def _canonical(tag: str, files: dict[str, dict]) -> bytes:
    return json.dumps(
        {"tag": tag, "files": files}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _norm_tag(tag: str) -> str:
    return tag.strip().lstrip("vV")


def build(tag: str, paths: list[Path], private_seed_b64: str) -> dict:
    """Manifest for `paths`, signed. Used by tools/sign_release.py in CI."""
    files = {}
    for p in paths:
        data = Path(p).read_bytes()
        files[Path(p).name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_seed_b64))
    sig = key.sign(_canonical(tag, files))
    return {"tag": tag, "files": files, "signature": base64.b64encode(sig).decode("ascii")}


def parse(raw: bytes, public_keys: tuple[str, ...] | None = None) -> Manifest:
    """Check the signature against an accepted release key and return
    the contents. Raises ManifestError for anything else."""
    from biracki_odbor.licensing import keys

    try:
        doc = json.loads(raw.decode("utf-8"))
        tag = str(doc["tag"])
        files = doc["files"]
        signature = base64.b64decode(doc["signature"], validate=True)
        if not isinstance(files, dict):
            raise TypeError("files is not an object")
    except (ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"malformed manifest: {exc}") from exc

    message = _canonical(tag, files)
    accepted = public_keys if public_keys is not None else keys.RELEASE_PUBLIC_KEYS
    for key in accepted:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(signature, message)
            break
        except InvalidSignature:
            continue
    else:
        raise ManifestError("manifest signature does not match any release key")

    try:
        entries = {
            name: FileEntry(sha256=str(e["sha256"]).lower(), size=int(e["size"]))
            for name, e in files.items()
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"malformed file entry: {exc}") from exc
    return Manifest(tag=tag, files=entries)


def verify_download(
    manifest: Manifest, filename: str, path: Path, expected_tag: str | None = None,
) -> None:
    """Raise ManifestError unless `path` is exactly the `filename` this
    signed release lists (and, when given, the release is `expected_tag`
    -- so an old genuine installer can't be passed off as the new one)."""
    if expected_tag and _norm_tag(manifest.tag) != _norm_tag(expected_tag):
        raise ManifestError(f"manifest is for {manifest.tag}, expected {expected_tag}")
    entry = manifest.files.get(filename)
    if entry is None:
        raise ManifestError(f"{filename} is not part of release {manifest.tag}")
    size = Path(path).stat().st_size
    if size != entry.size:
        raise ManifestError(f"{filename}: size {size} != {entry.size}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != entry.sha256:
        raise ManifestError(f"{filename}: SHA-256 does not match the signed manifest")
