"""The edge panel: a place to put a thought without opening anything.

The panel deliberately does one thing. It does not show your standing notes,
it has no to-dos, and it never loads a model -- it reads and appends plain
text. Everything else lives in the journal window.
"""
from __future__ import annotations

import weakref
from datetime import date as Date
from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QRect, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.geometry import collapsed_rect, expanded_rect
from journal.settings import load_settings, resolve_screen
from journal.store import append_capture, entries, open_day
from journal.ui import INK, JOURNAL_DIR, PAPER, Window


class CaptureBox(QTextEdit):
    """Enter saves, Shift+Enter makes a new line."""

    def __init__(self, on_commit):
        super().__init__()
        self._on_commit = on_commit
        self.setPlaceholderText("a thought…")
        self.setFixedHeight(64)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if enter and not (event.modifiers() & Qt.ShiftModifier):
            self._on_commit()
            return
        super().keyPressEvent(event)


class Panel(QWidget):
    # Emitted around the append, so whoever else may be holding the same page
    # can hand it over and take it back. See PanelWindow.__init__ for why the
    # order of these two matters.
    about_to_commit = Signal()
    committed = Signal()

    def __init__(self, journal_dir: Path | None = None, day: Date | None = None):
        super().__init__()
        self.journal_dir = journal_dir or JOURNAL_DIR
        # Kept as given -- None means "whatever day it is when you look". The
        # panel runs for weeks under autostart, so a date resolved once in
        # __init__ would freeze it on its construction day and quietly append
        # tonight's thoughts to a page from last Tuesday.
        self._day = day
        self._build()

    @property
    def day(self) -> Date:
        """The day being written to right now."""
        return self._day or datetime.now().date()

    def _build(self) -> None:
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)

        self.capture_box = CaptureBox(self.commit)
        self.open_button = QPushButton("open journal  ›")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.capture_box)
        layout.addWidget(self.open_button)

        self.setStyleSheet(
            f"QWidget {{ background:{PAPER}; color:{INK}; font-size:12px; }}"
            f"QListWidget {{ border:none; }}"
            f"QTextEdit {{ border:1px solid #e0dbd0; border-radius:5px; padding:5px; }}"
            f"QPushButton {{ border:none; padding:6px; text-align:left; }}"
        )

        self.refresh()

    def commit(self) -> None:
        text = self.capture_box.toPlainText().strip()
        if not text:
            return
        day = self.day
        self.about_to_commit.emit()
        append_capture(self.journal_dir, text, day=day)
        self.capture_box.clear()
        self.refresh()
        self.committed.emit()

    def refresh(self) -> None:
        page = open_day(self.journal_dir, "unknown", "unknown", self.day)
        self.list.clear()
        for entry in entries(page):
            stamp = f"{entry.at.hour:02d}:{entry.at.minute:02d}  " if entry.at else ""
            self.list.addItem(QListWidgetItem(f"{stamp}{entry.text}"))
        self.list.scrollToBottom()


SLIDE_MS = 150
RETRACT_DELAY_MS = 400


