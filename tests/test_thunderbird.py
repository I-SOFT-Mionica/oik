"""Tests for the Thunderbird send integration.

Real Thunderbird isn't on the CI runner (Ubuntu Semantic Release job
doesn't install it), so this file pins the deterministic surface:
binary discovery falls through cleanly when nothing is on PATH, the
compose-spec encoder handles tricky punctuation, and the dispatcher
in email_client.py picks the right backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from biracki_odbor.integrations import (
    email_client as ec_mod, thunderbird as tb_mod,
)
from biracki_odbor.integrations.email_client import (
    DraftSpec, EmailClient,
)


def test_find_thunderbird_returns_none_without_install(monkeypatch) -> None:
    """When neither PATH nor Program Files holds a thunderbird binary,
    `find_thunderbird_exe` must return None — the whole integration
    relies on that being the gating signal for THUNDERBIRD_AVAILABLE."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    # Force all candidate locations to point at empty dirs so the search
    # misses on Windows-like environments too — including per-user install.
    monkeypatch.setenv("ProgramFiles", "/tmp/nonexistent-progs")
    monkeypatch.setenv("ProgramFiles(x86)", "/tmp/nonexistent-progs-x86")
    monkeypatch.setenv("LOCALAPPDATA", "/tmp/nonexistent-localappdata")
    assert tb_mod.find_thunderbird_exe() is None


def test_encode_field_quotes_only_when_necessary() -> None:
    """Simple values should NOT be quoted — Thunderbird parses the
    bare form correctly and quoting adds visual noise to the CLI args.
    Commas and apostrophes are the two characters that DO require
    single-quote wrapping."""
    assert tb_mod._encode_field("alice@example.com") == "alice@example.com"
    assert tb_mod._encode_field("Simple subject") == "Simple subject"
    assert tb_mod._encode_field("Subject, with comma") == "'Subject, with comma'"
    # Apostrophes get doubled inside single-quoted form.
    assert tb_mod._encode_field("don't ship") == "'don''t ship'"


def test_build_compose_arg_includes_all_present_fields() -> None:
    """A draft with every field set must produce a single comma-
    separated key=value blob matching the Thunderbird CLI spec."""
    spec = DraftSpec(
        to="alice@example.com",
        subject="Hello",
        body="line one\nline two",
        attachment=Path(__file__).resolve(),
    )
    arg = tb_mod._build_compose_arg(spec)
    assert "to=alice@example.com" in arg
    assert "subject=Hello" in arg
    # Thunderbird 115+ stopped URL-decoding %0A in the body field.
    # The body is now single-quoted with literal newlines so the text
    # arrives in the compose window correctly.
    assert "body='line one\nline two'" in arg
    # Attachment must be a file:// URI so Thunderbird locates it
    # regardless of current working directory.
    assert "attachment=file:" in arg


def test_build_compose_arg_body_uses_single_quotes_with_literal_newlines() -> None:
    """Body is always single-quoted with literal newlines (Thunderbird 115+).

    Thunderbird 115+ (Supernova) no longer URL-decodes %0A or %2C in the
    body field — those characters appear literally in the compose window.
    The fix is single-quoting with literal newlines; commas are safe
    inside single-quoted body values because Thunderbird's compose-arg
    parser treats the entire single-quoted span as one field.
    """
    spec = DraftSpec(
        to="alice@example.com",
        subject="Test",
        body="Хвала,\nОИК",
        attachment=None,
    )
    arg = tb_mod._build_compose_arg(spec)
    # Single-quoted body with literal newline and comma — no URL-encoding.
    assert "body='Хвала,\nОИК'" in arg


def test_build_compose_arg_skips_empty_fields() -> None:
    """An empty `to` / `subject` / `body` shouldn't add a stray
    `key=` to the spec — Thunderbird interprets `to=` as a request
    to clear the recipient and then asks the user to pick one."""
    spec = DraftSpec(to="", subject="Only subject", body="", attachment=None)
    arg = tb_mod._build_compose_arg(spec)
    assert "to=" not in arg
    assert "subject=Only subject" in arg
    assert "body=" not in arg
    assert "attachment=" not in arg


