"""Tests for biracki_odbor.ssl_support — the shared TLS trust anchor.

Background: the update check (httpx, certifi-backed) succeeded on a
municipal PC while the download (bare urllib, Windows certificate store)
failed with CERTIFICATE_VERIFY_FAILED against the same host in the same
session. These tests pin the two properties that matter: certifi is used
when available, and the fallback never weakens verification.
"""

from __future__ import annotations

import logging
import ssl

import pytest


def test_the_context_verifies_and_carries_certificate_authorities() -> None:
    from biracki_odbor import ssl_support

    ctx = ssl_support.create_ssl_context()

    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.get_ca_certs(), "context must actually carry trust anchors"


def test_certifi_is_the_source_in_a_normal_environment() -> None:
    from biracki_odbor import ssl_support

    status = ssl_support.ca_bundle_status()

    assert status.is_bundled
    assert status.version
    assert status.path.endswith("cacert.pem") or status.path


def _clear_cache(monkeypatch) -> None:
    from biracki_odbor import ssl_support
    monkeypatch.setattr(ssl_support, "_context", None, raising=False)


def test_a_missing_certifi_still_verifies(monkeypatch, caplog) -> None:
    """The fallback is a real degradation — but it must degrade to the
    system trust store, never to no verification at all. What is being
    fetched is an installer that will then be executed."""
    from biracki_odbor import ssl_support

    _clear_cache(monkeypatch)
    monkeypatch.setattr(
        ssl_support, "ca_bundle_status",
        lambda: ssl_support.CaBundleStatus("system", "", "", "certifi not importable"),
    )

    with caplog.at_level(logging.WARNING):
        ctx = ssl_support.create_ssl_context()

    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert any("certifi" in r.message for r in caplog.records), "the fallback must be logged"


def test_a_missing_cacert_file_is_reported_as_system(monkeypatch, tmp_path) -> None:
    """A frozen build that lost cacert.pem must say so, because that is
    the silent cause of the download failure this module exists for."""
    from biracki_odbor import ssl_support

    import certifi
    monkeypatch.setattr(certifi, "where", lambda: str(tmp_path / "nope" / "cacert.pem"))

    status = ssl_support.ca_bundle_status()

    assert status.source == "system"
    assert not status.is_bundled
    assert "cacert.pem" in status.detail


def test_the_context_is_reused_rather_than_rebuilt(monkeypatch) -> None:
    """Building a context parses well over a hundred certificates, and
    both the check and the download ask for one."""
    from biracki_odbor import ssl_support

    _clear_cache(monkeypatch)

    assert ssl_support.create_ssl_context() is ssl_support.create_ssl_context()