class PanelWindow(QWidget):
    """The panel's home: frameless, always on top, resting at a screen edge."""

    def __init__(self, journal_dir: Path | None = None, day: Date | None = None):
        super().__init__()
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.settings = load_settings(self.journal_dir)

        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        # Sliding out must never steal focus from whatever is being typed in.
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.panel = Panel(journal_dir=self.journal_dir, day=day)
        self.day = day
        self.journal: Window | None = None
        self.panel.open_button.clicked.connect(self.open_journal)

        # One owner of the page at a time. The journal window saves by
        # overwriting the whole file from its own in-memory blocks, so if a
        # capture were appended while the window still held unflushed content,
        # the window's next save would silently destroy it. Hence the fixed
        # order: flush the window to disk FIRST, then the capture lands on top
        # of flushed content, then the window re-reads what is now on disk.
        # Flushing after the append would reintroduce exactly that bug.
        self.panel.about_to_commit.connect(self._flush_journal)
        self.panel.committed.connect(self._reload_journal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.panel)
        # The layout's minimum size (driven by the capture box and the
        # "open journal" button) would otherwise pin this window far wider
        # than the resting tab -- the collapsed strip must be able to shrink
        # past what its contents need, since nothing in it is legible at
        # TAB width anyway.
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumWidth(0)
        self.panel.setMinimumWidth(0)

        self.setMouseTracking(True)
        self._expanded = False
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(SLIDE_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        # A pointer crossing the edge on its way elsewhere should not make the
        # panel flap open and shut.
        self._retract = QTimer(self)
        self._retract.setSingleShot(True)
        self._retract.setInterval(RETRACT_DELAY_MS)
        self._retract.timeout.connect(self.collapse)

        self.setGeometry(QRect(*self._rect(expanded=False)))

        # Qt.Tool keeps this window out of the taskbar and out of Alt-Tab, and
        # the process outlives the journal window, so without this there is no
        # way to stop the panel short of Task Manager.
        self.quit_action = QAction("Quit", self)
        self.quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.quit_action.triggered.connect(self.quit)
        self.addAction(self.quit_action)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)

    def quit(self) -> None:
        """Stop the panel process."""
        QApplication.quit()

    # --- placement ------------------------------------------------------

    def _screen_rect(self) -> tuple[int, int, int, int]:
        screens = QGuiApplication.screens()
        index = resolve_screen(self.settings, len(screens))
        available = screens[index].availableGeometry()
        return (
            available.x(),
            available.y(),
            available.width(),
            available.height(),
        )

    def _rect(self, expanded: bool) -> tuple[int, int, int, int]:
        screen = self._screen_rect()
        edge = self.settings.edge
        return expanded_rect(screen, edge) if expanded else collapsed_rect(screen, edge)

    def _slide_to(self, expanded: bool) -> None:
        self._expanded = expanded
        self._animation.stop()
        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(QRect(*self._rect(expanded)))
        self._animation.start()

    def expand(self) -> None:
        self._retract.stop()
        if not self._expanded:
            self._slide_to(True)

    def collapse(self) -> None:
        if not self._expanded:
            return
        # A blocked retract that never retries leaves the panel stuck open
        # forever, since nothing else re-arms the single-shot timer -- so
        # re-check on the same interval until both guards clear.
        if self.panel.capture_box.hasFocus() or self.underMouse():
            self._retract.start()
            return
        self._slide_to(False)

    # --- hover ----------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        # NOT redundant with collapse()'s re-arm: this is the only thing that
        # arms the timer from rest, so the panel would never retract without
        # it. Leave it unconditional.
        self._retract.start()
        super().leaveEvent(event)

    # --- journal handoff --------------------------------------------------

    def open_journal(self) -> None:
        """Build the journal window, or raise the one already open.

        The model is not loaded here -- `Window.ensure_engine()` still defers
        that to the first question, so opening the journal stays cheap.
        """
        if self.journal is None:
            # The panel's resolved day, not the day this window was built on:
            # with no explicit day those differ the moment midnight passes.
            self.journal = Window(journal_dir=self.journal_dir, day=self.panel.day)
            self.journal.setAttribute(Qt.WA_DeleteOnClose)
            weak_self = weakref.ref(self)

            def _on_destroyed(_obj=None):
                inst = weak_self()
                if inst is not None:
                    inst._journal_closed()

            self.journal.destroyed.connect(_on_destroyed)
        self.journal.show()
        self.journal.raise_()
        self.journal.activateWindow()
        self.collapse()

    def _flush_journal(self) -> None:
        """Give the page back to disk before a capture is appended to it."""
        if self._journal_alive():
            self.journal.save_now()

    def _reload_journal(self) -> None:
        """Show the open window the capture that just landed underneath it."""
        if self._journal_alive():
            self.journal.reload_from_disk()

    def _journal_alive(self) -> bool:
        return self.journal is not None and shiboken6.isValid(self.journal)

    def _journal_closed(self, _obj=None) -> None:
        """Forget the window, so its Engine -- and the model -- can be freed.

        Qt passes the destroyed QObject as an argument; accept and ignore it.
        """
        self.journal = None
        # The weakref in open_journal() only proves the Python PanelWindow is
        # still alive; it says nothing about its C++ side. On app quit with
        # the journal still open, the panel's widgets are torn down first and
        # the journal's `destroyed` fires afterwards -- refreshing then hits
        # `RuntimeError: Internal C++ object already deleted`. So check C++
        # liveness as well before touching any widget.
        if shiboken6.isValid(self) and shiboken6.isValid(self.panel):
            self.panel.refresh()


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="reflect-panel")
    parser.add_argument(
        "--autostart",
        choices=("on", "off", "status"),
        help="start the panel when Windows starts",
    )
    args = parser.parse_args()

    if args.autostart:
        from journal import autostart

        # autostart imports winreg lazily, inside each function -- so the
        # failure lands here, not on the import above, and a bare traceback
        # is not an answer to "can I have this on Linux".
        try:
            if args.autostart == "on":
                autostart.enable()
            elif args.autostart == "off":
                autostart.disable()
            print("autostart:", "on" if autostart.is_enabled() else "off")
        except ModuleNotFoundError:
            print("autostart is Windows-only")
            return 2
        return 0

    app = QApplication(sys.argv)
    # The journal window closing must not end the process -- the panel is
    # still resting at the edge.
    app.setQuitOnLastWindowClosed(False)
    window = PanelWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
