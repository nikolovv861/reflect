"""One page a day, written inside a practice.

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
    QComboBox,
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
from journal.practices import DEFAULT as DEFAULT_PRACTICE
from journal.practices import list_practices, load_practice
from journal.prompts import starters
from journal.store import (
    QUESTION,
    WRITING,
    Block,
    Page,
    open_day,
    practice_day,
    save,
)

JOURNAL_DIR = Path.home() / "Documents" / "journal"

# Marks a paragraph as a question rather than the writer's own words. Lives on
# the block format so it survives editing and cannot bleed into typed text the
# way a character format would.
IS_QUESTION = QTextFormat.UserProperty + 1

# PySide6 wants a plain int for the line-height type, not the enum.
PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value

BODY_FONT = "Georgia"
BODY_SIZE = 15
LINE_HEIGHT = 165.0
# A readable measure is roughly 65 characters. Full-bleed text is the single
# most common reason a writing app is unpleasant to read in.
COLUMN_WIDTH = 660

PAPER = "#fbf9f4"
INK = "#33312c"
QUESTION_INK = "#8f86a8"
FAINT = "#a9a396"
ACCENT = "#7a6fa8"


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
        self.resize(940, 900)

        self.model_path = model_path
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.engine: Engine | None = None
        self.worker: AskWorker | None = None
        self._streaming = False

        self.page = open_day(self.journal_dir, model_path, DEFAULT_PROMPT, day)
        self.practices = list_practices()

        self._build_ui()
        self._render_page()
        self._sync_practice_label()
        self.editor.textChanged.connect(self._update_counter)
        self._update_counter()

        if not self.page.blocks:
            self._seed_opening()

        # A journal must not lose work. Autosave rather than trusting the
        # writer to remember a shortcut.
        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.save_now)
        self._autosave.start(20_000)

        self.editor.setFocus()

    # --- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        self.date_label = QLabel(self.page.day.strftime("%A, %d %B %Y").upper())
        self.date_label.setStyleSheet(
            f"color:{FAINT}; font-family:{BODY_FONT}; font-size:11px;"
            " letter-spacing:2px;"
        )

        self.practice_box = QComboBox()
        for practice in self.practices:
            self.practice_box.addItem(practice.name, practice.slug)
        index = self.practice_box.findData(self.page.practice)
        self.practice_box.setCurrentIndex(index if index >= 0 else 0)
        self.practice_box.setCursor(Qt.PointingHandCursor)
        self.practice_box.setStyleSheet(
            f"QComboBox {{ border:none; color:{ACCENT}; font-size:12px;"
            f" background:transparent; padding:2px 6px; }}"
            f"QComboBox::drop-down {{ border:none; width:16px; }}"
            f"QComboBox QAbstractItemView {{ background:white; color:{INK};"
            f" selection-background-color:#ece8f6; padding:4px; }}"
        )
        self.practice_box.currentIndexChanged.connect(self._on_practice_changed)

        header = QHBoxLayout()
        header.addWidget(self.date_label)
        header.addStretch(1)
        header.addWidget(self.practice_box)

        self.arc_label = QLabel("")
        self.arc_label.setStyleSheet(
            f"color:{FAINT}; font-size:11px; letter-spacing:1px;"
        )

        self.editor = QTextEdit()
        self.editor.setFrameStyle(0)
        self.editor.setFont(QFont(BODY_FONT, BODY_SIZE))
        self.editor.setStyleSheet(
            f"QTextEdit {{ background:{PAPER}; color:{INK}; border:none;"
            " selection-background-color:#e3ddf3; }}"
            "QScrollBar:vertical { background:transparent; width:8px; }"
            f"QScrollBar::handle:vertical {{ background:#ddd8cc;"
            " border-radius:4px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height:0; }"
        )
        self.editor.document().setDocumentMargin(0)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.ask_button = QPushButton("Ask me something")
        self.ask_button.setMinimumHeight(38)
        self.ask_button.setCursor(Qt.PointingHandCursor)
        self.ask_button.clicked.connect(self.request_question)
        self.ask_button.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:white; border:none;"
            " border-radius:6px; padding:8px 20px; font-size:13px; }"
            "QPushButton:hover { background:#8d82bb; }"
            "QPushButton:disabled { background:#d5d1c6; }"
        )

        self.counter = QLabel("")
        self.counter.setStyleSheet(f"color:{FAINT}; font-size:11px;")

        controls = QHBoxLayout()
        controls.addWidget(self.counter)
        controls.addStretch(1)
        controls.addWidget(self.ask_button)

        column = QVBoxLayout()
        column.setContentsMargins(0, 36, 0, 24)
        column.setSpacing(10)
        column.addLayout(header)
        column.addWidget(self.arc_label)
        column.addSpacing(14)
        column.addWidget(self.editor, 1)
        column.addSpacing(8)
        column.addLayout(controls)

        holder = QWidget()
        holder.setMaximumWidth(COLUMN_WIDTH)
        holder.setLayout(column)

        centred = QHBoxLayout()
        centred.setContentsMargins(0, 0, 0, 0)
        centred.addStretch(1)
        centred.addWidget(holder)
        centred.addStretch(1)

        container = QWidget()
        container.setStyleSheet(f"background:{PAPER};")
        container.setLayout(centred)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.statusBar().setStyleSheet(
            f"color:{FAINT}; font-size:11px; background:{PAPER};"
        )

        QShortcut(QKeySequence("Ctrl+Return"), self, self.request_question)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_now)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.stop_generation)

    # --- practices ------------------------------------------------------

    @property
    def practice(self):
        return load_practice(self.page.practice)

    def _day_index(self) -> int:
        if self.practice.is_open_ended:
            return 0
        return practice_day(self.journal_dir, self.page.practice, self.page.day) - 1

    def _sync_practice_label(self) -> None:
        practice = self.practice
        if practice.is_open_ended or practice.arc == 1:
            self.arc_label.setText("")
            self.arc_label.hide()
            return
        day = self._day_index() + 1
        self.arc_label.setText(
            f"{practice.name.upper()} · DAY {min(day, practice.arc)} OF {practice.arc}"
        )
        self.arc_label.show()

    def _on_practice_changed(self, _index: int) -> None:
        slug = self.practice_box.currentData()
        if not slug or slug == self.page.practice:
            return
        self.page.practice = slug
        if self.engine is not None:
            self.engine.set_practice(slug)
        self._sync_practice_label()
        self._seed_opening()
        self.save_now()

    def _seed_opening(self) -> None:
        """Put the practice's prompt on the page so it is never blank."""
        opening = self.practice.opening_for(self._day_index())
        if not opening:
            self.editor.setPlaceholderText(
                random.choice(starters()) + "\n\nStart writing…"
            )
            return
        cursor = self.editor.textCursor()
        self._open_question_block(cursor)
        cursor.insertText(opening)
        self._start_writing_block(cursor)
        self.editor.setFocus()

    # --- formatting -----------------------------------------------------

    def _writing_format(self) -> tuple[QTextBlockFormat, QTextCharFormat]:
        bf = QTextBlockFormat()
        bf.setProperty(IS_QUESTION, False)
        bf.setTopMargin(0)
        bf.setBottomMargin(12)
        bf.setLineHeight(LINE_HEIGHT, PROPORTIONAL)
        cf = QTextCharFormat()
        cf.setFont(QFont(BODY_FONT, BODY_SIZE))
        cf.setForeground(QColor(INK))
        cf.setFontItalic(False)
        return bf, cf

    def _question_format(self) -> tuple[QTextBlockFormat, QTextCharFormat]:
        bf = QTextBlockFormat()
        bf.setProperty(IS_QUESTION, True)
        bf.setLeftMargin(26)
        bf.setTopMargin(14)
        bf.setBottomMargin(16)
        bf.setLineHeight(LINE_HEIGHT, PROPORTIONAL)
        cf = QTextCharFormat()
        cf.setFont(QFont(BODY_FONT, BODY_SIZE - 1))
        cf.setForeground(QColor(QUESTION_INK))
        cf.setFontItalic(True)
        return bf, cf

    # --- rendering ------------------------------------------------------

    def _render_page(self) -> None:
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

    def _open_question_block(self, cursor: QTextCursor) -> None:
        bf, cf = self._question_format()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.editor.document().lastBlock().text().strip():
            cursor.insertBlock()
        cursor.setBlockFormat(bf)
        cursor.setCharFormat(cf)

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
            self.engine = Engine(
                self.model_path, DEFAULT_PROMPT, self.page.practice
            )
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
        if engine.practice != self.page.practice:
            engine.set_practice(self.page.practice)

        self._streaming = False
        self.statusBar().showMessage("Thinking…")
        self.worker = AskWorker(engine, self.page)
        self.worker.token.connect(self.on_token)
        self.worker.finished_ok.connect(self.on_question)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

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
