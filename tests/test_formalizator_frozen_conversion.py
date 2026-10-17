"""Tests for the frozen-build conversion path.

A PyInstaller exe has no `-m`, and `sys.executable` is the application
itself — so spawning the converter the dev-mode way would relaunch the
whole GUI instead of converting anything.
"""

from __future__ import annotations

import subprocess
import sys

from formalizator.core import pdf_template


def _captured_popen(monkeypatch) -> list:
    calls = []

    class _FakePopen:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))

    monkeypatch.setattr(pdf_template.subprocess, "Popen", _FakePopen)
    return calls


def test_dev_mode_spawns_the_module(monkeypatch, tmp_path) -> None:
    calls = _captured_popen(monkeypatch)
    monkeypatch.delattr(sys, "frozen", raising=False)

    pdf_template.start_conversion_process(tmp_path / "in.docx", tmp_path / "out.pdf")

    command = calls[0][0]
    assert command[1] == "-m"
    assert command[2] == "formalizator.core.pdf_template"


def test_frozen_build_reenters_itself_with_a_flag(monkeypatch, tmp_path) -> None:
    """The bug this guards: `[sys.executable, "-m", ...]` in a frozen
    build relaunches the GUI, so the operator sees a second window
    appear instead of their document converting."""
    calls = _captured_popen(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    pdf_template.start_conversion_process(tmp_path / "in.docx", tmp_path / "out.pdf")

    command = calls[0][0]
    assert "-m" not in command
    assert command[1] == pdf_template.CONVERT_FLAG
    assert command[2].endswith("in.docx")
    assert command[3].endswith("out.pdf")


def test_conversion_child_gets_no_console_window(monkeypatch, tmp_path) -> None:
    """Otherwise every conversion flashes a black console box over the
    operator's screen."""
    calls = _captured_popen(monkeypatch)

    pdf_template.start_conversion_process(tmp_path / "in.docx", tmp_path / "out.pdf")

    kwargs = calls[0][1]
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_entry_point_runs_the_conversion_instead_of_the_gui(monkeypatch, tmp_path) -> None:
    """The flag has to be handled before any Qt object is created."""
    import formalizator.__main__ as entry

    converted = []
    monkeypatch.setattr(
        "formalizator.core.pdf_template.export_to_pdf",
        lambda src, out: converted.append((src, out)),
    )

    def _no_gui():  # pragma: no cover — reaching this is the failure
        raise AssertionError("the GUI was started for a conversion invocation")

    monkeypatch.setattr(entry.QApplication, "instance", staticmethod(_no_gui))
    monkeypatch.setattr(
        sys, "argv",
        ["Formalizator.exe", pdf_template.CONVERT_FLAG, str(tmp_path / "a.docx"), str(tmp_path / "b.pdf")],
    )

    try:
        entry.main()
    except SystemExit as exit_code:
        assert exit_code.code == 0

    assert len(converted) == 1
