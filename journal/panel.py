"""The edge panel: a place to put a thought without opening anything.

The panel deliberately does one thing. It does not show your standing notes,
it has no to-dos, and it never loads a model -- it reads and appends plain
text. Everything else lives in the journal window.
"""
from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.store import append_capture, entries, open_day
from journal.ui import INK, JOURNAL_DIR, PAPER


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
    def __init__(self, journal_dir: Path | None = None, day: Date | None = None):
        super().__init__()
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.day = day or datetime.now().date()

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
        append_capture(self.journal_dir, text, day=self.day)
        self.capture_box.clear()
        self.refresh()

    def refresh(self) -> None:
        page = open_day(self.journal_dir, "unknown", "unknown", self.day)
        self.list.clear()
        for entry in entries(page):
            stamp = f"{entry.at.hour:02d}:{entry.at.minute:02d}  " if entry.at else ""
            self.list.addItem(QListWidgetItem(f"{stamp}{entry.text}"))
        self.list.scrollToBottom()
