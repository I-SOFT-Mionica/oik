"""Licence token decoding and verification.

Tokens signed with Ed25519 ("EdDSA") are verified locally against the
public keys in `keys.py` -- no server needed, so a licensed install keeps
working indefinitely. A token whose signature doesn't verify is rejected
(the app runs in demo mode).

Tokens issued before 16 October 2026 are HS256, signed with a secret the
app doesn't hold, so they can't be verified here. They are still
accepted during the transition (flagged `legacy`), and the licensing
server hands each such install a new Ed25519 token at its next update
check (see `state.save_refreshed_token`). Once every licence has
switched, a later release stops accepting HS256.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from biracki_odbor.licensing import keys as _keys


class TokenDecodeError(ValueError):
    """The raw token isn't a parseable JWT payload."""


class TokenSignatureError(TokenDecodeError):
    """The token parses but its signature doesn't verify (or its
    algorithm isn't one this app accepts)."""


@dataclass(frozen=True)
class VerifiedToken:
    payload: dict[str, Any]
    legacy: bool  # HS256 from before the switch: accepted, not verifiable


def verify_token(raw: str, public_keys: tuple[str, ...] | None = None) -> VerifiedToken:
    """Decode `raw` and check its signature. Raises TokenDecodeError /
    TokenSignatureError."""
    payload = decode_token_payload(raw)
    header_b64, payload_b64, sig_b64 = raw.strip().split(".")
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except (binascii.Error, ValueError) as e:
        raise TokenDecodeError(f"header is not JSON: {e}") from e
    alg = header.get("alg") if isinstance(header, dict) else None
    if alg == "HS256":
        return VerifiedToken(payload=payload, legacy=True)
    if alg != "EdDSA":
        raise TokenSignatureError(f"unsupported algorithm: {alg!r}")
    try:
        signature = _b64url_decode(sig_b64)
    except (binascii.Error, ValueError) as e:
        raise TokenSignatureError(f"signature is not base64url: {e}") from e
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    for key in (public_keys if public_keys is not None else _keys.ACCEPTED_PUBLIC_KEYS):
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(signature, signing_input)
            return VerifiedToken(payload=payload, legacy=False)
        except InvalidSignature:
            continue
    raise TokenSignatureError("signature does not match any accepted key")


def decode_token_payload(raw: str) -> dict[str, Any]:
    """Return the decoded JWT payload as a dict. No signature check.

    Raises `TokenDecodeError` on malformed input — caller (state.py)
    treats that as DEMO mode with `reason="license_malformed"`.
    """
    if not raw or not isinstance(raw, str):
        raise TokenDecodeError("empty or non-string token")
    parts = raw.split(".")
    if len(parts) != 3:
        raise TokenDecodeError(
            f"expected 3 JWT segments, got {len(parts)}"
        )
    payload_b64 = parts[1]
    try:
        payload_bytes = _b64url_decode(payload_b64)
    except (binascii.Error, ValueError) as e:
        raise TokenDecodeError(f"base64url decode failed: {e}") from e
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise TokenDecodeError(f"payload is not JSON: {e}") from e
    if not isinstance(payload, dict):
        raise TokenDecodeError("payload is not a JSON object")
    return payload


def _b64url_decode(s: str) -> bytes:
    """Base64url-decode a JWT segment, tolerant of missing padding.

    Standard library's `base64.urlsafe_b64decode` is strict about
    `=` padding; real JWTs omit it. Pad to a length divisible by 4
    before decoding.
    """
    padded = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
