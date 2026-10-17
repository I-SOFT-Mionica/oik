"""Mozilla Thunderbird send-side integration.

For OIK sites that use the office productivity tools without Outlook
installed, Thunderbird is the standard alternative. This module is
the send-side counterpart to `outlook.py`'s COM `create_drafts()` —
it produces the same `DraftResult` shape, but via Thunderbird's
`-compose` command-line interface instead of an automation API.

Why CLI (not Thunderbird's add-on / WebExtension API): the CLI is
the only headless interface Thunderbird ships out of the box. Any
WebExtension API would require us to bundle an extension into every
operator's profile, which is not a setup we can require for the
desktop installer. The CLI is stable across versions and works on
any Thunderbird install reachable on PATH.

Receive side (inbox listing for Phase 2 import) is NOT in this
module — Thunderbird's CLI has no read API, and the alternatives
(MBox parsing under `~/Thunderbird/Profiles/<name>/Mail/...` or
talking to a configured IMAP account) are tracked in TODO §8 as
not-yet-shipped. Phase 2 still imports through Outlook only.

CLI reference (Thunderbird `--help`):
    thunderbird -compose
        "to=alice@example.com,
         subject=Subject line,
         body=Body text,
         attachment=file:///C:/Users/...../file.xlsx"
The whole compose-spec is ONE argument; multiple key=value pairs are
comma-separated. Fields that contain commas or single quotes are
wrapped in single quotes (Thunderbird's parser, not the shell's) with
inner single quotes doubled. Literal newlines in the body are passed
as-is via Popen (no URL-encoding — Thunderbird 115+ stopped decoding
%0A in the body field).
"""

from __future__ import annotations

import configparser
import logging
import mailbox
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from biracki_odbor.integrations.email_client import (
    DraftResult, DraftSpec, InboxAttachment, InboxMessage,
)


log = logging.getLogger(__name__)


# ── Binary discovery ──────────────────────────────────────────────


def find_thunderbird_exe() -> Path | None:
    """Locate the Thunderbird binary, or None if it isn't installed.

    Search order:
      1. `thunderbird` on PATH (Linux / macOS / Windows after install).
      2. Standard Windows install dirs under Program Files.
      3. (Macintosh has `/Applications/Thunderbird.app/Contents/MacOS/
         thunderbird` but the OIK target is Windows; covered if it's
         on PATH but not exhaustively searched.)
    """
    # PATH lookup — works everywhere if the installer added it.
    name = "thunderbird.exe" if sys.platform == "win32" else "thunderbird"
    found = shutil.which(name)
    if found:
        return Path(found)

    # Windows: Thunderbird's installer doesn't reliably PATH-register
    # itself, so check the conventional locations under Program Files.
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "Mozilla Thunderbird" / "thunderbird.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
                / "Mozilla Thunderbird" / "thunderbird.exe",
            # Per-user install (default since Thunderbird ~115 on Windows).
            Path(os.environ.get("LOCALAPPDATA", ""))
                / "Mozilla Thunderbird" / "thunderbird.exe",
        ]
        for p in candidates:
            if p.exists():
                return p
    return None


_THUNDERBIRD_EXE = find_thunderbird_exe()
THUNDERBIRD_AVAILABLE: bool = _THUNDERBIRD_EXE is not None


# ── Compose-spec encoding ─────────────────────────────────────────


def _encode_field(value: str) -> str:
    """Quote a compose-spec field if it contains the separator char.

    Thunderbird's `-compose` argument is a single comma-separated key=
    value list. Any field that itself contains a comma (e.g. a subject
    with a comma, or a body that spans words separated by commas)
    needs to be wrapped in single quotes so the parser doesn't split
    it. Inner single quotes get escaped by doubling.
    """
    if "," in value or "'" in value:
        return "'" + value.replace("'", "''") + "'"
    return value


