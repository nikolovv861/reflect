"""A text area, a key, and one question back."""
from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.engine import DEFAULT_MODEL, DEFAULT_PROMPT, Engine, first_question
from journal.prompts import starters
from journal.store import Session, Turn, save

JOURNAL_DIR = Path.home() / "Documents" / "journal"


class AskWorker(QThread):
    """Generation off the UI thread, so typing never blocks on the model."""

    token = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: Engine, session: Session):
        super().__init__()
        self._engine = engine
        self._session = session

    def run(self):
        try:
            accumulated = ""
            emitted = 0
            for tok in self._engine.ask(self._session):
                accumulated += tok
                # Only ever show text up to the first question mark, so a
                # rambling second question never flashes on screen before
                # being truncated away.
                visible = first_question(accumulated)
                if len(visible) > emitted:
                    self.token.emit(visible[emitted:])
                    emitted = len(visible)
                if "?" in accumulated:
                    self._engine.stop()
                    break
            self.finished_ok.emit(first_question(accumulated))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self, model_path: str = DEFAULT_MODEL):
        super().__init__()
        self.setWindowTitle("reflect")
        self.resize(760, 820)

        self.model_path = model_path
        self.session = Session(
            started=datetime.now(),
            model=model_path,
            prompt_version=DEFAULT_PROMPT,
            turns=[],
        )
        self.engine: Engine | None = None
        self.worker: AskWorker | None = None
        self._streaming_started = False

        self.transcript = QTextEdit(readOnly=True)
        self.transcript.setFrameStyle(0)
        self.editor = QPlainTextEdit()
        self.editor.setFrameStyle(0)
        self.editor.setPlaceholderText(
            "Write. Ctrl+Enter when you want a question."
        )

        body = QFont("Georgia", 13)
        for widget in (self.transcript, self.editor):
            widget.setFont(body)

        self.hint = QLabel("Ctrl+Enter — ask · Ctrl+S — save · Esc — stop")
        self.hint.setEnabled(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)
        layout.addWidget(self.transcript, 3)
        layout.addWidget(self.editor, 2)
        layout.addWidget(self.hint)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

        QShortcut(QKeySequence("Ctrl+Return"), self, self.request_question)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_now)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.stop_generation)

        self.append_turn("ai", random.choice(starters()))
        self.editor.setFocus()

    # --- transcript -----------------------------------------------------

    def _format(self, is_question: bool) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setFont(QFont("Georgia", 13))
        if is_question:
            fmt.setFontItalic(True)
            fmt.setForeground(QColor("#7a6fa8"))
        return fmt

    def _write(self, text: str, is_question: bool, new_block: bool) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if new_block and self.transcript.toPlainText():
            cursor.insertBlock()
            cursor.insertBlock()
        cursor.setCharFormat(self._format(is_question))
        cursor.insertText(text)
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def _record(self, speaker: str, text: str) -> None:
        self.session.turns.append(Turn(speaker, text))

    def append_turn(self, speaker: str, text: str) -> None:
        self._write(text, speaker == "ai", new_block=True)
        self._record(speaker, text)

    # --- actions --------------------------------------------------------

    def ensure_engine(self) -> Engine | None:
        if self.engine is not None:
            return self.engine
        self.statusBar().showMessage("Loading model (first run downloads ~2.5GB)…")
        QApplication.processEvents()
        try:
            self.engine = Engine(self.model_path, self.session.prompt_version)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Model unavailable — {exc}")
            return None
        self.statusBar().clearMessage()
        return self.engine

    def request_question(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text or (self.worker and self.worker.isRunning()):
            return

        self.append_turn("me", text)
        self.editor.clear()
        self.save_now()

        engine = self.ensure_engine()
        if engine is None:
            return

        self.statusBar().showMessage("Thinking…")
        self._streaming_started = False
        self.worker = AskWorker(engine, self.session)
        self.worker.token.connect(self.on_token)
        self.worker.finished_ok.connect(self.on_question)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

    def on_token(self, chunk: str) -> None:
        first = not self._streaming_started
        self._streaming_started = True
        self._write(chunk, is_question=True, new_block=first)

    def on_question(self, question: str) -> None:
        self.statusBar().clearMessage()
        if not self._streaming_started:
            self.append_turn("ai", question)
        else:
            self._record("ai", question)
        self.save_now()
        self.editor.setFocus()

    def on_failure(self, message: str) -> None:
        self.statusBar().showMessage(f"No question this time — {message}")

    def stop_generation(self) -> None:
        if self.engine and self.worker and self.worker.isRunning():
            self.engine.stop()
            self.statusBar().showMessage("Stopped.", 2000)

    def save_now(self) -> None:
        if not self.session.turns:
            return
        try:
            path = save(self.session, JOURNAL_DIR)
            self.statusBar().showMessage(f"Saved {path.name}", 2000)
        except OSError as exc:
            self.statusBar().showMessage(f"COULD NOT SAVE — {exc}")

    def closeEvent(self, event):
        pending = self.editor.toPlainText().strip()
        if pending:
            self.append_turn("me", pending)
        self.save_now()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
