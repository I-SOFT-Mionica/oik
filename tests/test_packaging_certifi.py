"""The CA bundle must survive packaging.

If certifi's cacert.pem is missing from the frozen build the app falls
back to the Windows certificate store — silently, and only on the
packaged exe, which is exactly where it was never noticed. These are
cheap guards so a future spec edit cannot drop it unremarked.
"""

from __future__ import annotations

import pathlib


def test_the_certifi_bundle_exists_and_holds_certificates() -> None:
    import certifi

    bundle = pathlib.Path(certifi.where())

    assert bundle.is_file()
    assert "BEGIN CERTIFICATE" in bundle.read_text(encoding="utf-8", errors="ignore")


def test_the_spec_collects_certifi_explicitly() -> None:
    """PyInstaller's contrib hook-certifi should handle this on its own,
    but that was never verified on a real packaged exe and the failure
    mode is silent — so the spec states it outright."""
    spec = pathlib.Path("OIK.spec").read_text(encoding="utf-8")

    assert "collect_data_files('certifi')" in spec, "cacert.pem must be bundled"
    assert "'certifi'," in spec, "certifi must be a hidden import"


def test_certifi_is_a_direct_dependency() -> None:
    """Relying on httpx pulling it in transitively means a future httpx
    change could quietly remove the app's trust anchor."""
    pyproject = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")

    assert "certifi>=" in pyproject
