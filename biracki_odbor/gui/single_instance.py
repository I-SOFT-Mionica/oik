"""One running copy per user (TODO §21).

Double-clicking the shortcut while OIK is already open used to start a
second copy -- two windows writing the same data. Now the new launch
asks the running copy (over a per-user local socket) to come to the
front and exits.
"""

from __future__ import annotations

import getpass
import logging
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

_MESSAGE = b"activate"


def server_name() -> str:
    user = "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
    return f"OIK-BirackiOdbor-{user}"


def notify_running_instance(name: str | None = None, timeout_ms: int = 400) -> bool:
    """True if another copy is running (it has been asked to come forward)."""
    sock = QLocalSocket()
    sock.connectToServer(name or server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    if sys.platform == "win32":
        # Windows only lets the foreground process hand focus over; we are
        # that process right now (the user just launched us).
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:  # noqa: BLE001
            pass
    sock.write(_MESSAGE)
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    log.info("another OIK instance is running; asked it to activate")
    return True


class InstanceServer(QObject):
    activate_requested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        name = name or server_name()
        QLocalServer.removeServer(name)  # stale endpoint after a crash
        if not self._server.listen(name):
            log.warning("single-instance server not listening: %s", self._server.errorString())
        self._server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_read(s))
            sock.disconnected.connect(sock.deleteLater)
            # The sender writes and disconnects at once, so the message is
            # often already buffered before readyRead is connected.
            if sock.bytesAvailable():
                self._on_read(sock)

    def _on_read(self, sock: QLocalSocket) -> None:
        if bytes(sock.readAll()).startswith(_MESSAGE):
            self.activate_requested.emit()


def bring_to_front(window) -> None:
    if window.isMinimized():
        window.showMaximized()
    window.show()
    window.raise_()
    window.activateWindow()
