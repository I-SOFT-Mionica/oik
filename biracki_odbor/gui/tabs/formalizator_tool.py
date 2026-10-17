"""Алати → Formalizator: start the companion app, or fetch its installer.

Formalizator fills official forms from an ID card. It is a separate
product with its own installer; this tab only locates it, starts it, or
offers the download when it is missing — so an operator who needs it does
not have to be talked through finding a link over the phone.

Download mechanics mirror `about_page`'s update flow (DownloadWorker plus
a GUI-thread QTimer polling plain attributes — packaged builds silently
drop cross-thread Signal.emit from a QThread, see updates.py). The one
thing deliberately *not* copied is the QApplication.quit() at the end:
OIK quits for its own installer because that installer replaces the
running exe. Formalizator's writes to a different folder entirely and
never touches OIK.exe, so OIK keeps running.
"""

from __future__ import annotations

import logging
import subprocess
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from biracki_odbor.gui.app_state import AppState
from biracki_odbor.integrations import formalizator_app
from biracki_odbor.updates import TLS_ERROR_MARKER, DownloadWorker

log = logging.getLogger(__name__)

_POLL_MS = 250
_MB = 1024 * 1024


class FormalizatorPage(QWidget):
    """Launch-or-install panel for the Formalizator companion app."""

    def __init__(self, state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._install: formalizator_app.FormalizatorInstall | None = None
        self._worker: DownloadWorker | None = None
        self._timer: QTimer | None = None
        self._last_bytes = 0
        self._stall_since = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel("Formalizator")
        title.setStyleSheet("font-size:17px;font-weight:600;")
        root.addWidget(title)

        blurb = QLabel(self.tr(
            "Companion application for filling official forms from an ID"
            " card — used for collecting voter support signatures."
        ))
        blurb.setWordWrap(True)
        blurb.setObjectName("MutedLabel")
        root.addWidget(blurb)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        buttons = QHBoxLayout()
        self.btn_launch = QPushButton(self.tr("Start Formalizator"))
        self.btn_launch.setObjectName("PrimaryButton")
        self.btn_launch.clicked.connect(self._on_launch)
        buttons.addWidget(self.btn_launch)

        self.btn_install = QPushButton(self.tr("Download and install"))
        self.btn_install.clicked.connect(self._on_install)
        buttons.addWidget(self.btn_install)
        buttons.addStretch()
        root.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.progress)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("MutedLabel")
        self.lbl_progress.setVisible(False)
        root.addWidget(self.lbl_progress)

        root.addStretch()
        self.refresh()

    # ── State ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-probe the machine and reshape the panel around the answer."""
        self._install = formalizator_app.find_install()
        installed = self._install is not None

        self.btn_launch.setVisible(installed)
        self.btn_install.setVisible(True)
        self.btn_install.setText(
            self.tr("Reinstall") if installed else self.tr("Download and install")
        )
        self.btn_install.setObjectName("" if installed else "PrimaryButton")

        if installed:
            where = str(self._install.base_dir)
            version = f" ({self._install.version})" if self._install.version else ""
            self.lbl_status.setText(
                self.tr("Installed{version} — {path}").format(version=version, path=where)
            )
        else:
            self.lbl_status.setText(
                self.tr("Not installed on this computer. The installer is about 200 MB.")
            )

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        """Re-probe on every visit, so the panel flips to "installed" as
        soon as the wizard finishes — without restarting OIK."""
        super().showEvent(event)
        if self._worker is None:
            self.refresh()

    # ── Launch ───────────────────────────────────────────────────────

    def _on_launch(self) -> None:
        if self._install is None:
            self.refresh()
            return
        try:
            formalizator_app.launch(self._install)
        except OSError as exc:
            log.exception("could not start Formalizator")
            self.lbl_status.setText(
                self.tr("Could not start Formalizator: {error}").format(error=exc)
            )
            return
        self.lbl_status.setText(self.tr("Formalizator started."))

    # ── Install ──────────────────────────────────────────────────────

    def _server_url(self) -> str:
        url = (self._state.app_settings.licensing_server_url or "").strip()
        if url:
            return url
        try:
            from biracki_odbor import _build_config
            return str(getattr(_build_config, "LICENSING_SERVER_URL", "") or "").strip()
        except ImportError:
            return ""

    def _on_install(self) -> None:
        server = self._server_url()
        if not server:
            # Dev builds have no server baked in; say so plainly rather
            # than failing on an empty URL.
            self.lbl_status.setText(self.tr(
                "No update server is configured in this build, so the"
                " installer cannot be fetched automatically."
            ))
            return

        self.btn_install.setEnabled(False)
        self.btn_launch.setEnabled(False)
        self.lbl_status.setText(self.tr("Looking up the current version…"))

        from biracki_odbor.licensing import server_client
        try:
            manifest = server_client.fetch_release_manifest(server)
        except Exception as exc:  # noqa: BLE001 — any lookup failure is the same to the operator
            log.warning("Formalizator: release lookup failed: %s", exc)
            self._fail(self.tr(
                "Could not reach the server to look up the current version."
            ))
            return

        url = formalizator_app.installer_url(manifest.download_url, server, manifest.tag)
        if not url:
            self._fail(self.tr("The server did not report a download address."))
            return

        log.info("Formalizator: downloading %s", url)
        self.lbl_status.setText(
            self.tr("Downloading Formalizator {tag}…").format(tag=manifest.tag)
        )
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setText("")

        self._last_bytes = 0
        self._stall_since = time.monotonic()
        from biracki_odbor.updates import cleanup_stale_installer_downloads
        cleanup_stale_installer_downloads()
        self._worker = DownloadWorker(url, self)
        self._worker.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_download)
        self._timer.start(_POLL_MS)

    def _stall_timeout_seconds(self) -> int:
        return int(getattr(self._state.app_settings, "worker_stall_timeout_seconds", 180) or 0)

    def _poll_download(self) -> None:
        """Attributes, not signals — see the module docstring."""
        worker = self._worker
        if worker is None:
            return

        done, total = worker.bytes_downloaded, worker.bytes_total
        if done != self._last_bytes:
            self._last_bytes = done
            self._stall_since = time.monotonic()
            self._on_progress(done, total)

        if not worker.isRunning():
            self._timer.stop()
            if worker.error:
                self._on_failed(worker.error)
            elif worker.result_path:
                self._on_finished(worker.result_path)
            else:
                self._on_failed(self.tr("The download was interrupted."))
            return

        timeout = self._stall_timeout_seconds()
        if timeout and time.monotonic() - self._stall_since > timeout:
            self._timer.stop()
            log.error("Formalizator download stalled at %d/%d bytes", done, total)
            self._on_failed(self.tr("The download stalled — the server is not responding."))

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
            self.lbl_progress.setText(f"{done / _MB:.1f} MB / {total / _MB:.1f} MB")
        else:
            self.progress.setRange(0, 0)  # indeterminate — no Content-Length
            self.lbl_progress.setText(f"{done / _MB:.1f} MB")

    def _on_finished(self, path: str) -> None:
        self._worker = None
        self.progress.setVisible(False)
        self.lbl_progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_launch.setEnabled(True)
        try:
            subprocess.Popen([path])  # noqa: S603 — the installer we just downloaded
        except OSError as exc:
            log.exception("could not start the Formalizator installer")
            self.lbl_status.setText(
                self.tr("Could not start the installer: {error}").format(error=exc)
            )
            return
        # No QApplication.quit() here, unlike the OIK self-update: this
        # installer writes to its own folder and never replaces OIK.exe.
        self.lbl_status.setText(
            self.tr("The installer has started — follow the wizard. This window stays open.")
        )

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self.progress.setVisible(False)
        self.lbl_progress.setVisible(False)
        self._fail(self._humanise(message))

    def _humanise(self, message: str) -> str:
        """Turn a transport error into something worth reading.

        404 is the expected answer until the companion installer is
        published to the server, so it gets its own sentence rather than
        an HTTP code the operator cannot act on."""
        if message.startswith(TLS_ERROR_MARKER):
            return self.tr(
                "This computer did not accept the server's certificate, so"
                " the download failed. See Diagnostics on the About page."
            )
        if "404" in message:
            return self.tr(
                "The Formalizator installer is not available on the server"
                " yet. Please contact support to obtain it."
            )
        return self.tr("Download failed: {error}").format(error=message)

    def _fail(self, text: str) -> None:
        self.btn_install.setEnabled(True)
        self.btn_launch.setEnabled(True)
        self.lbl_status.setText(text)
