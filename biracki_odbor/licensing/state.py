"""License state machine — DISABLED / LICENSED / DEMO modes.

`Mode` distinguishes:

  - **DISABLED** — licensing_server_url is blank. The licensing
    feature itself is off. App runs in full mode unconditionally
    (dev / CI default).
  - **LICENSED** — license.dat exists, parses, and its HID matches
    the local machine. Full functionality.
  - **DEMO** — license.dat is missing OR malformed OR bound to a
    different machine. App runs but Phase 1 caps to a single
    polling station; banner across the app surfaces the situation.

`load_license` is the single entry point AppState calls on init.
It's intentionally side-effect-free apart from reading the .dat
file — no HTTP, no UI. The activation flow lives in
`server_client.activate()` + the GUI dialog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from biracki_odbor.licensing.hid import compute_hid
from biracki_odbor.licensing.token import (
    TokenDecodeError, TokenSignatureError, verify_token,
)


log = logging.getLogger(__name__)


class Mode(str, Enum):
    DISABLED = "disabled"  # licensing feature itself is off
    LICENSED = "licensed"  # local license verifies + HID matches
    DEMO = "demo"          # no license, wrong machine, malformed file


@dataclass
class License:
    """The runtime license state held by AppState.

    All fields are populated for LICENSED; only `mode` + `reason`
    are meaningful for DISABLED / DEMO. The GUI checks `mode` to
    decide whether to show the demo banner, gate Phase 1, etc.
    """

    mode: Mode
    # Populated only when mode == LICENSED.
    license_id: str = ""
    license_code: str = ""
    issued_to: str = ""
    issued_at: str = ""           # ISO date string from the token
    updates_until: str = ""       # ISO date string from the token
    modules: list[str] = field(default_factory=list)
    # The local machine's computed HID at the time of this check.
    # Surfaces in the About page "Get fingerprint" button. Populated
    # in every mode so even the demo banner can show it.
    machine_hid: str = ""
    # Why we're in DEMO (or DISABLED). Surfaced verbatim in the
    # banner so the operator can act on it.
    reason: str = ""
    # LICENSED on a pre-2026-10-16 HS256 token (not verifiable locally);
    # replaced by an Ed25519 one at the next update check.
    legacy_token: bool = False

    @property
    def is_full(self) -> bool:
        return self.mode in (Mode.LICENSED, Mode.DISABLED)

    @property
    def is_demo(self) -> bool:
        return self.mode == Mode.DEMO

    def updates_expired(self, today: date | None = None) -> bool:
        """True iff updates_until < today. Only meaningful for LICENSED.

        Used by the updater check — the SERVER does the authoritative
        comparison, but the client can pre-empt the network round
        trip when the locally-cached value already shows expiry.
        """
        if not self.updates_until:
            return False
        try:
            cutoff = date.fromisoformat(self.updates_until)
        except ValueError:
            return False
        return (today or date.today()) > cutoff


# ── Loader ─────────────────────────────────────────────────────────


def load_license(
    *, licensing_server_url: str, license_dat_path: Path,
) -> License:
    """Compute the License the app should run under, given config.

    Single entry point for AppState. Pure of side effects beyond
    reading the .dat file. Never raises — every failure path
    produces a DEMO-mode License with a `reason` the GUI can show.
    """
    if not licensing_server_url.strip():
        # Empty server URL ⇒ licensing isn't engaged at all. Skip the
        # whole machinery, including .dat parsing. This is what keeps
        # the dev / CI test suite running without any setup.
        return License(mode=Mode.DISABLED, reason="licensing_disabled")

    hid_now = compute_hid()

    if not license_dat_path.exists():
        return License(
            mode=Mode.DEMO,
            machine_hid=hid_now,
            reason="no_license_file",
        )

    try:
        raw_token = license_dat_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        log.warning("license load: cannot read %s (%s)", license_dat_path, e)
        return License(
            mode=Mode.DEMO,
            machine_hid=hid_now,
            reason="license_unreadable",
        )

    try:
        verified = verify_token(raw_token)
    except TokenSignatureError as e:
        log.warning("license load: signature rejected (%s)", e)
        return License(
            mode=Mode.DEMO,
            machine_hid=hid_now,
            reason="license_invalid_signature",
        )
    except TokenDecodeError as e:
        log.warning("license load: malformed token (%s)", e)
        return License(
            mode=Mode.DEMO,
            machine_hid=hid_now,
            reason="license_malformed",
        )
    payload = verified.payload

    token_hid = str(payload.get("hid") or "")
    if not token_hid or token_hid != hid_now:
        log.info(
            "license load: HID mismatch (token=%s, machine=%s)",
            token_hid[:8] + "…" if token_hid else "(empty)",
            hid_now[:8] + "…",
        )
        return License(
            mode=Mode.DEMO,
            machine_hid=hid_now,
            issued_to=str(payload.get("issued_to") or ""),
            reason="machine_mismatch",
        )

    # Happy path.
    return License(
        mode=Mode.LICENSED,
        license_id=str(payload.get("sub") or ""),
        license_code=str(payload.get("license_code") or ""),
        issued_to=str(payload.get("issued_to") or ""),
        issued_at=str(payload.get("issued_at") or ""),
        updates_until=str(payload.get("updates_until") or ""),
        modules=list(payload.get("modules") or []),
        machine_hid=hid_now,
        legacy_token=verified.legacy,
    )


def save_refreshed_token(license_dat_path: Path, token: str) -> bool:
    """Replace license.dat with a token the server re-issued. Written only
    if it verifies with an accepted key (never legacy) and belongs to this
    machine; atomic, so a crash can't leave a half-written licence."""
    try:
        verified = verify_token(token)
    except TokenDecodeError as e:
        log.warning("refreshed token rejected: %s", e)
        return False
    if verified.legacy or str(verified.payload.get("hid") or "") != compute_hid():
        log.warning("refreshed token rejected: legacy or other machine")
        return False
    tmp = license_dat_path.with_suffix(".dat.tmp")
    try:
        tmp.write_text(token, encoding="utf-8")
        tmp.replace(license_dat_path)
    except OSError:
        log.warning("could not save refreshed licence token", exc_info=True)
        return False
    log.info("licence token upgraded to Ed25519")
    return True
