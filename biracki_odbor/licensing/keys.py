"""Public keys that may sign licence tokens (Ed25519, base64 of the raw
32 bytes). Verification is entirely local, so a licensed install keeps
working with no server at all -- licences are perpetual by design.

To rotate: add the new key here in a release, switch the server's
JWT_SIGNING_KEY, and keep the old key listed so tokens it signed still
verify. The matching private key lives only in the licensing server's
environment (JWT_SIGNING_KEY).
"""

ACCEPTED_PUBLIC_KEYS: tuple[str, ...] = (
    "PIIeGvCL5YTux1R7hPz0aqicQvN36se+d4LcCz2Y7pk=",  # 2026-10-16
)
