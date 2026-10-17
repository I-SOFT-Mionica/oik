"""Shared TLS trust anchor for the app's raw-urllib HTTPS calls.

Field incident, 2026-08-18 (TODO.md §24): on a municipal PC the update
*check* reported a new version while the *download* failed with
`[SSL: CERTIFICATE_VERIFY_FAILED] ... certificate has expired`. Same
host, same moment, and the identical download succeeded on another
machine. The cause was not the server:

  * the check goes through `httpx`, which verifies against **certifi**'s
    bundled CA snapshot (`httpx/_config.py` does
    `ssl.create_default_context(cafile=certifi.where())`);
  * the download went through bare `urllib.request.urlopen` with no
    `context=`, i.e. the live **Windows certificate store**.

`api.isoft.rs` serves an ECDSA chain rooted at ISRG Root X2, which
reaches a Windows machine only through the root-certificate sync
service — frequently stale or disabled on exactly the locked-down
municipal PCs this app is deployed to. certifi has carried ISRG Root X2
for years, so one call survived and the other did not.

Every raw-urllib HTTPS call therefore goes through `create_ssl_context()`
so the whole app trusts the same anchors httpx already does.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_context: ssl.SSLContext | None = None


@dataclass(frozen=True)
class CaBundleStatus:
    """Which trust store is actually in use — surfaced in the About
    page's diagnostics and in support e-mails, because "which CA store
    did that machine use" is otherwise unanswerable without a remote
    session."""

    source: str   # "certifi" | "system"
    path: str     # cacert.pem location; "" when source == "system"
    version: str  # certifi.__version__; "" when unavailable
    detail: str   # why the fallback happened, when source == "system"

    @property
    def is_bundled(self) -> bool:
        return self.source == "certifi"


def ca_bundle_status() -> CaBundleStatus:
    """Report the trust store without building a context."""
    try:
        import certifi
    except ImportError as exc:  # pragma: no cover — certifi ships with httpx
        return CaBundleStatus("system", "", "", f"certifi not importable: {exc}")

    version = str(getattr(certifi, "__version__", ""))
    try:
        path = Path(certifi.where())
    except Exception as exc:  # noqa: BLE001 — a broken install must not crash the About page
        return CaBundleStatus("system", "", version, f"certifi.where() failed: {exc}")

    if not path.is_file():
        # The frozen build lost cacert.pem — PyInstaller's certifi hook
        # did not fire, or the spec dropped it.
        return CaBundleStatus("system", "", version, f"missing CA bundle: {path}")
    return CaBundleStatus("certifi", str(path), version, "")


def create_ssl_context() -> ssl.SSLContext:
    """A verifying SSL context anchored on certifi where possible.

    Falls back to the system trust store if certifi or its bundle is
    unavailable — which is a real degradation (it is the very failure
    mode above), so it is logged as a warning rather than passing
    silently.

    What this never does is weaken verification: no `check_hostname =
    False`, no `CERT_NONE`. A build that cannot verify must fail loudly
    on a bad certificate, because the thing being fetched is an
    executable installer that will then be run.
    """
    global _context  # noqa: PLW0603 — building a context parses ~150 certs
    if _context is not None:
        return _context

    status = ca_bundle_status()
    if status.is_bundled:
        try:
            _context = ssl.create_default_context(cafile=status.path)
            log.debug("TLS: using certifi %s (%s)", status.version, status.path)
            return _context
        except (OSError, ssl.SSLError) as exc:
            log.warning("TLS: certifi bundle at %s unusable (%s)", status.path, exc)
    else:
        log.warning(
            "TLS: certifi CA bundle unavailable (%s); falling back to the"
            " system trust store, which is what fails on machines whose"
            " root-certificate updates are stale", status.detail,
        )

    _context = ssl.create_default_context()
    return _context