def _build_compose_arg(spec: DraftSpec) -> str:
    """Assemble the `key=value,key=value,…` blob Thunderbird expects."""
    parts: list[str] = []
    if spec.to:
        parts.append(f"to={_encode_field(spec.to)}")
    if spec.subject:
        parts.append(f"subject={_encode_field(spec.subject)}")
    if spec.body:
        # Thunderbird 115+ (Supernova) no longer URL-decodes %0A/%2C in
        # the body field, so the old URL-encoding approach produces literal
        # "%0A" characters in the compose window.  Use single-quoting with
        # literal newlines instead: the compose arg is passed as a list
        # element via Popen so embedded newlines reach Thunderbird's parser
        # intact without going through the shell.  Inner single quotes are
        # escaped by doubling (''), same as _encode_field does elsewhere.
        body = spec.body.replace("\r\n", "\n").replace("'", "''")
        parts.append(f"body='{body}'")
    if spec.attachment is not None:
        # Thunderbird wants a file:// URI for attachments, NOT a plain
        # path. On Windows the URI uses forward slashes after the drive
        # letter: `file:///C:/path/to/file.xlsx`. `Path.as_uri()` does
        # this conversion correctly across platforms.
        try:
            uri = Path(spec.attachment).resolve().as_uri()
        except ValueError:
            # `as_uri` raises for relative paths; fall back to a best
            # effort. The operator will see "attachment missing" in
            # the compose window if it doesn't resolve.
            uri = str(spec.attachment)
        parts.append(f"attachment={_encode_field(uri)}")
    return ",".join(parts)


# ── Public API — mirrors outlook.create_drafts ────────────────────


# ── Inbox-side — read MBox files from local Thunderbird profile ───
#
# Why MBox parsing: Thunderbird stores mail in plain MBox files under
# its profile dir. For accounts configured for POP3 (or IMAP with
# "Keep messages on this computer" enabled, which is Thunderbird's
# default for offline use), the Inbox is locally available without
# any network calls. We use stdlib `mailbox.mbox` + `email` so there's
# zero new third-party dependency.
#
# Limitation: IMAP-only accounts without offline copies have nothing
# on disk to read. The picker dialog tells the operator in that case;
# the fix is "enable offline" in Thunderbird account settings.


