"""Outlook desktop integration — read Inbox messages with .xlsx attachments.

Used by Phase 2 import to source party submission files directly from
the operator's local Outlook profile. The email's `ReceivedTime` is
the canonical "submission timestamp" we then bake into the imported
file's name and cache entry (see `popunjeni_io.import_file`,
`popunjeni_cache.CacheEntry.received_time_iso`).

The module is **safe to import on non-Windows / no-pywin32**. In that
case `OUTLOOK_AVAILABLE` is False and `fetch_inbox_messages` raises
`OutlookUnavailable` if called. GUI code checks the flag and hides
the Outlook-import button instead of bombing out.

Why COM (not Microsoft Graph): the target office runs desktop Outlook
with a local Exchange profile already authenticated under the
operator's Windows session. COM gives us the messages without asking
anyone to set up OAuth or share credentials with a side-channel API.

This is also the foundation TODO.md § 4 (auto-send to parties) will
reuse — the receive direction is just the smaller half of the same
COM-init / connect / dispatch pattern.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


log = logging.getLogger(__name__)


# Probe pywin32 lazily so this module imports cleanly on the Ubuntu
# Semantic Release runner (no pywin32) and inside unit tests.
OUTLOOK_AVAILABLE: bool = False
_IMPORT_ERR: str = ""
try:  # pragma: no cover — covered by smoke test where reachable
    if sys.platform == "win32":
        import pythoncom  # noqa: F401 — re-checked at runtime
        import win32com.client  # noqa: F401
        OUTLOOK_AVAILABLE = True
except Exception as e:  # noqa: BLE001 — any import error means "no Outlook"
    _IMPORT_ERR = str(e)


class OutlookUnavailable(RuntimeError):
    """Raised when the integration is called on a platform without
    Outlook / pywin32 available. GUI callers should check
    `OUTLOOK_AVAILABLE` first; this exception is the belt-and-suspenders
    backstop."""


# Inbox folder constant (`olFolderInbox` in OOM). Hard-coding avoids an
# extra Outlook constants dispatch and keeps the unavailable-platform
# path import-clean.
_OL_FOLDER_INBOX = 6


# Inbox message + attachment dataclasses live in `email_client.py` so
# both Outlook and Thunderbird backends produce the same shape. Re-
# exported here as `OutlookMessage` / `OutlookAttachment` aliases so
# existing imports (`from outlook import OutlookMessage`) keep working
# until callers migrate.

from biracki_odbor.integrations.email_client import (  # noqa: E402,F401
    InboxAttachment as OutlookAttachment,
    InboxMessage as OutlookMessage,
)


def fetch_inbox_messages(
    since_days: int = 14,
    only_xlsx: bool = True,
    max_messages: int = 200,
    subject_contains: str = "",
) -> list[OutlookMessage]:
    """Return recent Inbox messages with .xlsx attachments.

    Args:
      since_days: only messages received within the last N days.
      only_xlsx: filter attachments to *.xlsx; messages with no .xlsx
        attachment are excluded entirely.
      max_messages: hard cap on how many messages to walk (the COM
        iteration is slow). Newer-first ordering means cap = "the N
        most recent matching messages".
      subject_contains: optional substring; when non-empty, the MAPI
        Restrict adds `[Subject] ci_phrasematch '<value>'` so a busy
        Inbox doesn't drown the picker in every department's .xlsx
        mail. Phase 2 passes the current election's `subject_token`
        (`[ОИК-YYYYMMDD]`) which Phase 1's send-to-parties drops into
        every outgoing subject + body footer. Empty string ⇒
        date-only filter (the previous default behavior).

    Raises:
      OutlookUnavailable: pywin32 not installed or platform is not
        Windows. Callers should guard with `OUTLOOK_AVAILABLE` first
        and present a fallback UI ("use file picker instead") when
        the integration is unavailable.

    The returned list is ordered newest-first by ReceivedTime.
    """
    if not OUTLOOK_AVAILABLE:
        raise OutlookUnavailable(
            f"Outlook integration unavailable on this platform: {_IMPORT_ERR}"
        )

    # Defer imports so static analysis on non-Windows doesn't flag
    # win32com as unresolved. The OUTLOOK_AVAILABLE check above means
    # we never reach this point without pywin32.
    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    try:
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(_OL_FOLDER_INBOX)
        except Exception as e:  # noqa: BLE001 — surface Outlook errors uniformly
            raise OutlookUnavailable(
                f"Cannot reach Outlook MAPI: {e}"
            ) from e

        items = inbox.Items
        # Restrict to recent messages via MAPI's Restrict (server-side
        # filter, MUCH faster than walking the full Inbox on a busy
        # mailbox). Optionally also matches by subject substring, so
        # only replies to our Phase 1 outgoing mail show up — not every
        # .xlsx in the department's inbox for the last 14 days.
        try:
            items.Sort("[ReceivedTime]", True)  # True = descending
            cutoff = datetime.now() - timedelta(days=max(since_days, 1))
            restriction = _build_restrict(cutoff, subject_contains)
            items = items.Restrict(restriction)
        except Exception as e:  # noqa: BLE001
            log.warning("outlook: Restrict failed (%s); falling back to unfiltered iter", e)

        out: list[OutlookMessage] = []
        for idx, item in enumerate(items):
            if idx >= max_messages:
                break
            try:
                msg = _wrap_message(item, only_xlsx=only_xlsx)
            except Exception as e:  # noqa: BLE001 — one bad message shouldn't kill the scan
                log.warning("outlook: skipped message #%d (%s)", idx, e)
                continue
            if msg is not None:
                out.append(msg)
        return out
    finally:
        pythoncom.CoUninitialize()


def _wrap_message(item, *, only_xlsx: bool) -> OutlookMessage | None:
    """Convert a COM MailItem to an OutlookMessage, or None if it has
    no qualifying attachments. Plays defensively with COM access — any
    property dereference can raise on a moved/deleted message."""
    try:
        # Non-mail items in the Inbox (meeting requests etc.) don't have
        # the properties we read below; skip them.
        olclass = getattr(item, "Class", 0)
        if olclass != 43:  # olMail
            return None
    except Exception:
        return None

    try:
        attachments_com = item.Attachments
    except Exception:
        return None

    wrapped_attachments: list[OutlookAttachment] = []
    for i in range(1, attachments_com.Count + 1):
        att = attachments_com.Item(i)
        try:
            name = str(att.FileName)
            size = int(getattr(att, "Size", 0))
        except Exception:
            continue
        if only_xlsx and not name.lower().endswith(".xlsx"):
            continue

        # Snapshot what we need; captured `att` keeps the COM ref live
        # for the lifetime of the closure.
        def _save(dest: Path, _att=att) -> None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _att.SaveAsFile(str(dest))

        wrapped_attachments.append(OutlookAttachment(
            name=name, size=size, _save_callback=_save,
        ))

    if not wrapped_attachments:
        return None

    received = getattr(item, "ReceivedTime", None)
    received_dt = _to_utc_datetime(received)

    return OutlookMessage(
        entry_id=str(getattr(item, "EntryID", "")),
        subject=str(getattr(item, "Subject", "")),
        sender_name=str(getattr(item, "SenderName", "")),
        sender_email=str(getattr(item, "SenderEmailAddress", "")),
        received_time=received_dt,
        attachments=wrapped_attachments,
    )


# ── Outgoing — create draft emails ────────────────────────────────
#
# `DraftSpec` and `DraftResult` moved into `email_client.py` once
# Thunderbird joined the family — both backends needed the same
# shape. We re-export them here so existing callers that imported
# `outlook.DraftSpec` keep working with a one-liner pivot to the
# dispatcher when they're ready.

from biracki_odbor.integrations.email_client import (  # noqa: E402,F401
    DraftResult, DraftSpec,
)


def create_drafts(
    drafts: list[DraftSpec],
    *,
    display_first: bool = True,
    display_all: bool = False,
) -> list[DraftResult]:
    """Create N Outlook drafts in one COM dispatch.

    The drafts land in the operator's Outlook Drafts folder; they are
    NOT sent automatically — the human stays in the loop.

    Args:
      display_first: pop up the first draft so the operator can review
        the template and confirm the send button is one click away.
      display_all: open every draft in its own compose window. Use
        sparingly — N parties × open windows can overwhelm.

    Raises:
      OutlookUnavailable: same contract as `fetch_inbox_messages` —
        non-Windows or no-pywin32. Callers guard on `OUTLOOK_AVAILABLE`
        first.

    Per-draft errors don't abort the batch — they're returned in the
    result list so the GUI can show "N succeeded, M failed" with
    specific reasons.
    """
    if not OUTLOOK_AVAILABLE:
        raise OutlookUnavailable(
            f"Outlook integration unavailable on this platform: {_IMPORT_ERR}"
        )

    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    results: list[DraftResult] = []
    try:
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
        except Exception as e:  # noqa: BLE001
            raise OutlookUnavailable(f"Cannot reach Outlook: {e}") from e

        for idx, spec in enumerate(drafts):
            try:
                # `CreateItem(0)` = `olMailItem`. Hard-coding avoids a
                # second Dispatch for constants on each call.
                item = outlook.CreateItem(0)
                item.To = spec.to or ""
                item.Subject = spec.subject or ""
                # `Body` is plain text; if you need HTML, switch to
                # `HTMLBody`. The operator can format manually after
                # the draft opens — keep this side dumb.
                item.Body = spec.body or ""
                if spec.attachment is not None:
                    item.Attachments.Add(str(Path(spec.attachment).resolve()))
                # `Save()` lands it in Drafts so the operator can find
                # the batch from one place even if no window is opened.
                item.Save()
                if display_all or (display_first and idx == 0):
                    # `Display()` is non-modal — opens the compose
                    # window and returns immediately so the rest of
                    # the loop can continue creating the other drafts.
                    item.Display(False)
                results.append(DraftResult(spec=spec, ok=True))
            except Exception as e:  # noqa: BLE001
                log.warning("outlook: cannot create draft to %s (%s)", spec.to, e)
                results.append(DraftResult(spec=spec, ok=False, error=str(e)))
    finally:
        pythoncom.CoUninitialize()
    return results


# ── Internal helpers ─────────────────────────────────────────────────


def _build_restrict(cutoff: datetime, subject_contains: str) -> str:
    """Assemble the MAPI Restrict expression for `fetch_inbox_messages`.

    Always includes the `[ReceivedTime] >= cutoff` clause. When
    `subject_contains` is non-empty, AND-joins a
    `[Subject] ci_phrasematch '<token>'` clause so the inbox scan
    drops anything that doesn't carry our outgoing subject rider.

    The date string format Outlook accepts is locale-dependent; we
    use the M/D/YYYY shape that's safest in MAPI Restrict filters
    regardless of UI locale. The subject value is single-quote-
    escaped (doubled) so a token with an apostrophe wouldn't break
    the filter syntax (today's tokens are bracket-wrapped digits, so
    this is belt-and-suspenders against future format changes).

    Extracted as a pure function so it can be unit-tested without
    spinning up Outlook COM.
    """
    parts = [
        f"[ReceivedTime] >= '{cutoff.strftime('%m/%d/%Y %I:%M %p')}'",
    ]
    if subject_contains:
        safe = subject_contains.replace("'", "''")
        parts.append(f"[Subject] ci_phrasematch '{safe}'")
    return " AND ".join(parts)


def _to_utc_datetime(value) -> datetime:
    """Convert an Outlook COM datetime to a tz-aware UTC datetime.

    pywintypes.datetime values implement the standard datetime
    interface but typically carry a local tzinfo. We normalize to UTC
    so downstream string formatting (`isoformat`, the filename token)
    is stable across timezones.

    Touching `.tzinfo` / `.astimezone()` on a `pywintypes.datetime`
    triggers a lazy `from win32 import win32timezone` that fails on
    pywin32 installs where the post-install step wasn't run (we've
    seen "No module named 'win32timezone'" in the wild). So we read
    the date/time fields directly and build a fresh stdlib datetime,
    attaching the OS's local tz via `datetime.now().astimezone()`.
    """
    if value is None:
        return datetime.now(timezone.utc)
    try:
        local_tz = datetime.now().astimezone().tzinfo
        local = datetime(
            value.year, value.month, value.day,
            value.hour, value.minute, value.second,
            getattr(value, "microsecond", 0),
            tzinfo=local_tz,
        )
        return local.astimezone(timezone.utc)
    except Exception:
        log.exception("outlook: cannot normalise ReceivedTime")
        return datetime.now(timezone.utc)
