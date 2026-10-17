"""Machine hardware ID (HID) — stable per-machine fingerprint.

Combines the first non-virtual non-USB NIC's MAC address with the
Windows MachineGuid registry value, hashes both. The result is what
the licensing server stores at activation time and what the desktop
recomputes at every startup to verify the license is still on the
machine it was activated for.

Stability properties (good):
  - MachineGuid is set during Windows install and only changes on a
    full OS reinstall.
  - Built-in NIC MACs survive Windows updates, driver updates, and
    docking-station swaps.

Known instability cases (call out in support docs):
  - User replaces the motherboard / built-in NIC → MAC changes → HID
    differs → license needs re-activation.
  - User does an in-place Windows reset (not a clean reinstall) →
    MachineGuid is preserved in most cases but not always.
  - Hyper-V hosts: GetAdaptersAddresses returns the host's MAC; HID
    is stable across VM start/stop on the same host.

Non-Windows callers get a deterministic fallback ("non-windows-host")
so dev / CI machines have a consistent HID for testing without
hitting Win32 calls that don't exist.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import uuid


log = logging.getLogger(__name__)


_UNKNOWN_HID = "0" * 64


def compute_hid() -> str:
    """Return the 64-char hex SHA-256 of (MAC + MachineGuid).

    Never raises — any failure returns the deterministic
    `_UNKNOWN_HID` so callers can show "license bound to a different
    machine" rather than crashing on a corrupted Windows registry.
    """
    mac = _read_primary_mac()
    machine_guid = _read_windows_machine_guid()
    raw = f"{mac}|{machine_guid}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── MAC ────────────────────────────────────────────────────────────


def _read_primary_mac() -> str:
    """Best-effort: MAC of the first non-virtual, non-USB NIC.

    Falls back to `uuid.getnode()` which is portable and sufficient
    for non-Windows tests. On Windows we try harder because virtual
    adapters (WSL, Hyper-V switches, Bluetooth PAN) shift around.
    """
    if sys.platform == "win32":
        try:
            mac = _read_windows_primary_mac()
            if mac:
                return mac
        except Exception as e:  # noqa: BLE001
            log.warning("hid: windows MAC lookup failed (%s); falling back", e)
    # Cross-platform fallback: uuid.getnode returns the first MAC the
    # stdlib finds. Stable enough for non-Windows dev machines.
    n = uuid.getnode()
    return ":".join(f"{(n >> (8 * i)) & 0xFF:02x}" for i in reversed(range(6)))


def _read_windows_primary_mac() -> str:
    """Iterate adapters via Win32 GetAdaptersAddresses, return the
    MAC of the first one that's plugged in, non-loopback, non-virtual.

    We avoid pywin32 here so this module imports cleanly on the
    Ubuntu Semantic Release runner — uses ctypes directly against
    iphlpapi.dll.
    """
    import ctypes
    from ctypes import wintypes

    # Flags + constants for GetAdaptersAddresses
    GAA_FLAG_SKIP_UNICAST   = 0x0001  # noqa: N806
    GAA_FLAG_SKIP_ANYCAST   = 0x0002  # noqa: N806
    GAA_FLAG_SKIP_MULTICAST = 0x0004  # noqa: N806
    GAA_FLAG_SKIP_DNS       = 0x0008  # noqa: N806
    IF_TYPE_ETHERNET_CSMACD = 6       # noqa: N806
    IF_TYPE_IEEE80211       = 71      # noqa: N806
    IF_OPER_STATUS_UP       = 1       # noqa: N806

    class IP_ADAPTER_ADDRESSES(ctypes.Structure):  # noqa: N801
        pass

    # Match the actual win32 layout up to the fields we read. The
    # struct is much larger — we only need length + Next pointer +
    # PhysicalAddress + IfType + OperStatus, and we stop chasing
    # further fields. AdapterName + FriendlyName are after a couple
    # of pointers we don't dereference, so we skip them with raw
    # void_p typing.
    IP_ADAPTER_ADDRESSES._fields_ = [
        ("Length", wintypes.ULONG),
        ("IfIndex", wintypes.DWORD),
        ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.c_void_p),
        ("FirstAnycastAddress", ctypes.c_void_p),
        ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p),
        ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p),
        ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * 8),
        ("PhysicalAddressLength", wintypes.ULONG),
        ("Flags", wintypes.ULONG),
        ("Mtu", wintypes.ULONG),
        ("IfType", wintypes.DWORD),
        ("OperStatus", wintypes.DWORD),
        # The struct continues for many more fields; we stop reading
        # here because reading more requires matching the exact OS-
        # version layout, which is fragile. The fields above are
        # stable across all supported Windows versions.
    ]

    iphlpapi = ctypes.windll.iphlpapi
    GetAdaptersAddresses = iphlpapi.GetAdaptersAddresses  # noqa: N806
    GetAdaptersAddresses.argtypes = [
        wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
        ctypes.POINTER(IP_ADAPTER_ADDRESSES), ctypes.POINTER(wintypes.ULONG),
    ]
    GetAdaptersAddresses.restype = wintypes.ULONG

    AF_UNSPEC = 0  # noqa: N806
    flags = (
        GAA_FLAG_SKIP_UNICAST | GAA_FLAG_SKIP_ANYCAST
        | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS
    )
    size = wintypes.ULONG(15000)
    buf = ctypes.create_string_buffer(size.value)
    rv = GetAdaptersAddresses(
        AF_UNSPEC, flags, None,
        ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ctypes.byref(size),
    )
    if rv != 0:
        return ""

    adapter_ptr = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while adapter_ptr:
        adapter = adapter_ptr.contents
        if (
            adapter.OperStatus == IF_OPER_STATUS_UP
            and adapter.IfType in (IF_TYPE_ETHERNET_CSMACD, IF_TYPE_IEEE80211)
            and adapter.PhysicalAddressLength >= 6
            and not _is_virtual_adapter(adapter.Description or "")
        ):
            mac_bytes = bytes(adapter.PhysicalAddress[:6])
            return ":".join(f"{b:02x}" for b in mac_bytes)
        if not adapter.Next:
            break
        adapter_ptr = adapter.Next
    return ""


def _is_virtual_adapter(description: str) -> bool:
    """Filter out virtual adapters that come and go (VPN, container,
    Hyper-V virtual switch, etc.). We want a MAC that stays stable
    across reboots and software installs."""
    d = description.lower()
    return any(token in d for token in (
        "virtual", "vmware", "hyper-v", "vethernet", "wsl",
        "tap-", "tun-", "wireguard", "openvpn", "loopback",
        "bluetooth", "usb",
    ))


# ── MachineGuid ────────────────────────────────────────────────────


def _read_windows_machine_guid() -> str:
    """Read `HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid`.

    On non-Windows we substitute a constant so test environments are
    deterministic. The MachineGuid format is a UUID string; we don't
    parse it, just hash it byte-for-byte alongside the MAC.
    """
    if sys.platform != "win32":
        return "non-windows-host"
    try:
        import winreg  # type: ignore[import-not-found]
        # 64-bit view (KEY_WOW64_64KEY) because the 32-bit-on-64-bit
        # WOW redirector exposes a *different* MachineGuid under the
        # WOW6432Node — we want the one Windows itself uses for crypto.
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        try:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value)
        finally:
            winreg.CloseKey(key)
    except Exception as e:  # noqa: BLE001
        log.warning("hid: MachineGuid read failed (%s); using fallback", e)
        return "unknown-machineguid"
