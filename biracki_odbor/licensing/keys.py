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

# Release signing (updates). Separate from the licence key on purpose:
# the licence key lives on the server, this one only in GitHub CI
# (secret RELEASE_SIGNING_KEY), so a compromised server can't sign an
# update. See biracki_odbor/release_manifest.py. Rotate the same way:
# ship the new public key first, keep the old one listed.
RELEASE_PUBLIC_KEYS: tuple[str, ...] = (
    "eYbjq/o1Frb+0jV+7COokQLnhUkQJV5qRK/FCJaioNQ=",  # 2026-10-27
)
