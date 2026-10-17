"""Tests for Thunderbird inbox parsing (Phase 2 receive side).

The CI runner has no Thunderbird and no profiles.ini, so these tests
construct their own profile directory layout + sample MBox files in
tmp_path, then point the discovery + parser at them via monkeypatch.

Three layers covered:
  - `_list_profiles` parses profiles.ini correctly (relative vs
    absolute paths, missing entries, malformed files),
  - `find_inbox_paths` walks Local Folders + ImapMail and returns
    every existing Inbox MBox file,
  - `fetch_inbox_messages` filters by date / subject / attachment
    type, decodes RFC 2047 headers, extracts attachments byte-for-byte.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from biracki_odbor.integrations import (
    email_client as ec_mod, thunderbird as tb_mod,
)
from biracki_odbor.integrations.email_client import EmailClient


# ── Helpers ───────────────────────────────────────────────────────


def _b64_xlsx_payload() -> str:
    """A 4-byte stand-in for a real .xlsx attachment.

    Real .xlsx is a ZIP starting with PK\x03\x04. The Phase 2 file
    safety pipeline checks the magic later; here we just need
    something base64-encodable to verify byte-for-byte extraction.
    """
    return base64.b64encode(b"PK\x03\x04hello").decode("ascii")


def _build_mbox_message(
    *,
    subject: str = "Стални састав — фајл за попуну (СНС)",
    sender: str = '"Странка СНС" <sns@example.rs>',
    date_offset_days: int = 1,
    attachment_filename: str | None = "СНС.xlsx",
    attachment_payload_b64: str | None = None,
) -> str:
    """Build a single MBox message string with optional attachment.

    Days are subtracted from now() so each message can be placed
    inside or outside the fetch cutoff window. RFC 5322 date format.
    """
    received = datetime.now(timezone.utc) - timedelta(days=date_offset_days)
    date_header = received.strftime("%a, %d %b %Y %H:%M:%S +0000")
    boundary = "===BOUNDARY==="
    text_part = (
        f"--{boundary}\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 7bit\n"
        "\n"
        "Поштовани, у прилогу је фајл.\n"
    )
    if attachment_filename and attachment_payload_b64 is None:
        attachment_payload_b64 = _b64_xlsx_payload()
    if attachment_filename and attachment_payload_b64:
        attachment_part = (
            f"--{boundary}\n"
            "Content-Type: application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet\n"
            "Content-Transfer-Encoding: base64\n"
            f'Content-Disposition: attachment; filename="{attachment_filename}"\n'
            "\n"
            f"{attachment_payload_b64}\n"
        )
    else:
        attachment_part = ""
    closing = f"--{boundary}--\n"
    body = text_part + attachment_part + closing
    return (
        f"From sns@example.rs {date_header}\n"
        f"Date: {date_header}\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Message-ID: <{date_offset_days}-{abs(hash(subject))}@example.rs>\n"
        "MIME-Version: 1.0\n"
        f'Content-Type: multipart/mixed; boundary="{boundary}"\n'
        "\n"
        f"{body}"
    )


def _make_inbox(tmp_path: Path, *messages: str) -> Path:
    """Write `messages` into an mbox file under tmp_path/Inbox."""
    inbox = tmp_path / "Inbox"
    inbox.write_text("\n".join(messages), encoding="utf-8")
    return inbox


# ── _list_profiles ────────────────────────────────────────────────


def test_list_profiles_handles_missing_ini(tmp_path: Path) -> None:
    """No profiles.ini → empty list. Pre-install / non-Thunderbird
    machines must NOT raise — they pass the test by returning []."""
    assert tb_mod._list_profiles(tmp_path) == []


def test_list_profiles_returns_relative_path(tmp_path: Path) -> None:
    """The common case: `IsRelative=1` profile path under the root."""
    prof = tmp_path / "Profiles" / "abc123.default"
    prof.mkdir(parents=True)
    (tmp_path / "profiles.ini").write_text(
        "[Profile0]\n"
        "Name=default\n"
        "IsRelative=1\n"
        f"Path=Profiles/{prof.name}\n"
        "Default=1\n",
        encoding="utf-8",
    )
    result = tb_mod._list_profiles(tmp_path)
    assert result == [prof]


def test_list_profiles_skips_missing_directories(tmp_path: Path) -> None:
    """A profiles.ini entry that points at a deleted folder must be
    skipped — not raised. Operators routinely orphan profiles by
    cleaning up by hand."""
    (tmp_path / "profiles.ini").write_text(
        "[Profile0]\n"
        "Name=ghost\n"
        "IsRelative=1\n"
        "Path=Profiles/never-existed\n",
        encoding="utf-8",
    )
    assert tb_mod._list_profiles(tmp_path) == []


# ── find_inbox_paths ──────────────────────────────────────────────


def test_find_inbox_paths_returns_both_local_and_imap(
    tmp_path: Path, monkeypatch,
) -> None:
    """Both Local Folders and ImapMail Inboxes contribute to the
    final list — multi-account operators see one combined view."""
    prof = tmp_path / "Profiles" / "abc123.default"
    prof.mkdir(parents=True)
    local_inbox = prof / "Mail" / "Local Folders" / "Inbox"
    local_inbox.parent.mkdir(parents=True)
    local_inbox.write_text("", encoding="utf-8")
    imap_inbox = prof / "ImapMail" / "imap.example.com" / "INBOX"
    imap_inbox.parent.mkdir(parents=True)
    imap_inbox.write_text("", encoding="utf-8")
    (tmp_path / "profiles.ini").write_text(
        "[Profile0]\n"
        "Name=default\n"
        "IsRelative=1\n"
        f"Path=Profiles/{prof.name}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tb_mod, "_thunderbird_appdata_root", lambda: tmp_path)
    found = tb_mod.find_inbox_paths()
    assert local_inbox in found
    assert imap_inbox in found


def test_find_inbox_paths_returns_empty_without_profile(
    tmp_path: Path, monkeypatch,
) -> None:
    """No appdata root → empty list, even when the binary exists.
    Required for `thunderbird_inbox_available()` to gate the button
    visibility correctly on a fresh Thunderbird install."""
    monkeypatch.setattr(tb_mod, "_thunderbird_appdata_root", lambda: None)
    assert tb_mod.find_inbox_paths() == []


# ── fetch_inbox_messages ──────────────────────────────────────────


def test_fetch_returns_messages_within_date_window(
    tmp_path: Path, monkeypatch,
) -> None:
    """A message dated 3 days ago must appear when since_days=14;
    a 30-day-old one must NOT."""
    recent = _build_mbox_message(
        subject="recent submission", date_offset_days=3,
    )
    old = _build_mbox_message(
        subject="too old", date_offset_days=30,
    )
    inbox = _make_inbox(tmp_path, recent, old)
    monkeypatch.setattr(tb_mod, "find_inbox_paths", lambda account_email="": [inbox])
    messages = tb_mod.fetch_inbox_messages(since_days=14)
    subjects = [m.subject for m in messages]
    assert "recent submission" in subjects
    assert "too old" not in subjects


def test_fetch_subject_contains_filter(tmp_path: Path, monkeypatch) -> None:
    """When `subject_contains` is set, messages without the token must
    be dropped — mirrors the MAPI Restrict on the Outlook side."""
    with_token = _build_mbox_message(
        subject="Стални састав [ОИК-20260615] (СНС)",
    )
    without_token = _build_mbox_message(
        subject="Random email about catering",
    )
    inbox = _make_inbox(tmp_path, with_token, without_token)
    monkeypatch.setattr(tb_mod, "find_inbox_paths", lambda account_email="": [inbox])
    messages = tb_mod.fetch_inbox_messages(
        subject_contains="[ОИК-20260615]",
    )
    assert len(messages) == 1
    assert "ОИК-20260615" in messages[0].subject


def test_fetch_extracts_attachment_bytes(tmp_path: Path, monkeypatch) -> None:
    """save_to must write the exact attachment bytes — the round-trip
    is the contract Phase 2's `popunjeni_io.import_file` relies on."""
    payload = base64.b64encode(b"PK\x03\x04inbox bytes").decode("ascii")
    msg = _build_mbox_message(attachment_payload_b64=payload)
    inbox = _make_inbox(tmp_path, msg)
    monkeypatch.setattr(tb_mod, "find_inbox_paths", lambda account_email="": [inbox])
    messages = tb_mod.fetch_inbox_messages(since_days=14)
    assert len(messages) == 1
    att = messages[0].attachments[0]
    out = tmp_path / "out" / "СНС.xlsx"
    att.save_to(out)
    assert out.read_bytes() == b"PK\x03\x04inbox bytes"


