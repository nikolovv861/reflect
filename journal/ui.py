"""One page a day. You write down it; questions appear in the margin voice.

Deliberately NOT a chat. There is no transcript pane, no input box, no send.
Your words never leave the spot where you typed them -- that single property is
most of what separates a journal from a chatbot.
"""
from __future__ import annotations

import random
import sys
from datetime import date as Date
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.engine import DEFAULT_MODEL, DEFAULT_PROMPT, Engine, first_question
from journal.prompts import starters
from journal.store import QUESTION, WRITING, Block, Page, open_day, save

JOURNAL_DIR = Path.home() / "Documents" / "journal"

# Marks a paragraph as a question rather than the writer's own words. Lives on
# the block format so it survives editing and cannot bleed into typed text the
# way a character format would.
IS_QUESTION = QTextFormat.UserProperty + 1

# PySide6 wants a plain int for the line-height type, not the enum.
PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value

BODY_FONT = "Georgia"
BODY_SIZE = 14
INK = "#2b2b33"
QUESTION_INK = "#9a93b5"
PAPER = "#fdfcfa"


class AskWorker(QThread):
    token = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: Engine, page: Page):
        super().__init__()
        self._engine = engine
        self._page = page

    def run(self):
        try:
            accumulated = ""
            emitted = 0
            for tok in self._engine.ask(self._page):
                accumulated += tok
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
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        journal_dir: Path | None = None,
        day: Date | None = None,
    ):
        super().__init__()
        self.setWindowTitle("reflect")
        self.resize(720, 860)

        self.model_path = model_path
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.engine: Engine | None = None
        self.worker: AskWorker | None = None
        self._streaming = False

        self.page = open_day(self.journal_dir, model_path, DEFAULT_PROMPT, day)

        self.date_label = QLabel(self._date_heading())
        self.date_label.setStyleSheet(
            f"color:{QUESTION_INK}; font-family:{BODY_FONT}; font-size:12px;"
            " letter-spacing:2px;"
        )

        self.editor = QTextEdit()
        self.editor.setFrameStyle(0)
        self.editor.setFont(QFont(BODY_FONT, BODY_SIZE))
        self.editor.setStyleSheet(
            f"QTextEdit {{ background:{PAPER}; color:{INK}; border:none;"
            " selection-background-color:#ddd6f3; }}"
        )
        self.editor.document().setDocumentMargin(8)

        self.ask_button = QPushButton("Ask me something")
        self.ask_button.setMinimumHeight(38)
        self.ask_button.setCursor(Qt.PointingHandCursor)
        self.ask_button.clicked.connect(self.request_question)
        self.ask_button.setStyleSheet(
            "QPushButton { background:#7a6fa8; color:white; border:none;"
            " border-radius:6px; padding:8px 18px; font-size:13px; }"
            "QPushButton:hover { background:#8d82bb; }"
            "QPushButton:disabled { background:#cfcbdb; }"
        )

        self.counter = QLabel("")
        self.counter.setStyleSheet(f"color:{QUESTION_INK}; font-size:12px;")

        controls = QHBoxLayout()
        controls.addWidget(self.counter)
        controls.addStretch(1)
        controls.addWidget(self.ask_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(48, 28, 48, 20)
        layout.setSpacing(14)
        layout.addWidget(self.date_label)
        layout.addWidget(self.editor, 1)
        layout.addLayout(controls)

        container = QWidget()
        container.setStyleSheet(f"background:{PAPER};")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())

        QShortcut(QKeySequence("Ctrl+Return"), self, self.request_question)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_now)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.stop_generation)

        self._render_page()
        self.editor.textChanged.connect(self._update_counter)
        self._update_counter()

        # A journal must not lose work. Autosave rather than trusting the
        # writer to remember a shortcut.
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.save_now)
        self._autosave.start(20_000)

        self.editor.setFocus()

    # --- formatting -----------------------------------------------------

    def _date_heading(self) -> str:
        return self.page.day.strftime("%A, %d %B %Y").upper()

    def _writing_format(self) -> tuple[QTextBlockFormat, QTextCharFormat]:
        bf = QTextBlockFormat()
        bf.setProperty(IS_QUESTION, False)
        bf.setTopMargin(0)
        bf.setBottomMargin(10)
        bf.setLineHeight(150.0, PROPORTIONAL)
        cf = QTextCharFormat()
        cf.setFont(QFont(BODY_FONT, BODY_SIZE))
        cf.setForeground(QColor(INK))
        cf.setFontItalic(False)
        return bf, cf

    def _question_format(self) -> tuple[QTextBlockFormat, QTextCharFormat]:
        bf = QTextBlockFormat()
        bf.setProperty(IS_QUESTION, True)
        bf.setLeftMargin(24)
        bf.setTopMargin(10)
        bf.setBottomMargin(12)
        bf.setLineHeight(150.0, PROPORTIONAL)
        cf = QTextCharFormat()
        cf.setFont(QFont(BODY_FONT, BODY_SIZE - 1))
        cf.setForeground(QColor(QUESTION_INK))
        cf.setFontItalic(True)
        return bf, cf

    # --- rendering ------------------------------------------------------

    def _render_page(self) -> None:
        """Paint the stored page into the editor."""
        self.editor.blockSignals(True)
        self.editor.clear()
        cursor = self.editor.textCursor()
        first = True
        for block in self.page.blocks:
            bf, cf = (
                self._question_format()
                if block.kind == QUESTION
                else self._writing_format()
            )
            for line in block.text.split("\n"):
                if not first:
                    cursor.insertBlock()
                first = False
                cursor.setBlockFormat(bf)
                cursor.setCharFormat(cf)
                cursor.insertText(line)
        self.editor.blockSignals(False)

        if self.page.blocks:
            self._start_writing_block(cursor)
        else:
            bf, cf = self._writing_format()
            cursor.setBlockFormat(bf)
            cursor.setCharFormat(cf)
            self.editor.setTextCursor(cursor)
            self.editor.setCurrentCharFormat(cf)
            self.editor.setPlaceholderText(
                random.choice(starters()) + "\n\nStart writing…"
            )

    def _start_writing_block(self, cursor: QTextCursor) -> None:
        """Open a fresh, un-styled paragraph for the writer to continue in."""
        bf, cf = self._writing_format()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.block().text().strip() or cursor.block().blockFormat().property(
            IS_QUESTION
        ):
            cursor.insertBlock()
        cursor.setBlockFormat(bf)
        cursor.setCharFormat(cf)
        self.editor.setTextCursor(cursor)
        self.editor.setCurrentCharFormat(cf)

    # --- reading the document back --------------------------------------

    def harvest(self) -> list[Block]:
        """Read the editor back into blocks, using the per-paragraph marker."""
        blocks: list[Block] = []
        kind: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            if kind is None:
                return
            text = "\n".join(buffer).strip("\n")
            if text.strip():
                blocks.append(Block(kind, text))

        block = self.editor.document().begin()
        while block.isValid():
            line_kind = (
                QUESTION if block.blockFormat().property(IS_QUESTION) else WRITING
            )
            if line_kind != kind:
                flush()
                kind = line_kind
                buffer = [block.text()]
            else:
                buffer.append(block.text())
            block = block.next()
        flush()
        return blocks

    def _update_counter(self) -> None:
        self.page.blocks = self.harvest()
        words = self.page.words
        self.counter.setText(f"{words} words" if words else "")

    # --- actions --------------------------------------------------------

    def ensure_engine(self) -> Engine | None:
        if self.engine is not None:
            return self.engine
        self.statusBar().showMessage("Loading model…")
        QApplication.processEvents()
        try:
            self.engine = Engine(self.model_path, DEFAULT_PROMPT)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Model unavailable — {exc}")
            return None
        self.statusBar().clearMessage()
        return self.engine

    def request_question(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.page.blocks = self.harvest()
        if not self.page.words:
            self.statusBar().showMessage("Write something first.", 2500)
            return

        self.ask_button.setEnabled(False)
        self.ask_button.setText("Thinking…")
        self.save_now()

        engine = self.ensure_engine()
        if engine is None:
            self._reset_button()
            return

        self._streaming = False
        self.statusBar().showMessage("Thinking…")
        self.worker = AskWorker(engine, self.page)
        self.worker.token.connect(self.on_token)
        self.worker.finished_ok.connect(self.on_question)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

    def _open_question_block(self, cursor: QTextCursor) -> None:
        bf, cf = self._question_format()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.editor.document().lastBlock().text().strip():
            cursor.insertBlock()
        cursor.setBlockFormat(bf)
        cursor.setCharFormat(cf)

    def on_token(self, chunk: str) -> None:
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._streaming:
            self._streaming = True
            self._open_question_block(cursor)
        cursor.insertText(chunk)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def on_question(self, question: str) -> None:
        self.statusBar().clearMessage()
        self._reset_button()
        cursor = self.editor.textCursor()
        if not self._streaming:
            self._open_question_block(cursor)
            cursor.insertText(question)
        # Drop the writer straight back into their own voice, below the note.
        self._start_writing_block(cursor)
        self.save_now()
        self.editor.setFocus()

    def on_failure(self, message: str) -> None:
        self._reset_button()
        self.statusBar().showMessage(f"No question this time — {message}")

    def _reset_button(self) -> None:
        self.ask_button.setEnabled(True)
        self.ask_button.setText("Ask me something")

    def stop_generation(self) -> None:
        if self.engine and self.worker and self.worker.isRunning():
            self.engine.stop()
            self.statusBar().showMessage("Stopped.", 2000)

    def save_now(self) -> None:
        self.page.blocks = self.harvest()
        if not self.page.blocks:
            return
        try:
            save(self.page, self.journal_dir)
            self.statusBar().showMessage(f"Saved {datetime.now():%H:%M}", 1800)
        except OSError as exc:
            self.statusBar().showMessage(f"COULD NOT SAVE — {exc}")

    def closeEvent(self, event):
        self._autosave.stop()
        self.save_now()
        if self.worker and self.worker.isRunning():
            self.stop_generation()
            self.worker.wait(3000)
        if self.engine is not None:
            self.engine.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
