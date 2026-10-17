"""Backend-agnostic e-mail client dispatcher.

The desktop app sends drafts in two places (Phase 1 «Пошаљи
странкама…», backup → e-mail target) and originally talked to
Outlook only via COM. Some OIK sites use the office suite without
Outlook installed and rely on Thunderbird instead — for them, the
Outlook-only path is a hard blocker.

This module owns the shared `DraftSpec` / `DraftResult` dataclasses
and the dispatcher that routes `create_drafts()` to whichever
backend is configured + actually present on the machine. Outlook +
Thunderbird modules live next to this one and are imported lazily so
the dispatcher itself stays import-safe on every platform.

Preference resolution (most-specific wins):
  1. Operator's explicit choice in Поставке ОИК → Систем
     (`AppSettings.email_client` = "outlook" | "thunderbird").
  2. Auto — first available backend, Outlook preferred (it's the
     office standard in Serbia; Thunderbird is a deliberate
     alternative when Outlook isn't installed).
  3. If neither is available, every send-side caller gracefully
     degrades (button hidden / disabled). Receive-side (Phase 2
     inbox import) still only goes through Outlook — Thunderbird
     receive is more involved (MBox / IMAP) and tracked in
     TODO §8 as not-yet-shipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable


log = logging.getLogger(__name__)


class EmailClient(str, Enum):
    """User-facing client choices.

    AUTO is what `AppSettings.email_client` defaults to; the
    dispatcher resolves it to the first available concrete client.
    OUTLOOK / THUNDERBIRD are the operator's explicit overrides when
    they want to pin a specific backend even if both are installed.
    """

    AUTO = "auto"
    OUTLOOK = "outlook"
    THUNDERBIRD = "thunderbird"


@dataclass
class DraftSpec:
    """One outgoing e-mail to be created as a draft.

    Shared shape across backends so `gui/dialogs/send_to_parties_dialog`
    and `gui/dialogs/backup_flow` can build a list of these without
    caring which client will pick them up.
    """

    to: str
    subject: str
    body: str
    attachment: Path | None = None


@dataclass
class DraftResult:
    """Per-draft outcome from `create_drafts()`."""

    spec: DraftSpec
    ok: bool
    error: str = ""


class EmailClientUnavailable(RuntimeError):
    """No e-mail backend is available on this machine.

    GUI callers should guard with `any_available()` first and hide the
    relevant button; this exception is the belt-and-suspenders backstop
    for the case where availability changes between the check and the
    actual call.
    """


# ── Inbox-side shared shape ───────────────────────────────────────


@dataclass
class InboxAttachment:
    """One .xlsx attachment on an inbox message.

    `save_to(dest)` lazily extracts the attachment's bytes to disk —
    the underlying source (Outlook COM ref or MBox MIME part) stays
    held by the closure until the caller actually needs the file.
    Once saved, Phase 2 hands the path to `popunjeni_io.import_file`
    along with the parent message's `received_time`.
    """

    name: str
    size: int
    # The callback closes over backend-specific state (a COM
    # Attachment reference for Outlook, raw bytes for Thunderbird),
    # kept opaque so this dataclass stays the only contract callers
    # see across backends.
    _save_callback: Callable[[Path], None] = field(repr=False)

    def save_to(self, dest: Path) -> None:
        self._save_callback(Path(dest))


@dataclass
class InboxMessage:
    """Summary of one inbox message with at least one .xlsx attachment.

    Same shape regardless of which backend produced it — the inbox
    picker dialog and Phase 2 import flow treat all backends
    identically once the messages are wrapped in this shape.
    """

    entry_id: str           # backend-stable per-message ID
    subject: str
    sender_name: str
    sender_email: str
    received_time: datetime
    attachments: list[InboxAttachment]


@dataclass
class PickedAttachment:
    """One attachment the operator chose to import from the picker.

    Holds the source attachment plus the parent message metadata
    Phase 2 needs to call `popunjeni_io.import_file` (the timestamp
    becomes the canonical "submitted at" used for de-duplication of
    multiple submissions from the same party).
    """

    attachment: InboxAttachment
    received_time: datetime
    subject: str
    sender_name: str


class InboxBackendUnavailable(RuntimeError):
    """No inbox backend is reachable on this machine.

    Separate from `EmailClientUnavailable` (send-side) because the
    receive direction has stricter requirements: Outlook needs the COM
    integration, Thunderbird needs a discovered profile + at least
    one Inbox MBox file. The button-visibility check in Phase 2 uses
    `inbox_available()`.
    """


# ── Availability ──────────────────────────────────────────────────


def outlook_available() -> bool:
    """True iff the Outlook COM integration loaded cleanly on import."""
    try:
        from biracki_odbor.integrations import outlook as outlook_mod
        return bool(outlook_mod.OUTLOOK_AVAILABLE)
    except Exception:  # noqa: BLE001 — defensive against import-time errors
        return False


def thunderbird_available() -> bool:
    """True iff a Thunderbird binary was located on this machine."""
    try:
        from biracki_odbor.integrations import thunderbird as tb_mod
        return bool(tb_mod.THUNDERBIRD_AVAILABLE)
    except Exception:  # noqa: BLE001
        return False


def available_clients() -> list[EmailClient]:
    """Enumerate concrete backends actually present on the machine.

    Useful for the settings dropdown (only show options the operator
    could actually pick) and for `any_available()` button-visibility
    checks.
    """
    out: list[EmailClient] = []
    if outlook_available():
        out.append(EmailClient.OUTLOOK)
    if thunderbird_available():
        out.append(EmailClient.THUNDERBIRD)
    return out


def any_available() -> bool:
    """True iff at least one backend is usable on this machine."""
    return bool(available_clients())


# ── Inbox availability (separate from send) ───────────────────────


def outlook_inbox_available() -> bool:
    """True iff the Outlook integration can read the inbox.

    Currently identical to `outlook_available()` because Outlook's COM
    integration handles both directions. Kept separate so future
    changes (e.g. a fast Outlook send-only mode) don't conflate the
    two."""
    return outlook_available()


def thunderbird_inbox_available() -> bool:
    """True iff at least one Thunderbird Inbox MBox file is reachable.

    Distinct from `thunderbird_available()` (which checks for the
    binary) — receiving requires a discovered profile + an Inbox file
    on disk. A freshly-installed Thunderbird with no accounts
    configured will fail this check; that's correct — there's
    literally nothing to read."""
    try:
        from biracki_odbor.integrations import thunderbird as tb_mod
        return bool(tb_mod.find_inbox_paths())
    except Exception:  # noqa: BLE001
        return False


def any_inbox_available() -> bool:
    """True iff at least one backend can attempt an inbox fetch."""
    return outlook_inbox_available() or thunderbird_inbox_available()


def resolve_inbox(preference: EmailClient | str) -> EmailClient | None:
    """Same as `resolve()` but gates on inbox-reachability instead of
    send-reachability — a Thunderbird install with no accounts looks
    available to send but not to read."""
    if isinstance(preference, str):
        try:
            preference = EmailClient(preference)
        except ValueError:
            preference = EmailClient.AUTO

    available: list[EmailClient] = []
    if outlook_inbox_available():
        available.append(EmailClient.OUTLOOK)
    if thunderbird_inbox_available():
        available.append(EmailClient.THUNDERBIRD)
    if not available:
        return None

    if preference == EmailClient.OUTLOOK:
        if EmailClient.OUTLOOK in available:
            return EmailClient.OUTLOOK
        log.warning(
            "email_client (inbox): Outlook preferred but unavailable;"
            " falling back to %s", available[0].value,
        )
        return available[0]
    if preference == EmailClient.THUNDERBIRD:
        if EmailClient.THUNDERBIRD in available:
            return EmailClient.THUNDERBIRD
        log.warning(
            "email_client (inbox): Thunderbird preferred but unavailable;"
            " falling back to %s", available[0].value,
        )
        return available[0]
    return available[0]


def fetch_inbox_messages(
    *,
    preference: EmailClient | str = EmailClient.AUTO,
    since_days: int = 14,
    only_xlsx: bool = True,
    max_messages: int = 200,
    subject_contains: str = "",
    account_email: str = "",
) -> list[InboxMessage]:
    """Read recent inbox messages via the resolved backend.

    Same contract as the per-backend `fetch_inbox_messages` functions
    plus a `preference` knob. Raises `InboxBackendUnavailable` when
    neither backend can attempt the fetch (e.g. no Outlook + no
    Thunderbird profile on disk); the GUI guards on
    `any_inbox_available()` before calling so this exception is the
    backstop for race conditions.
    """
    target = resolve_inbox(preference)
    if target is None:
        raise InboxBackendUnavailable(
            "Ниједан мејл клијент са inbox-ом није доступан"
            " (нема Outlook-а, нема Thunderbird профила)."
        )
    log.info(
        "email_client.fetch_inbox_messages: dispatching to %s",
        target.value,
    )
    if target == EmailClient.OUTLOOK:
        from biracki_odbor.integrations import outlook as outlook_mod
        return outlook_mod.fetch_inbox_messages(
            since_days=since_days, only_xlsx=only_xlsx,
            max_messages=max_messages,
            subject_contains=subject_contains,
        )
    if target == EmailClient.THUNDERBIRD:
        from biracki_odbor.integrations import thunderbird as tb_mod
        return tb_mod.fetch_inbox_messages(
            since_days=since_days, only_xlsx=only_xlsx,
            max_messages=max_messages,
            subject_contains=subject_contains,
            account_email=account_email,
        )
    raise InboxBackendUnavailable(f"Непознат мејл клијент: {target}")


# ── Resolution ────────────────────────────────────────────────────


def resolve(preference: EmailClient | str) -> EmailClient | None:
    """Map operator preference + machine state to a concrete client.

    `preference` may be the enum or its string value (matches what's
    stored in `AppSettings.email_client`). Returns None when no
    backend is available, in which case the caller should refuse to
    proceed and show a clear error (the GUI guards before reaching
    this code, but the resolution is also exposed for tests).
    """
    if isinstance(preference, str):
        try:
            preference = EmailClient(preference)
        except ValueError:
            preference = EmailClient.AUTO

    available = available_clients()
    if not available:
        return None

    if preference == EmailClient.OUTLOOK:
        if EmailClient.OUTLOOK in available:
            return EmailClient.OUTLOOK
        # Operator asked for Outlook but it's not installed; fall back
        # to whatever IS available rather than refusing to send. Log
        # so the misconfig is visible in the daily log.
        log.warning(
            "email_client: Outlook preferred but unavailable; falling back to %s",
            available[0].value,
        )
        return available[0]
    if preference == EmailClient.THUNDERBIRD:
        if EmailClient.THUNDERBIRD in available:
            return EmailClient.THUNDERBIRD
        log.warning(
            "email_client: Thunderbird preferred but unavailable; falling back to %s",
            available[0].value,
        )
        return available[0]
    # AUTO — Outlook wins when both are present (Serbian OIK office
    # standard), else whichever is first in the available list.
    return available[0]


# ── Dispatch ──────────────────────────────────────────────────────


def create_drafts(
    drafts: list[DraftSpec],
    *,
    preference: EmailClient | str = EmailClient.AUTO,
    display_first: bool = True,
    display_all: bool = False,
) -> list[DraftResult]:
    """Create drafts via the resolved backend.

    `display_first` / `display_all` are forwarded only to Outlook —
    Thunderbird's `-compose` always opens its own compose window per
    draft, there's no headless option.
    """
    target = resolve(preference)
    if target is None:
        raise EmailClientUnavailable(
            "Ниједан мејл клијент (Outlook / Thunderbird) није доступан на овом рачунару."
        )
    log.info(
        "email_client.create_drafts: dispatching %d drafts to %s",
        len(drafts), target.value,
    )
    if target == EmailClient.OUTLOOK:
        from biracki_odbor.integrations import outlook as outlook_mod
        return outlook_mod.create_drafts(
            drafts, display_first=display_first, display_all=display_all,
        )
    if target == EmailClient.THUNDERBIRD:
        from biracki_odbor.integrations import thunderbird as tb_mod
        return tb_mod.create_drafts(drafts)
    # Defensive — `resolve` is supposed to return one of the above.
    raise EmailClientUnavailable(f"Непознат мејл клијент: {target}")


# ── Cyrillic display names (for the settings dropdown) ────────────


_LABELS = {
    EmailClient.AUTO: "Аутоматски (прво доступан)",
    EmailClient.OUTLOOK: "Microsoft Outlook",
    EmailClient.THUNDERBIRD: "Mozilla Thunderbird",
}


def label(client: EmailClient) -> str:
    return _LABELS.get(client, client.value)