def test_create_drafts_raises_when_thunderbird_missing(monkeypatch) -> None:
    """Direct calls to thunderbird.create_drafts must refuse cleanly
    when no binary was discovered — the GUI guards on the dispatcher
    so this exception is the belt-and-suspenders backstop."""
    monkeypatch.setattr(tb_mod, "THUNDERBIRD_AVAILABLE", False)
    monkeypatch.setattr(tb_mod, "_THUNDERBIRD_EXE", None)
    with pytest.raises(RuntimeError):
        tb_mod.create_drafts([DraftSpec(to="a@b.c", subject="s", body="b")])


# ── Dispatcher (email_client.resolve / create_drafts) ────────────


def test_resolve_returns_none_when_no_backend_available(monkeypatch) -> None:
    """If neither Outlook nor Thunderbird is detected, resolve must
    return None so callers can refuse and surface a clear message."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: False)
    assert ec_mod.resolve(EmailClient.AUTO) is None
    assert ec_mod.resolve(EmailClient.OUTLOOK) is None
    assert ec_mod.resolve(EmailClient.THUNDERBIRD) is None


def test_resolve_auto_prefers_outlook(monkeypatch) -> None:
    """When both backends exist + the operator picked AUTO, Outlook
    wins (Serbian OIK office standard)."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: True)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: True)
    assert ec_mod.resolve(EmailClient.AUTO) == EmailClient.OUTLOOK


def test_resolve_auto_falls_back_to_thunderbird(monkeypatch) -> None:
    """Auto with only Thunderbird installed must pick Thunderbird —
    no Outlook fallback when the binary isn't there."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: True)
    assert ec_mod.resolve(EmailClient.AUTO) == EmailClient.THUNDERBIRD


def test_resolve_pinned_outlook_falls_back_when_missing(monkeypatch) -> None:
    """Operator pinned Outlook but only Thunderbird is installed.
    Rather than refusing, the dispatcher falls back to Thunderbird
    and logs a warning — the alternative (silent failure) is worse
    operational behavior when the operator just wants their drafts."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: True)
    assert ec_mod.resolve(EmailClient.OUTLOOK) == EmailClient.THUNDERBIRD


def test_resolve_string_value_accepted(monkeypatch) -> None:
    """AppSettings stores the preference as a raw string; the
    dispatcher must accept that form so callers don't have to convert."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: True)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: False)
    assert ec_mod.resolve("outlook") == EmailClient.OUTLOOK
    assert ec_mod.resolve("auto") == EmailClient.OUTLOOK
    # Garbage string falls through to AUTO behavior.
    assert ec_mod.resolve("not-a-client") == EmailClient.OUTLOOK


def test_create_drafts_dispatches_to_thunderbird(monkeypatch) -> None:
    """End-to-end: when the dispatcher resolves to Thunderbird, the
    thunderbird backend's create_drafts must be the one actually
    invoked. Mock both backends so we don't launch real processes."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: True)
    called = {}

    def fake_create_drafts(drafts):
        called["thunderbird"] = drafts
        return []

    monkeypatch.setattr(tb_mod, "create_drafts", fake_create_drafts)
    spec = DraftSpec(to="x@y.z", subject="s", body="b")
    ec_mod.create_drafts([spec], preference=EmailClient.AUTO)
    assert "thunderbird" in called
    assert called["thunderbird"] == [spec]


def test_create_drafts_raises_when_no_backend(monkeypatch) -> None:
    """Belt-and-suspenders: if both backends vanish between the GUI's
    visibility check and the actual call (machine state changed), the
    dispatcher must raise EmailClientUnavailable rather than silently
    eating the drafts."""
    monkeypatch.setattr(ec_mod, "outlook_available", lambda: False)
    monkeypatch.setattr(ec_mod, "thunderbird_available", lambda: False)
    with pytest.raises(ec_mod.EmailClientUnavailable):
        ec_mod.create_drafts([DraftSpec(to="x", subject="s", body="b")])
