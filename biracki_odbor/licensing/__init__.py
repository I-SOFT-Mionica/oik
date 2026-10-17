"""License client — talks to the I-SOFT license server.

Pattern adapted from the waterworks.rs auth/router.py activation flow:
the server pre-issues a `license_code`, the desktop client posts that
code + a locally-computed machine HID, the server binds the row to the
HID and returns a signed JWT, the client stores the JWT and from then
on validates against the local HID at startup (offline) and consults
the server when checking for updates (online).

Submodules:

  - `hid`             — SHA256(MAC + Windows MachineGuid) fingerprint
  - `state`           — License dataclass + Mode enum (DISABLED /
                        LICENSED / DEMO)
  - `token`           — JWT decode (no local verify; server is the
                        source of truth) + HID-match check
  - `server_client`   — httpx wrappers around POST /activate and
                        POST /check-update

The whole package short-circuits cleanly when `licensing_server_url`
is blank — see `state.load_license` for the "disabled" fast path.
"""