def _thunderbird_appdata_root() -> Path | None:
    """Locate the Thunderbird profile root directory.

    Windows: `%APPDATA%\\Thunderbird\\`.
    Linux: `~/.thunderbird/`.
    macOS: `~/Library/Thunderbird/`.

    Returns None when none of these exist — caller treats that as
    "no Thunderbird configured on this machine, the picker can't be
    offered".
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "Thunderbird"
            if p.exists():
                return p
        return None
    home = Path.home()
    for cand in (home / ".thunderbird", home / "Library" / "Thunderbird"):
        if cand.exists():
            return cand
    return None


def _list_profiles(root: Path) -> list[Path]:
    """Parse `profiles.ini` and return existing profile directories.

    Thunderbird supports multiple profiles; we read every one rather
    than guessing "default", because the operator's mail might be in a
    profile they didn't mark default. Empty list if profiles.ini is
    missing or malformed — also returned when every listed profile
    points at a directory that no longer exists.
    """
    ini_path = root / "profiles.ini"
    if not ini_path.exists():
        return []
    cp = configparser.ConfigParser()
    try:
        cp.read(ini_path, encoding="utf-8")
    except (configparser.Error, OSError) as e:
        log.warning("thunderbird: profiles.ini unreadable (%s)", e)
        return []
    profiles: list[Path] = []
    for section in cp.sections():
        if not section.startswith("Profile"):
            continue
        path_value = cp[section].get("Path", "").strip()
        if not path_value:
            continue
        is_relative = cp[section].get("IsRelative", "1") == "1"
        candidate = (root / path_value) if is_relative else Path(path_value)
        if candidate.exists() and candidate.is_dir():
            profiles.append(candidate)
    return profiles


def _parse_prefs_js(prefs_path: Path) -> dict[str, str]:
    """Parse a Thunderbird prefs.js file into a key→value dict.

    Only reads string-valued prefs (quoted values). Boolean/integer
    prefs are ignored — we only need email addresses and directory paths.
    """
    pattern = re.compile(r'user_pref\("([^"]+)",\s*"([^"]*)"\)')
    prefs: dict[str, str] = {}
    try:
        text = prefs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return prefs
    for m in pattern.finditer(text):
        prefs[m.group(1)] = m.group(2)
    return prefs


def _inbox_dirs_for_account(profile_dir: Path, account_email: str) -> list[Path]:
    """Return the mail-server directory (or directories) for the given email.

    Parses prefs.js to find which Thunderbird account uses `account_email`,
    then resolves the directory that account's server stores mail in.
    The inbox file itself is expected directly inside that directory
    (INBOX or Inbox for IMAP; Inbox for POP3/local).

    Returns an empty list when the email is not found in any account —
    the caller falls back to scanning all directories.
    """
    prefs = _parse_prefs_js(profile_dir / "prefs.js")
    if not prefs:
        return []

    needle = account_email.strip().lower()

    # identity name → email address
    id_emails: dict[str, str] = {}
    for key, val in prefs.items():
        if key.startswith("mail.identity.") and key.endswith(".useremail"):
            id_name = key.split(".")[2]
            id_emails[id_name] = val.strip().lower()

    # account name → server name, account name → identity list
    acct_server: dict[str, str] = {}
    acct_ids: dict[str, list[str]] = {}
    for key, val in prefs.items():
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != "mail" or parts[1] != "account":
            continue
        acct = parts[2]
        if parts[3] == "server":
            acct_server[acct] = val
        elif parts[3] == "identities":
            acct_ids[acct] = [i.strip() for i in val.split(",") if i.strip()]

    # Find servers belonging to accounts that use our email address
    target_servers: set[str] = set()
    for acct, server in acct_server.items():
        for id_name in acct_ids.get(acct, []):
            if id_emails.get(id_name) == needle:
                target_servers.add(server)

    if not target_servers:
        return []

    dirs: list[Path] = []
    for server in target_servers:
        dir_rel = prefs.get(f"mail.server.{server}.directory-rel", "")
        dir_abs = prefs.get(f"mail.server.{server}.directory", "")
        hostname = prefs.get(f"mail.server.{server}.hostname", "")
        stype = prefs.get(f"mail.server.{server}.type", "")

        candidate: Path | None = None
        if dir_rel.startswith("[Profile]/"):
            candidate = profile_dir / dir_rel[len("[Profile]/"):]
        elif dir_abs:
            candidate = Path(dir_abs)
        elif hostname and stype == "imap":
            # Fallback: conventional ImapMail/<hostname> layout
            candidate = profile_dir / "ImapMail" / hostname

        if candidate is not None and candidate.exists():
            dirs.append(candidate)

    return dirs


def find_inbox_paths(account_email: str = "") -> list[Path]:
    """Return MBox Inbox file(s) for the given account, or all inboxes.

    When `account_email` is set, parses each profile's prefs.js to
    locate only the inbox belonging to that address — avoids opening
    unrelated accounts on a multi-account Thunderbird install.

    Falls back to scanning every inbox across every profile when the
    email is blank or not found in prefs.js (same as the original
    behaviour).
    """
    root = _thunderbird_appdata_root()
    if root is None:
        return []
    profiles = _list_profiles(root)
    inboxes: list[Path] = []

    for prof in profiles:
        if account_email:
            server_dirs = _inbox_dirs_for_account(prof, account_email)
            if server_dirs:
                for sdir in server_dirs:
                    for name in ("INBOX", "Inbox"):
                        cand = sdir / name
                        if cand.is_file():
                            inboxes.append(cand)
                # Found matches for this profile — don't fall through
                # to the full scan for this profile.
                continue

        # No email filter, or account not found in prefs — scan all.
        local_inbox = prof / "Mail" / "Local Folders" / "Inbox"
        if local_inbox.is_file():
            inboxes.append(local_inbox)
        imap_root = prof / "ImapMail"
        if imap_root.is_dir():
            for server_dir in imap_root.iterdir():
                if not server_dir.is_dir():
                    continue
                for name in ("INBOX", "Inbox"):
                    cand = server_dir / name
                    if cand.is_file():
                        inboxes.append(cand)

    return inboxes


# ── IMAP-offline gap detection ─────────────────────────────────────


from dataclasses import dataclass as _dataclass


@_dataclass
class ImapOfflineGap:
    """An IMAP account found in prefs.js that has no local inbox file."""
    email: str
    hostname: str


def find_imap_offline_gaps(account_email: str = "") -> list[ImapOfflineGap]:
    """Return IMAP accounts configured in Thunderbird but with no local inbox.

    Used to surface a targeted warning when the inbox picker finds zero
    messages: instead of "no messages", we can tell the operator which
    specific account needs "Keep messages on this computer" enabled.

    When `account_email` is given, only that account is checked.
    """
    root = _thunderbird_appdata_root()
    if root is None:
        return []

    gaps: list[ImapOfflineGap] = []
    needle = account_email.strip().lower()

    for prof in _list_profiles(root):
        prefs = _parse_prefs_js(prof / "prefs.js")
        if not prefs:
            continue

        # Collect all server keys that are IMAP type
        server_keys: set[str] = set()
        for key in prefs:
            m = re.match(r"^mail\.server\.(server\d+)\.type$", key)
            if m and prefs[key] == "imap":
                server_keys.add(m.group(1))

        for srv in server_keys:
            hostname = prefs.get(f"mail.server.{srv}.hostname", "")
            if not hostname:
                continue

            # Get email address for this server via its identity
            srv_email = ""
            for key, val in prefs.items():
                if key.startswith("mail.identity.") and key.endswith(".smtpServer"):
                    continue
                if key.startswith("mail.identity.") and key.endswith(".useremail"):
                    # find identity linked to this server
                    pass
            # Simpler: check all identity emails against account→server mapping
            acct_server: dict[str, str] = {}
            acct_ids: dict[str, list[str]] = {}
            id_emails: dict[str, str] = {}
            for key, val in prefs.items():
                m2 = re.match(r"^mail\.account\.(account\d+)\.server$", key)
                if m2:
                    acct_server[m2.group(1)] = val
                m3 = re.match(r"^mail\.account\.(account\d+)\.identities$", key)
                if m3:
                    acct_ids[m3.group(1)] = [s.strip() for s in val.split(",") if s.strip()]
                m4 = re.match(r"^mail\.identity\.(id\d+)\.useremail$", key)
                if m4:
                    id_emails[m4.group(1)] = val.lower()

            for acct, s in acct_server.items():
                if s != srv:
                    continue
                for id_name in acct_ids.get(acct, []):
                    em = id_emails.get(id_name, "")
                    if em:
                        srv_email = em
                        break
                if srv_email:
                    break

            # Apply account_email filter if given
            if needle and srv_email and srv_email != needle:
                continue

            # Check whether a local inbox file exists for this server
            dir_rel = prefs.get(f"mail.server.{srv}.directory-rel", "")
            dir_abs = prefs.get(f"mail.server.{srv}.directory", "")
            mail_dir: Path | None = None
            if dir_rel.startswith("[Profile]/"):
                mail_dir = prof / dir_rel[len("[Profile]/"):]
            elif dir_abs:
                mail_dir = Path(dir_abs)
            else:
                mail_dir = prof / "ImapMail" / hostname

            has_inbox = False
            if mail_dir is not None and mail_dir.is_dir():
                for name in ("INBOX", "Inbox"):
                    if (mail_dir / name).is_file():
                        has_inbox = True
                        break

            if not has_inbox:
                gaps.append(ImapOfflineGap(
                    email=srv_email or hostname,
                    hostname=hostname,
                ))

    # Deduplicate by hostname
    seen: set[str] = set()
    result: list[ImapOfflineGap] = []
    for g in gaps:
        if g.hostname not in seen:
            seen.add(g.hostname)
            result.append(g)
    return result


def fetch_inbox_messages(
    since_days: int = 14,
    only_xlsx: bool = True,
    max_messages: int = 200,
    subject_contains: str = "",
    account_email: str = "",
) -> list[InboxMessage]:
    """Mirror of `outlook.fetch_inbox_messages` for Thunderbird MBox.

    Same args, same return shape, same filter semantics:
      - `since_days` drops anything older than the cutoff,
      - `only_xlsx` keeps only messages with at least one .xlsx
        attachment,
      - `subject_contains` (case-insensitive substring) lets Phase 2
        narrow to messages carrying the per-election token,
      - `max_messages` caps the result list (newest-first),
      - `account_email` pins the scan to a single Thunderbird account's
        inbox; falls back to all inboxes when blank or not matched.

    Walks only the Inbox file(s) for the resolved account (or all inboxes
    when no account is configured). Returns an empty list when no inbox
    files are found.
    """
    inbox_paths = find_inbox_paths(account_email=account_email)
    if not inbox_paths:
        log.warning(
            "thunderbird.fetch_inbox_messages: no inbox files found",
        )
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(since_days, 1))
    needle = subject_contains.strip().lower()
    results: list[InboxMessage] = []

    for inbox_path in inbox_paths:
        try:
            mb = mailbox.mbox(str(inbox_path))
        except (OSError, ValueError) as e:
            log.warning(
                "thunderbird: cannot open %s (%s)", inbox_path, e,
            )
            continue
        try:
            for key in mb.keys():
                if len(results) >= max_messages * 2:
                    # Soft cap during the walk: we sort + trim later.
                    # The 2× lets the final sort still pick the N
                    # newest even if we visit older entries first.
                    break
                try:
                    msg = mb[key]
                except (KeyError, OSError, ValueError) as e:
                    log.warning(
                        "thunderbird: skipping mbox entry #%s (%s)", key, e,
                    )
                    continue
                wrapped = _wrap_mbox_message(
                    msg, only_xlsx=only_xlsx,
                    cutoff=cutoff, needle=needle,
                )
                if wrapped is not None:
                    results.append(wrapped)
        finally:
            mb.close()

    results.sort(key=lambda m: m.received_time, reverse=True)
    return results[:max_messages]


# ── Internal MBox parsing helpers ─────────────────────────────────


def _decode_mime_header(value: str) -> str:
    """Decode an RFC 2047 encoded-word header to plain str.

    Subject + filename headers often arrive as
    `=?UTF-8?Q?...?=` or `=?UTF-8?B?...?=` runs; stdlib's
    `decode_header` parses both. Bytes parts get decoded with their
    declared charset (fallback UTF-8 + replace) so we never raise
    just because a sender used an exotic encoding.
    """
    if not value:
        return ""
    parts = decode_header(value)
    out: list[str] = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _parse_received_time(msg: Message) -> datetime | None:
    """Best-effort UTC timestamp for the message.

    Prefer the `Date:` header (RFC 5322 timestamp). When that's
    missing or unparseable, return None and let the caller drop the
    message rather than invent a date — silently treating undated
    mail as "now" would let stale messages slip past the cutoff.
    """
    raw = msg.get("Date", "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _wrap_mbox_message(
    msg: Message,
    *,
    only_xlsx: bool,
    cutoff: datetime,
    needle: str,
) -> InboxMessage | None:
    """Convert an `email.message.Message` to `InboxMessage`, or None.

    Filters applied here mirror what MAPI's Restrict does on the
    Outlook side — date cutoff first (cheapest), then subject token,
    then attachment walk (most expensive). Messages with no qualifying
    attachment return None too, so the result list never contains
    rows the picker dialog can't act on.
    """
    received = _parse_received_time(msg)
    if received is None or received < cutoff:
        return None

    subject = _decode_mime_header(msg.get("Subject", ""))
    if needle and needle not in subject.lower():
        return None

    sender_name_raw, sender_email = parseaddr(msg.get("From", ""))
    sender_name = _decode_mime_header(sender_name_raw)

    attachments: list[InboxAttachment] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        # `get_filename` already does decode_header internally on
        # modern stdlib, but it can return None for inline parts.
        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode_mime_header(filename)
        if only_xlsx and not filename.lower().endswith(".xlsx"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        attachments.append(_attachment_from_bytes(filename, payload))

    if not attachments:
        return None

    return InboxMessage(
        entry_id=str(msg.get("Message-ID", "")) or f"mbox-{id(msg):x}",
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email or "",
        received_time=received,
        attachments=attachments,
    )


def _attachment_from_bytes(filename: str, payload: bytes) -> InboxAttachment:
    """Wrap raw MIME bytes in an InboxAttachment with a save callback.

    The payload is captured by closure so the eventual `save_to()` is
    a simple file write — no need to keep the parent mbox file open.
    This is the symmetry break vs Outlook (where the COM object has
    to stay alive); for Thunderbird we just hold the bytes.
    """
    def save(dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(payload)

    return InboxAttachment(
        name=filename, size=len(payload), _save_callback=save,
    )


# ── Outgoing — create draft emails (unchanged below) ──────────────


def create_drafts(drafts: list[DraftSpec]) -> list[DraftResult]:
    """Open a Thunderbird compose window for each draft.

    Unlike Outlook's `Save()` + `Display()` two-step (which lets us
    save to Drafts in the background and only display the first),
    Thunderbird's CLI ALWAYS opens a compose window. Operators will
    see N windows for N drafts; we send them in a single `Popen` call
    each so they spawn concurrently rather than one waiting for the
    previous to close.

    Per-draft errors don't abort the batch — they're collected into
    `DraftResult.error` so the GUI can summarise N succeeded / M
    failed without losing context for the failures.
    """
    if not THUNDERBIRD_AVAILABLE or _THUNDERBIRD_EXE is None:
        raise RuntimeError(
            "Thunderbird није доступан на овом рачунару. "
            "Проверите да ли је Thunderbird инсталиран."
        )

    results: list[DraftResult] = []
    for spec in drafts:
        try:
            compose_arg = _build_compose_arg(spec)
            # Detached so the GUI's process tree doesn't keep
            # Thunderbird windows tethered. CREATE_NEW_PROCESS_GROUP
            # also stops Ctrl-C in the parent from killing the child.
            creationflags = 0
            if os.name == "nt":
                creationflags = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                )
            subprocess.Popen(
                [str(_THUNDERBIRD_EXE), "-compose", compose_arg],
                close_fds=True,
                creationflags=creationflags,
            )
            results.append(DraftResult(spec=spec, ok=True))
        except OSError as e:
            log.warning(
                "thunderbird: cannot create draft to %s (%s)", spec.to, e,
            )
            results.append(DraftResult(spec=spec, ok=False, error=str(e)))
    return results
