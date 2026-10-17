"""Tests for installer.scaffold (filesystem layout, upgrade preservation)."""

from __future__ import annotations

from pathlib import Path

from biracki_odbor.installer import scaffold


def test_fresh_install(tmp_path: Path) -> None:
    target = tmp_path / "install"
    result = scaffold.perform_scaffold(target, upgrade=False)
    for sub in scaffold.SUBDIRS:
        assert (target / sub).is_dir()
    # example configs should be copied
    assert (target / "oik_constants.json").exists()
    assert (target / "election_config.json").exists()
    assert (target / "УПУТСТВО.txt").exists()
    # Blank Stalni_sastav.xlsx must be dropped into sablon/
    blank = target / "sablon" / "Stalni_sastav.xlsx"
    assert blank.exists()
    assert blank.stat().st_size > 0
    # icon.ico must be copied so Windows can show it on the install folder
    assert (target / "icon.ico").exists()
    assert (target / "icon.ico").stat().st_size > 0
    assert result.preserved_files == []


def test_folder_icon_desktop_ini(tmp_path: Path) -> None:
    """Windows-only: desktop.ini wired up so Explorer renders the custom icon."""
    import os
    target = tmp_path / "install"
    scaffold.perform_scaffold(target, upgrade=False)
    if os.name != "nt":
        # On non-Windows the helper is a no-op by design; nothing to assert.
        return
    ini = target / "desktop.ini"
    assert ini.exists()
    content = ini.read_text(encoding="utf-8")
    assert "[.ShellClassInfo]" in content
    assert "IconResource=icon.ico" in content


def test_resolve_desktop_returns_path_or_none() -> None:
    """`_resolve_desktop` must always return Path | None — never crash."""
    from pathlib import Path
    result = scaffold._resolve_desktop()
    assert result is None or isinstance(result, Path)


def test_resolve_desktop_handles_missing_userprofile(monkeypatch) -> None:
    """If USERPROFILE is unset, fall through SH lookups gracefully."""
    monkeypatch.delenv("USERPROFILE", raising=False)
    # Should still not crash; result depends on the actual machine.
    result = scaffold._resolve_desktop()
    from pathlib import Path
    assert result is None or isinstance(result, Path)


def test_blank_template_is_readable_by_loader(tmp_path: Path) -> None:
    """The blank Stalni_sastav.xlsx must satisfy `read_template`'s structural checks."""
    from biracki_odbor.core.template import read_template

    target = tmp_path / "install"
    scaffold.perform_scaffold(target, upgrade=False)
    data, report = read_template(target / "sablon" / "Stalni_sastav.xlsx")
    # No structural errors (sheets present, headers found) — only NO_ALLOCATIONS
    # because the template is empty by design.
    error_codes = {i.code for i in report.errors}
    assert "HEADER_MISMATCH" not in error_codes
    assert "SHEET_MISSING" not in error_codes
    assert data.allocations == []


def test_upgrade_preserves_user_data(tmp_path: Path) -> None:
    target = tmp_path / "install"
    # First install
    scaffold.perform_scaffold(target, upgrade=False)
    # Simulate user editing config + adding correction log
    custom_cfg = '{"municipality": {"name": "Тест"}}'
    (target / "oik_constants.json").write_text(custom_cfg, encoding="utf-8")
    (target / "corrections.log").write_text("dummy\n", encoding="utf-8")
    drop_in_popunjeni = target / "popunjeni" / "СНС.xlsx"
    drop_in_popunjeni.write_bytes(b"fake xlsx")

    # Upgrade
    result = scaffold.perform_scaffold(target, upgrade=True)
    # User data must remain untouched
    assert (target / "oik_constants.json").read_text(encoding="utf-8") == custom_cfg
    assert (target / "corrections.log").exists()
    assert drop_in_popunjeni.exists()
    # And we should see it preserved
    preserved_names = {Path(p).name for p in result.preserved_files}
    assert "oik_constants.json" in preserved_names


def test_scaffold_bakes_licensing_url_on_fresh_install(
    tmp_path: Path, monkeypatch,
) -> None:
    """When LICENSING_SERVER_URL is non-blank, a fresh install must write
    app_settings.json with the URL already set."""
    import biracki_odbor._build_config as build_cfg
    monkeypatch.setattr(build_cfg, "LICENSING_SERVER_URL", "https://lic.example.com")

    target = tmp_path / "install"
    scaffold.perform_scaffold(target, upgrade=False)

    from biracki_odbor.config import settings as settings_mod
    s = settings_mod.load(target / "app_settings.json")
    assert s.licensing_server_url == "https://lic.example.com"


def test_scaffold_preserves_operator_prefs_on_reinstall(
    tmp_path: Path, monkeypatch,
) -> None:
    """Reinstall with a non-blank URL must update the URL field but leave
    other operator preferences (debug_logging, email_client) intact."""
    import biracki_odbor._build_config as build_cfg
    monkeypatch.setattr(build_cfg, "LICENSING_SERVER_URL", "https://lic.example.com")

    target = tmp_path / "install"
    # Pre-populate app_settings.json simulating a previous install
    from biracki_odbor.config import settings as settings_mod
    settings_mod.save(
        settings_mod.AppSettings(debug_logging=True, email_client="thunderbird"),
        target / "app_settings.json",
    )
    target.mkdir(parents=True, exist_ok=True)

    scaffold.perform_scaffold(target, upgrade=True)

    s = settings_mod.load(target / "app_settings.json")
    assert s.licensing_server_url == "https://lic.example.com"
    assert s.debug_logging is True
    assert s.email_client == "thunderbird"


def test_fresh_install_covers_both_workflows(tmp_path: Path) -> None:
    """Every directory for stalni AND prošireni AND posmatraci must exist after scaffold."""
    from biracki_odbor.core.workflow import all_specs
    target = tmp_path / "install"
    scaffold.perform_scaffold(target, upgrade=False)
    for spec in all_specs():
        p = spec.paths
        for subdir in (
            p.stranke_subdir,
            p.popunjeni_subdir,
            p.popunjeni_odbijeno_subdir,
            p.master_subdir,
            p.resenja_subdir,
            p.audit_subdir,
        ):
            assert (target / subdir).is_dir(), f"Missing dir for {spec.slug}: {subdir}"
    for nested in ("posmatraci", "posmatraci/liste", "posmatraci/legitimacije"):
        assert (target / nested).is_dir(), f"Missing posmatraci dir: {nested}"


def test_existing_install_detection(tmp_path: Path) -> None:
    info = scaffold.existing_install_info(tmp_path / "missing")
    assert not info["exists"]

    target = tmp_path / "install"
    scaffold.perform_scaffold(target, upgrade=False)
    info = scaffold.existing_install_info(target)
    assert info["exists"]
    assert "oik_constants.json" in info["preserved"]
