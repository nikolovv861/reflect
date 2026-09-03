"""One page a day, written inside a practice, beside notes you keep.

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
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
    Note,
    Page,
    list_notes,
    load,
    load_note,
    open_day,
    path_for,
    practice_day,
    recent_pages,
    save,
    save_note,
    search,
    seed_notes,
    slugify,
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
COLUMN_WIDTH = 660
SIDEBAR_WIDTH = 250

PAPER = "#fbf9f4"
SIDEBAR_BG = "#f4f1ea"
INK = "#33312c"
QUESTION_INK = "#8f86a8"
FAINT = "#a9a396"
ACCENT = "#7a6fa8"

PAGE, NOTE, HEADER, ACTION = "page", "note", "header", "action"


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
        self.resize(1120, 900)

        self.model_path = model_path
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.today = day or datetime.now().date()
        self.engine: Engine | None = None
        self.worker: AskWorker | None = None
        self._streaming = False

        self.mode = PAGE
        self.note: Note | None = None
        self.page = open_day(self.journal_dir, model_path, DEFAULT_PROMPT, day)
        self.practices = list_practices()
        seed_notes(self.journal_dir)

        self._build_ui()
        self._render_page()
        self._sync_practice_label()
        self.editor.textChanged.connect(self._on_text_changed)
        self._update_counter()
        self.refresh_sidebar()

        if not self.page.blocks:
            self._seed_opening()

        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self.save_now)
        self._autosave.start(20_000)

        self.editor.setFocus()

    # --- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        # --- sidebar ---
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setStyleSheet(
            f"QLineEdit {{ border:none; border-radius:5px; background:#eae6dc;"
            f" color:{INK}; padding:6px 9px; font-size:12px; }}"
        )
        self.search_box.textChanged.connect(self.refresh_sidebar)

        self.sidebar = QListWidget()
        self.sidebar.setStyleSheet(
            f"QListWidget {{ background:{SIDEBAR_BG}; border:none;"
            f" color:{INK}; font-size:12px; outline:none; }}"
            "QListWidget::item { padding:6px 8px; border-radius:5px; }"
            f"QListWidget::item:selected {{ background:#e2dcf1; color:{INK}; }}"
            "QListWidget::item:hover { background:#ece8e0; }"
        )
        self.sidebar.itemClicked.connect(self._on_sidebar_click)

        side = QVBoxLayout()
        side.setContentsMargins(14, 20, 10, 16)
        side.setSpacing(10)
        side.addWidget(self.search_box)
        side.addWidget(self.sidebar, 1)

        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_widget.setStyleSheet(f"background:{SIDEBAR_BG};")
        sidebar_widget.setLayout(side)

        # --- main column ---
        self.date_label = QLabel()
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
            " background:transparent; padding:2px 6px; }"
            "QComboBox::drop-down { border:none; width:16px; }"
            f"QComboBox QAbstractItemView {{ background:white; color:{INK};"
            " selection-background-color:#ece8f6; padding:4px; }"
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
            "QScrollBar::handle:vertical { background:#ddd8cc; border-radius:4px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height:0; }"
        )
        self.editor.document().setDocumentMargin(0)

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
        centred.setContentsMargins(24, 0, 24, 0)
        centred.addStretch(1)
        centred.addWidget(holder)
        centred.addStretch(1)

        main = QWidget()
        main.setStyleSheet(f"background:{PAPER};")
        main.setLayout(centred)

        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(sidebar_widget)
        outer.addWidget(main, 1)

        container = QWidget()
        container.setLayout(outer)
        self.setCentralWidget(container)
        self.setStatusBar(QStatusBar())
        self.statusBar().setStyleSheet(
            f"color:{FAINT}; font-size:11px; background:{PAPER};"
        )

        QShortcut(QKeySequence("Ctrl+Return"), self, self.request_question)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_now)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_box.setFocus)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_note)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.stop_generation)

        self._sync_header()

    # --- sidebar --------------------------------------------------------

    def _add_item(self, text: str, kind: str, key: str, selectable: bool = True):
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, (kind, key))
        if kind == HEADER:
            item.setFlags(Qt.NoItemFlags)
            font = item.font()
            font.setPointSize(8)
            font.setBold(True)
            item.setFont(font)
            item.setForeground(QColor(FAINT))
        elif not selectable:
            item.setFlags(Qt.NoItemFlags)
        self.sidebar.addItem(item)
        return item

    def refresh_sidebar(self) -> None:
        query = self.search_box.text().strip()
        self.sidebar.clear()

        if query:
            hits = search(self.journal_dir, query)
            self._add_item(
                f"  {len(hits)} RESULT{'S' if len(hits) != 1 else ''}", HEADER, ""
            )
            for hit in hits:
                self._add_item(f"{hit.title}\n{hit.snippet}", hit.kind, hit.key)
            if not hits:
                self._add_item("  nothing found", ACTION, "", selectable=False)
            return

        self._add_item("  JOURNAL", HEADER, "")
        pages = recent_pages(self.journal_dir)
        seen_today = any(p.day == self.today for p in pages)
        if not seen_today:
            self._add_item("Today", PAGE, self.today.isoformat())
        for page in pages:
            label = "Today" if page.day == self.today else page.day.strftime(
                "%a %d %b"
            )
            words = page.words
            self._add_item(
                f"{label}   ·   {words} words" if words else label,
                PAGE,
                page.day.isoformat(),
            )

        self._add_item("", HEADER, "")
        self._add_item("  NOTES", HEADER, "")
        for note in list_notes(self.journal_dir):
            self._add_item(note.title, NOTE, note.slug)
        self._add_item("+  New note", ACTION, "new-note")

        self._highlight_current()

    def _highlight_current(self) -> None:
        want = (
            (PAGE, self.page.day.isoformat())
            if self.mode == PAGE
            else (NOTE, self.note.slug if self.note else "")
        )
        for row in range(self.sidebar.count()):
            item = self.sidebar.item(row)
            if item.data(Qt.UserRole) == want:
                self.sidebar.setCurrentItem(item)
                return
        self.sidebar.clearSelection()

    def _on_sidebar_click(self, item: QListWidgetItem) -> None:
        kind, key = item.data(Qt.UserRole)
        if kind == ACTION and key == "new-note":
            self.new_note()
        elif kind == PAGE:
            self.open_page(Date.fromisoformat(key))
        elif kind == NOTE:
            self.open_note(key)

    # --- switching documents --------------------------------------------

    def _sync_header(self) -> None:
        if self.mode == PAGE:
            self.date_label.setText(self.page.day.strftime("%A, %d %B %Y").upper())
            self.practice_box.show()
            self.ask_button.show()
        else:
            self.date_label.setText((self.note.title if self.note else "").upper())
            self.practice_box.hide()
            self.arc_label.hide()
            # A note is a reference document, not a reflection surface.
            self.ask_button.hide()

    def open_page(self, day: Date) -> None:
        self.save_now()
        path = path_for(self.journal_dir, day)
        self.page = (
            load(path)
            if path.exists()
            else Page(day=day, model=self.model_path, prompt_version=DEFAULT_PROMPT)
        )
        self.mode = PAGE
        self.note = None
        self._sync_header()
        index = self.practice_box.findData(self.page.practice)
        self.practice_box.blockSignals(True)
        self.practice_box.setCurrentIndex(index if index >= 0 else 0)
        self.practice_box.blockSignals(False)
        self._render_page()
        self._sync_practice_label()
        self._update_counter()
        self._highlight_current()
        self.editor.setFocus()

    def open_note(self, slug: str) -> None:
        self.save_now()
        self.note = load_note(self.journal_dir, slug)
        self.mode = NOTE
        self._sync_header()
        self.editor.blockSignals(True)
        self.editor.clear()
        cursor = self.editor.textCursor()
        bf, cf = self._writing_format()
        cursor.setBlockFormat(bf)
        cursor.setCharFormat(cf)
        cursor.insertText(self.note.text)
        self.editor.blockSignals(False)
        self.editor.setTextCursor(cursor)
        self.editor.setCurrentCharFormat(cf)
        self.editor.setPlaceholderText("")
        self._update_counter()
        self._highlight_current()
        self.editor.setFocus()

    def new_note(self) -> None:
        title, ok = QInputDialog.getText(self, "New note", "Title:")
        if not ok or not title.strip():
            return
        note = Note(slug=slugify(title), title=title.strip(), text="")
        save_note(self.journal_dir, note)
        self.refresh_sidebar()
        self.open_note(note.slug)

    # --- practices ------------------------------------------------------

    @property
    def practice(self):
        return load_practice(self.page.practice)

    def _day_index(self) -> int:
        if self.practice.is_open_ended:
            return 0
        return practice_day(self.journal_dir, self.page.practice, self.page.day) - 1

    def _sync_practice_label(self) -> None:
        if self.mode != PAGE:
            self.arc_label.hide()
            return
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
        if not slug or self.mode != PAGE or slug == self.page.practice:
            return
        self.page.practice = slug
        if self.engine is not None:
            self.engine.set_practice(slug)
        self._sync_practice_label()
        self._seed_opening()
        self.save_now()

    def _seed_opening(self) -> None:
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

    def _on_text_changed(self) -> None:
        self._update_counter()

    def _update_counter(self) -> None:
        if self.mode == PAGE:
            self.page.blocks = self.harvest()
            words = self.page.words
        else:
            words = len(self.editor.toPlainText().split())
        self.counter.setText(f"{words} words" if words else "")

    # --- actions --------------------------------------------------------

    def standing_context(self) -> str:
        parts = [
            f"{n.title}: {n.text.strip()}"
            for n in list_notes(self.journal_dir)
            if n.text.strip()
        ]
        return "\n\n".join(parts)

    def ensure_engine(self) -> Engine | None:
        if self.engine is not None:
            return self.engine
        self.statusBar().showMessage("Loading model…")
        QApplication.processEvents()
        try:
            self.engine = Engine(self.model_path, DEFAULT_PROMPT, self.page.practice)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Model unavailable — {exc}")
            return None
        self.statusBar().clearMessage()
        return self.engine

    def request_question(self) -> None:
        if self.mode != PAGE or (self.worker and self.worker.isRunning()):
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
        engine.set_context(self.standing_context())

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
        try:
            if self.mode == NOTE and self.note is not None:
                self.note.text = self.editor.toPlainText()
                save_note(self.journal_dir, self.note)
            else:
                self.page.blocks = self.harvest()
                if not self.page.blocks:
                    return
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
