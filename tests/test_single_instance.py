"""TODO §21: a second launch asks the running copy to come forward
instead of opening another window."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from PySide6.QtTest import QTest

from biracki_odbor.gui.single_instance import InstanceServer, notify_running_instance, server_name


def test_no_running_copy_means_start_normally() -> None:
    assert notify_running_instance(f"oik-test-{uuid.uuid4().hex}", timeout_ms=100) is False


def test_second_launch_activates_the_running_copy() -> None:
    """The second launch is a separate process, as in real use."""
    name = f"oik-test-{uuid.uuid4().hex}"
    server = InstanceServer(name)
    fired: list[bool] = []
    server.activate_requested.connect(lambda: fired.append(True))
    code = (
        "import sys; from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]);"
        "from biracki_odbor.gui.single_instance import notify_running_instance;"
        f"sys.exit(0 if notify_running_instance({name!r}, timeout_ms=3000) else 1)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]))
    for _ in range(200):
        if fired and proc.poll() is not None:
            break
        QTest.qWait(25)
    assert proc.wait(timeout=10) == 0
    assert fired == [True]
    server.deleteLater()


def test_server_name_is_per_user_and_safe() -> None:
    n = server_name()
    assert n.startswith("OIK-BirackiOdbor-")
    assert all(c.isalnum() or c == "-" for c in n)
