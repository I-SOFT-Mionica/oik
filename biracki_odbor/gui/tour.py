"""Guided tour: walks a new (usually demo) user through one full cycle on
their own RIK data, one spotlighted control at a time (TODO §33).

Each step names the widget to click and how the app reports the step as
done (a signal + condition). Navigation is generic: `reveal()` walks up
from the target selecting every tab / stack page on the way, so steps
never hardcode tab indices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QScrollArea, QStackedWidget, QTabWidget, QWidget

from biracki_odbor.gui.widgets.spotlight import SpotlightOverlay

log = logging.getLogger(__name__)


@dataclass
class TourStep:
    title: str
    text: str
    target: Callable[[], QWidget | None]
    # Signals that may complete the step; `done` decides. None = the
    # step is look-only and the callout shows a Next button.
    signals: tuple = ()
    done: Callable[[], bool] | None = None


def reveal(window, widget: QWidget) -> None:
    """Make `widget` visible: select each enclosing tab/stack page (the
    top-level section through the sidebar, so its highlight and unsaved-
    changes handling stay in sync) and scroll it into view."""
    child = widget
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QStackedWidget):
            idx = parent.indexOf(child)
            if idx >= 0 and parent.currentIndex() != idx:
                if parent is getattr(window, "stack", None):
                    window.sidebar.set_section(idx)
                else:
                    tabs = parent.parentWidget()
                    if isinstance(tabs, QTabWidget):
                        tabs.setCurrentIndex(idx)
                    else:
                        parent.setCurrentIndex(idx)
        if isinstance(parent, QScrollArea) and parent.widget() is not None:
            parent.ensureWidgetVisible(widget, 40, 40)
        child, parent = parent, parent.parentWidget()


class GuidedTour(QObject):
    finished = Signal(bool)  # True = completed, False = ended early

    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self.state = window.state
        self.overlay = SpotlightOverlay(window)
        self.overlay.skip_requested.connect(lambda: self._end(False))
        self.overlay.next_requested.connect(self._advance)
        self.steps = self._build_steps()
        self.i = -1
        self._connected: list = []
        self._snapshot: dict = {}

    # ── steps ───────────────────────────────────────────────────────

    def _tab(self, cls_name: str):
        tabs = self.w.tabs
        for k in range(tabs.count()):
            if type(tabs.widget(k)).__name__ == cls_name:
                return tabs.widget(k)
        return None

    def _build_steps(self) -> list[TourStep]:
        s = self.state
        gl = lambda: s.generation_log.stalni  # noqa: E731
        izborna = self.w.izborna_page
        p1 = lambda: self._tab("Phase1Tab")  # noqa: E731
        p2 = lambda: self._tab("Phase2Tab")  # noqa: E731
        p3 = lambda: self._tab("Phase3Tab")  # noqa: E731
        return [
            TourStep(
                self.tr("RIK allocation"),
                self.tr("Import the RIK РАСПОДЕЛА file you received for this election."
                   " Your polling stations, the parliamentary groups and who"
                   " proposes which seat are filled in from it."),
                lambda: izborna.btn_import_rik,
                signals=(s.template_changed,),
                done=lambda: bool(s.oik.polling_stations),
            ),
            TourStep(
                self.tr("Files for the parties"),
                self.tr("Generate one Excel file per party. In real use you send"
                   " them by email; parties fill in their people and send them"
                   " back. JMBG is checked while they type."),
                lambda: p1() and p1().btn_run,
                signals=(s.generation_log_changed,),
                done=lambda: gl().phase1_last != self._snapshot.get("phase1"),
            ),
            TourStep(
                self.tr("Sample submissions"),
                self.tr("Your parties sent their lists on paper or RIK forms this"
                   " time, so fill the files with fictional people instead."
                   " Two of them are deliberately proposed by two parties."),
                lambda: p2() and p2().btn_sample,
                signals=(p2().imported,) if p2() else (),
                done=lambda: True,
            ),
            TourStep(
                self.tr("Consolidation"),
                self.tr("Combine all submissions into one table. Mistakes and"
                   " conflicts are found here, before any decision exists."),
                lambda: p2() and p2().btn_run,
                signals=(s.master_changed,),
                done=lambda: True,
            ),
            TourStep(
                self.tr("Conflicts"),
                self.tr("The same person proposed by two parties is shown side by"
                   " side, with who submitted first. You decide who stays."),
                lambda: self.w.corrections_tab.conflicts_panel,
            ),
            TourStep(
                self.tr("Session"),
                self.tr("Enter the date and number of the session at which the"
                   " decisions are adopted."),
                lambda: p3() and p3().dt_session.parentWidget(),
            ),
            TourStep(
                self.tr("Decisions"),
                self.tr("Generate the decisions. In demo mode this is the decision"
                   " for your first polling station."),
                lambda: p3() and p3().btn_run,
                signals=(s.generation_log_changed,),
                done=lambda: gl().phase3_last != self._snapshot.get("phase3"),
            ),
            TourStep(
                self.tr("Done"),
                self.tr("Open the folder and look at the finished decision — your"
                   " municipality, your polling station, ready to sign."),
                lambda: p3() and p3().btn_open,
            ),
        ]

    # ── flow ────────────────────────────────────────────────────────

    def start(self) -> None:
        log.info("guided tour started")
        self.i = -1
        self._advance()

    def _advance(self) -> None:
        self._disconnect()
        self.i += 1
        if self.i >= len(self.steps):
            self._end(True)
            return
        step = self.steps[self.i]
        gl = self.state.generation_log.stalni
        self._snapshot = {"phase1": gl.phase1_last, "phase3": gl.phase3_last}
        target = step.target()
        if target is not None:
            reveal(self.w, target)
        last = self.i == len(self.steps) - 1
        self.overlay.show_step(
            target,
            step=self.tr("Step {n} of {total}").format(n=self.i + 1, total=len(self.steps)),
            title=step.title, text=step.text,
            next_label=(self.tr("Finish") if last else self.tr("Next →")) if not step.signals else None,
        )
        for sig in step.signals:
            sig.connect(self._on_signal)
            self._connected.append(sig)

    def _on_signal(self, *_args) -> None:
        step = self.steps[self.i]
        if step.done is None or step.done():
            # Let the step's own handlers (banners, tab unlocks) finish first.
            QTimer.singleShot(300, self._advance)
            self._disconnect()

    def _disconnect(self) -> None:
        for sig in self._connected:
            try:
                sig.disconnect(self._on_signal)
            except (RuntimeError, TypeError):
                pass
        self._connected = []

    def _end(self, completed: bool) -> None:
        self._disconnect()
        self.overlay.finish()
        log.info("guided tour %s at step %d", "completed" if completed else "ended", self.i + 1)
        self.finished.emit(completed)