def test_fetch_drops_messages_without_xlsx_attachment(
    tmp_path: Path, monkeypatch,
) -> None:
    """A message with only a .pdf attachment must not surface — Phase 2
    only consumes .xlsx. The picker dialog would otherwise show rows
    the operator can't act on."""
    msg = _build_mbox_message(attachment_filename="invoice.pdf")
    inbox = _make_inbox(tmp_path, msg)
    monkeypatch.setattr(tb_mod, "find_inbox_paths", lambda account_email="": [inbox])
    messages = tb_mod.fetch_inbox_messages(since_days=14)
    assert messages == []


def test_fetch_returns_empty_when_no_inboxes(monkeypatch) -> None:
    """No discovered inbox files → empty list (NOT exception). The
    dispatcher decides whether to refuse based on
    `any_inbox_available`; the per-backend function returns gracefully."""
    monkeypatch.setattr(tb_mod, "find_inbox_paths", lambda account_email="": [])
    assert tb_mod.fetch_inbox_messages() == []


# ── Dispatcher (email_client.fetch_inbox_messages) ────────────────


def test_dispatcher_routes_to_thunderbird(monkeypatch) -> None:
    """When the dispatcher resolves to Thunderbird, the thunderbird
    backend's fetch_inbox_messages must be the one actually invoked."""
    monkeypatch.setattr(ec_mod, "outlook_inbox_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_inbox_available", lambda: True)
    called = {}

    def fake_fetch(**kwargs):
        called.update(kwargs)
        return []

    monkeypatch.setattr(tb_mod, "fetch_inbox_messages", fake_fetch)
    ec_mod.fetch_inbox_messages(
        preference=EmailClient.AUTO,
        since_days=7, subject_contains="x",
    )
    # Args were forwarded.
    assert called == {
        "since_days": 7, "only_xlsx": True,
        "max_messages": 200, "subject_contains": "x",
        "account_email": "",
    }


def test_dispatcher_raises_when_no_inbox_backend(monkeypatch) -> None:
    """Belt-and-suspenders: backend disappearing between visibility
    check and call must raise rather than silently no-op."""
    monkeypatch.setattr(ec_mod, "outlook_inbox_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_inbox_available", lambda: False)
    with pytest.raises(ec_mod.InboxBackendUnavailable):
        ec_mod.fetch_inbox_messages()


def test_resolve_inbox_falls_back_when_pinned_unavailable(monkeypatch) -> None:
    """Operator pinned Outlook but only Thunderbird has an inbox.
    Falls back to Thunderbird and logs — same policy as send-side."""
    monkeypatch.setattr(ec_mod, "outlook_inbox_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_inbox_available", lambda: True)
    assert ec_mod.resolve_inbox(EmailClient.OUTLOOK) == EmailClient.THUNDERBIRD
