"""One page a day, written inside a practice, beside notes you keep.

Deliberately NOT a chat. There is no transcript pane, no input box, no send.
Your words never leave the spot where you typed them -- that single property is
most of what separates a journal from a chatbot.
"""
from __future__ import annotations

import html
import os
import random
import re
import sys
from datetime import date as Date
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
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
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.engine import DEFAULT_MODEL, DEFAULT_PROMPT, Engine, first_question
from journal.epigraphs import for_day as epigraph_for_day
from journal.export import export_all, write_export
from journal.review import PRACTICE as REVIEW_PRACTICE
from journal.review import EVENING_PRACTICE, GUIDED
from journal.review import (
    extract_turn,
    followup_page,
    needs_followup,
    next_index,
    progress_label,
)
from journal.review import questions as review_questions
from journal.review import turns as review_turns
from journal.review import unanswered as review_unanswered
from journal.year import year_records
from journal.yearpage import YearSummary, aggregate, render_html, render_markdown
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
    on_this_day,
    open_day,
    path_for,
    practice_day,
    practice_history,
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

# Marks a paragraph as a not-yet-accepted suggestion. harvest() skips these, so
# a suggestion is never saved or counted until you accept it and it becomes
# ordinary writing.
IS_GHOST = QTextFormat.UserProperty + 2

# PySide6 wants a plain int for the line-height type, not the enum.
PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value

# Below this, a 4B model has nothing concrete to grab and falls back to
# feelings-fishing -- so we gently ask for a little more instead of asking badly.
MIN_ASK_WORDS = 15

BODY_FONT = "Georgia"
BODY_SIZE = 15
LINE_HEIGHT = 165.0
COLUMN_WIDTH = 660
SIDEBAR_WIDTH = 250

# Parchment & Ink -- a warm, classical palette. Paper is a real parchment
# tone, the accent a muted bronze rather than the old plum.
PAPER = "#f7f1e3"
SIDEBAR_BG = "#efe7d4"
INK = "#3a3226"
QUESTION_INK = "#9c7b45"
FAINT = "#b0a488"
ACCENT = "#8a7b4e"
# Soft parchment tint used to highlight things (a selection, the phrase a
# question points at). The everyday "marked" colour of this palette.
TINT = "#efe0c0"
BORDER = "#e3d8bf"
# The buried phrase a question points at -- tinted in your own writing so you
# can see at a glance what it noticed. Display only; never saved to disk.
TARGET_INK = "#b5623f"
# A provisional suggestion in your voice, before you accept or dismiss it.
GHOST_INK = "#c3b591"


def _quoted_phrase(text: str) -> str:
    """The phrase a question quotes back, straight or curly quotes. '' if none."""
    match = re.search(r"[\"“]([^\"”“]{3,}?)[\"”]", text)
    return match.group(1).strip() if match else ""

PAGE, NOTE, HEADER, ACTION = "page", "note", "header", "action"
YEAR = "year"


class YearWorker(QThread):
    """Extracts any not-yet-cached days on the local model, off the UI thread."""

    progress = Signal(int, int)
    done = Signal()
    failed = Signal(str)

    def __init__(self, engine: Engine, journal_dir: Path):
        super().__init__()
        self._engine = engine
        self._dir = journal_dir

    def run(self):
        try:
            year_records(self._dir, self._engine, on_progress=self.progress.emit)
            self.done.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class PortraitWorker(QThread):
    """Writes the reading -- eight grounded sections -- off the UI thread."""

    progress = Signal(int, int)
    done = Signal(object)  # Portrait
    failed = Signal(str)

    def __init__(self, journal_dir: Path, engine: Engine, page: Page, script: list[str]):
        super().__init__()
        self._dir = journal_dir
        self._engine = engine
        self._page = page
        self._script = script

    def run(self):
        try:
            from journal.portrait import portrait_for

            self.done.emit(
                portrait_for(self._dir, self._engine, self._page, self._script,
                             on_progress=self.progress.emit)
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class DeepWorker(QThread):
    """Writes the deep reading -- a read of each answer, then a letter -- off the
    UI thread, when someone presses 'Go deeper'."""

    progress = Signal(int, int)
    done = Signal(object)  # Deep
    failed = Signal(str)

    def __init__(self, journal_dir: Path, engine: Engine, page: Page,
                 script: list[str], portrait: object):
        super().__init__()
        self._dir = journal_dir
        self._engine = engine
        self._page = page
        self._script = script
        self._portrait = portrait

    def run(self):
        try:
            from journal.portrait import deep_for

            self.done.emit(
                deep_for(self._dir, self._engine, self._page, self._script,
                         self._portrait, on_progress=self.progress.emit)
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class ReviewWorker(QThread):
    """Reads each answered review question on the local model, off the UI thread."""

    progress = Signal(int, int)
    done = Signal(object)  # list[Record]
    failed = Signal(str)

    def __init__(self, engine: Engine, page: Page, script: list[str], directory: Path | None = None):
        super().__init__()
        self._engine = engine
        self._page = page
        self._script = script
        self._dir = directory

    def run(self):
        try:
            if self._dir is not None:
                from journal.review import review_records_cached

                found = review_records_cached(self._dir, self._engine, self._page,
                                              self._script, on_progress=self.progress.emit)
            else:
                found = []
                all_turns = review_turns(self._page, self._script)
                for i, turn in enumerate(all_turns):
                    record = extract_turn(self._engine, turn, self._page.day)
                    if record is not None:
                        found.append(record)
                    self.progress.emit(i + 1, len(all_turns))
            self.done.emit(found)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class AskWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: Engine, page: Page, history=(), avoid=()):
        super().__init__()
        self._engine = engine
        self._page = page
        self._history = history
        self._avoid = avoid

    def run(self):
        try:
            # Best-of-N rather than one streamed shot: we would rather show one
            # good question a beat later than stream a weak one live.
            self.finished_ok.emit(
                self._engine.ask_best_of(self._page, self._history, avoid=self._avoid)
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class SuggestWorker(QThread):
    """Runs one style-matched continuation off the UI thread."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: Engine, page: Page, history=()):
        super().__init__()
        self._engine = engine
        self._page = page
        self._history = history

    def run(self):
        try:
            self.done.emit(self._engine.suggest(self._page, self._history))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.failed.emit(str(exc))


class WarmupWorker(QThread):
    """Loads the model -- and pays the one-time shader compile -- off the UI
    thread, so the first real 'Ask' is fast instead of a ~25s cold start.

    Emits the ready engine, or None if the model is missing or fails. Warming
    up must never get in the way of writing, so every failure here is silent.
    """

    ready = Signal(object)

    def __init__(self, model_path: str, practice: str):
        super().__init__()
        self._model_path = model_path
        self._practice = practice

    def run(self):
        try:
            engine = Engine(self._model_path, DEFAULT_PROMPT, self._practice)
            try:
                # A throwaway question forces the one-time Vulkan/Metal shader
                # compile now. Its output is discarded; the engine is stateless.
                warm_page = Page(
                    day=Date.min,
                    model=self._model_path,
                    prompt_version=DEFAULT_PROMPT,
                    blocks=[Block(WRITING, "Warming up.")],
                )
                engine.ask_text(warm_page)
            except Exception:  # noqa: BLE001 - warming is best-effort
                pass
            self.ready.emit(engine)
        except Exception:  # noqa: BLE001 - never let warm-up surface an error
            self.ready.emit(None)


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
        self._warmup: WarmupWorker | None = None
        self._suggester: SuggestWorker | None = None
        self._year_worker: YearWorker | None = None
        self._review_worker: ReviewWorker | None = None
        self._portrait_worker: PortraitWorker | None = None
        self._deep_worker: DeepWorker | None = None
        self._portrait = None
        self._deep = None
        self._review_session: Page | None = None
        self._year_summary: YearSummary = YearSummary()
        self._streaming = False
        self._highlight: tuple[int, int] | None = None
        self._sealed = False  # an evening review closed with "Seal the day"
        self._ghost: int | None = None  # anchor of a pending suggestion, or None
        self._last_q: str | None = None  # the question just shown, for re-roll

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

        self._start_warmup()
        self.editor.setFocus()

    def _start_warmup(self) -> None:
        # Only for a real model. A stub path ("model://…", used in tests) would
        # just fail to load, so skip it and keep the suite quiet and fast.
        if not self.model_path or self.model_path.startswith("model://"):
            return
        self._warmup = WarmupWorker(self.model_path, self.page.practice)
        self._warmup.ready.connect(self._on_warm)
        self._warmup.start()

    def _on_warm(self, engine) -> None:
        if engine is None:
            return
        if self.engine is None:
            self.engine = engine
        else:
            # A real engine was already built (the user asked during warm-up).
            engine.close()

    # --- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        # --- sidebar ---
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setStyleSheet(
            f"QLineEdit {{ border:none; border-radius:5px; background:#e6dcc3;"
            f" color:{INK}; padding:6px 9px; font-size:12px; }}"
        )
        self.search_box.textChanged.connect(self.refresh_sidebar)

        self.sidebar = QListWidget()
        self.sidebar.setStyleSheet(
            f"QListWidget {{ background:{SIDEBAR_BG}; border:none;"
            f" color:{INK}; font-size:12px; outline:none; }}"
            "QListWidget::item { padding:6px 8px; border-radius:5px; }"
            f"QListWidget::item:selected {{ background:#e2d6ba; color:{INK}; }}"
            "QListWidget::item:hover { background:#ece2cf; }"
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
            f"QComboBox QAbstractItemView {{ background:#fbf7ec; color:{INK};"
            " selection-background-color:#ece2cf; padding:4px; }"
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

        # The day's Stoic epigraph. It greets the blank page at full strength
        # and fades to faint once you begin writing, so it never competes with
        # your own words. Display only; the (quote, author) for this day.
        self._epigraph: tuple[str, str] = ("", "")
        self.epigraph = QLabel("")
        self.epigraph.setWordWrap(True)
        self.epigraph.setAlignment(Qt.AlignHCenter)
        self.epigraph.setTextFormat(Qt.RichText)
        self.epigraph.setContentsMargins(0, 4, 0, 2)

        self.editor = QTextEdit()
        self.editor.setFrameStyle(0)
        self.editor.setFont(QFont(BODY_FONT, BODY_SIZE))
        self.editor.setStyleSheet(
            f"QTextEdit {{ background:{PAPER}; color:{INK}; border:none;"
            f" selection-background-color:{TINT}; }}"
            "QScrollBar:vertical { background:transparent; width:8px; }"
            "QScrollBar::handle:vertical { background:#ddd8cc; border-radius:4px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height:0; }"
        )
        self.editor.document().setDocumentMargin(0)

        # The Year page: one scrolling, read-only page assembled from your
        # words. Lives beside the editor; only one of the two is visible.
        self.year_view = QTextBrowser()
        self.year_view.setFrameStyle(0)
        self.year_view.setOpenExternalLinks(False)
        self.year_view.setFont(QFont(BODY_FONT, BODY_SIZE))
        self.year_view.setStyleSheet(
            f"QTextBrowser {{ background:{PAPER}; color:{INK}; border:none; }}"
            "QScrollBar:vertical { background:transparent; width:8px; }"
            "QScrollBar::handle:vertical { background:#ddd8cc; border-radius:4px; }"
        )
        self.year_view.document().setDocumentMargin(0)
        self.year_view.hide()

        self.ask_button = QPushButton("Ask me something")
        self.ask_button.setMinimumHeight(38)
        self.ask_button.setCursor(Qt.PointingHandCursor)
        self.ask_button.clicked.connect(self.request_question)
        self.ask_button.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:{PAPER}; border:none;"
            " border-radius:6px; padding:8px 20px; font-size:13px; }"
            "QPushButton:hover { background:#9a8b5e; }"
            "QPushButton:disabled { background:#d8cfb8; }"
        )

        self.counter = QLabel("")
        self.counter.setStyleSheet(f"color:{FAINT}; font-size:11px;")

        self.suggest_button = QPushButton("Suggest a line")
        self.suggest_button.setMinimumHeight(38)
        self.suggest_button.setCursor(Qt.PointingHandCursor)
        self.suggest_button.clicked.connect(self.request_suggestion)
        self.suggest_button.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{ACCENT};"
            f" border:1px solid #ddceac; border-radius:6px; padding:8px 16px;"
            " font-size:13px; }"
            "QPushButton:hover { background:#f0ecdf; }"
            "QPushButton:disabled { color:#c7b89a; border-color:#e4ddca; }"
        )

        # Only during a year review: move past a question without answering.
        self.skip_button = QPushButton("Skip")
        self.skip_button.setMinimumHeight(38)
        self.skip_button.setCursor(Qt.PointingHandCursor)
        self.skip_button.clicked.connect(self.skip_question)
        self.skip_button.setStyleSheet(self.suggest_button.styleSheet())
        self.skip_button.hide()

        # A loud, inline answer to "why didn't a question appear?" -- the ask
        # gate's refusals used to live only in the status bar, which vanishes in
        # a few seconds and the eye skips. This sits right beside the button.
        self.ask_hint = QLabel("")
        self.ask_hint.setWordWrap(True)
        self.ask_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ask_hint.hide()
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._clear_ask_hint)

        controls = QHBoxLayout()
        controls.addWidget(self.counter)
        controls.addStretch(1)
        controls.addWidget(self.ask_hint, 1)
        controls.addWidget(self.skip_button)
        controls.addWidget(self.suggest_button)
        controls.addWidget(self.ask_button)

        column = QVBoxLayout()
        column.setContentsMargins(0, 36, 0, 24)
        column.setSpacing(10)
        column.addLayout(header)
        column.addWidget(self.arc_label)
        column.addWidget(self.epigraph)
        column.addSpacing(14)
        column.addWidget(self.editor, 1)
        column.addWidget(self.year_view, 1)
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
        QShortcut(QKeySequence("Ctrl+E"), self, self.export_journal)
        QShortcut(QKeySequence("Ctrl+D"), self, self.go_to_today)
        QShortcut(QKeySequence("Ctrl+Space"), self, self.request_suggestion)
        QShortcut(QKeySequence("Ctrl+R"), self, self.ask_again)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.open_year)
        QShortcut(QKeySequence("Ctrl+Shift+Y"), self, self.start_review)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, self.go_deeper)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.stop_generation)

        # A pending suggestion is accepted with Tab/Enter and dismissed by any
        # other key -- handled here so it never fights the normal editor keys.
        self.editor.installEventFilter(self)

        self._sync_header()

    def eventFilter(self, obj, event):
        if (
            obj is self.editor
            and self._ghost is not None
            and event.type() == QEvent.KeyPress
        ):
            key = event.key()
            if key in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                self.accept_suggestion()
                return True
            if key == Qt.Key_Escape:
                self.dismiss_suggestion()
                return True
            if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
                return False  # a bare modifier is not a decision
            # Any real typing means "no thanks" -- drop it, then let the key land.
            self.dismiss_suggestion()
        return super().eventFilter(obj, event)

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

        self._add_item("◎  Your year", ACTION, "year")
        self._add_item("◐  Review your year", ACTION, "review")
        self._add_item("", HEADER, "")

        echoes = on_this_day(self.journal_dir, self.today)
        if echoes:
            self._add_item("  ON THIS DAY", HEADER, "")
            for label, page in echoes:
                when = page.day.strftime("%d %b %Y")
                self._add_item(f"{label}   ·   {when}", PAGE, page.day.isoformat())
            self._add_item("", HEADER, "")

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
        if self.mode == PAGE:
            want = (PAGE, self.page.day.isoformat())
        elif self.mode == YEAR:
            want = (ACTION, "year")
        else:
            want = (NOTE, self.note.slug if self.note else "")
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
        elif kind == ACTION and key == "year":
            self.open_year()
        elif kind == ACTION and key == "review":
            self.start_review()
        elif kind == PAGE:
            self.open_page(Date.fromisoformat(key))
        elif kind == NOTE:
            self.open_note(key)

    # --- switching documents --------------------------------------------

    def _render_epigraph(self, strong: bool) -> None:
        """Paint the day's epigraph -- bold and centred on a blank page,
        faded once there are words so it steps out of the way."""
        quote, who = self._epigraph
        if not quote:
            self.epigraph.hide()
            return
        size = 18 if strong else 14
        quote_col = "#7e7454" if strong else "#c3b591"
        who_col = "#c0b28c" if strong else "#d0c4a4"
        self.epigraph.setText(
            f'<div style="font-family:{BODY_FONT}; font-style:italic;'
            f' font-size:{size}px; color:{quote_col}; line-height:135%;">'
            f'“{html.escape(quote)}”</div>'
            f'<div style="font-family:{BODY_FONT}; font-size:10px;'
            f' color:{who_col};">{html.escape(who).upper()}</div>'
        )
        self.epigraph.show()

    def _sync_header(self) -> None:
        showing_year = self.mode == YEAR
        self.year_view.setVisible(showing_year)
        self.editor.setVisible(not showing_year)
        if self.mode == PAGE:
            self.date_label.setText(self.page.day.strftime("%A, %d %B %Y").upper())
            self.practice_box.show()
            self.ask_button.show()
            if self._sealed:
                self.ask_button.setEnabled(False)
                self.ask_button.setText("Sealed ✓")
            else:
                self.ask_button.setEnabled(True)
                self.ask_button.setText(
                    self._guided_ask_text() if self._in_review else "Ask me something"
                )
            self.skip_button.setVisible(self._in_review and not self._sealed)
            self.suggest_button.setVisible(not self._in_review)
            # No epigraph during a guided review -- it has its own frame.
            if self._in_review:
                self._epigraph = ("", "")
            else:
                self._epigraph = epigraph_for_day(self.page.day)
            self._render_epigraph(strong=not self.page.words)
        elif showing_year:
            self.date_label.setText("YOUR YEAR")
            self.practice_box.hide()
            self.arc_label.hide()
            self.epigraph.hide()
            self.ask_button.hide()
            self.suggest_button.hide()
            self.skip_button.hide()
        else:
            self.date_label.setText((self.note.title if self.note else "").upper())
            self.practice_box.hide()
            self.arc_label.hide()
            self.epigraph.hide()
            # A note is a reference document, not a reflection surface.
            self.ask_button.hide()
            self.suggest_button.hide()
            self.skip_button.hide()

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
        self._sealed = False
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

    def go_to_today(self) -> None:
        self.open_page(self.today)

    # --- your year, on one page -------------------------------------------

    def open_year(self) -> None:
        """Show the Year page: instantly from cache, then fill in any new days
        on the local model in the background and redraw."""
        self.save_now()
        self.mode = YEAR
        self.note = None
        self._sync_header()
        self._update_counter()
        self._highlight_current()
        self._render_year()
        self._extract_year_in_background()

    def _render_year(self) -> None:
        records = year_records(self.journal_dir, None)  # cache only: instant
        self._year_summary = aggregate(records)
        self.year_view.setHtml(render_html(self._year_summary))

    def _extract_year_in_background(self) -> None:
        if self._year_worker is not None and self._year_worker.isRunning():
            return
        engine = self.ensure_engine()
        if engine is None:
            self.statusBar().showMessage(
                "Showing what is cached — the model is unavailable to read new days."
            )
            return
        self._year_worker = YearWorker(engine, self.journal_dir)
        self._year_worker.progress.connect(self._on_year_progress)
        self._year_worker.done.connect(self._on_year_done)
        self._year_worker.failed.connect(
            lambda m: self.statusBar().showMessage(f"Could not read every day — {m}")
        )
        self._year_worker.start()

    def _on_year_progress(self, done: int, total: int) -> None:
        if self.mode == YEAR and done < total:
            self.statusBar().showMessage(f"Reading your year… {done} of {total} days")

    def _on_year_done(self) -> None:
        if self.mode == YEAR:
            self._render_year()
            self.statusBar().showMessage("Your year is up to date.", 2500)

    # --- review your year, in one sitting ---------------------------------

    def start_review(self) -> None:
        """Begin, or resume, the fourteen-question review on today's page."""
        self.open_page(self.today)
        script = review_questions()
        if self.page.practice != REVIEW_PRACTICE:
            self.page.practice = REVIEW_PRACTICE
            if self.engine is not None:
                self.engine.set_practice(REVIEW_PRACTICE)
            index = self.practice_box.findData(REVIEW_PRACTICE)
            self.practice_box.blockSignals(True)
            if index >= 0:
                self.practice_box.setCurrentIndex(index)
            self.practice_box.blockSignals(False)
        self._sync_header()
        self.page.blocks = self.harvest()
        if not review_turns(self.page, script):
            self._insert_question(script[0])
        self._sync_practice_label()
        self.statusBar().showMessage(
            "Fourteen questions, about an hour. Write, then Ctrl+Enter for the next.",
            6000,
        )
        self.editor.setFocus()

    def _insert_question(self, text: str) -> None:
        cursor = self.editor.textCursor()
        self._open_question_block(cursor)
        cursor.insertText(text)
        self._start_writing_block(cursor)
        self.save_now()
        self.editor.setFocus()

    def next_step(self) -> None:
        """Next -- a follow-up if the answer is thin, otherwise the next question."""
        if not self._in_review or (self.worker and self.worker.isRunning()):
            return
        script = self._guided_script()
        self.page.blocks = self.harvest()
        done = review_turns(self.page, script)
        if not done:
            self._insert_question(script[0])
            self._sync_practice_label()
            return
        current = done[-1]
        if not current.answer.strip():
            self.statusBar().showMessage("Write something here, or skip it.", 3000)
            return
        # Only the year review draws follow-ups from the model; the evening
        # review is three plain questions, deterministic and offline.
        if self.page.practice == REVIEW_PRACTICE and needs_followup(current):
            self._request_followup(current)
            return
        self._advance(current.index + 1, script)

    def skip_question(self) -> None:
        if not self._in_review or (self.worker and self.worker.isRunning()):
            return
        script = self._guided_script()
        self.page.blocks = self.harvest()
        self._advance(next_index(self.page, script), script)

    def _advance(self, index: int, script: list[str]) -> None:
        if index >= len(script):
            if self.page.practice == EVENING_PRACTICE:
                self.seal_day()
            else:
                self.finish_review()
            return
        self._insert_question(script[index])
        self.ask_button.setText(self._guided_ask_text())
        self._sync_practice_label()

    def seal_day(self) -> None:
        """Close an evening review with a deliberate act, not a silent save."""
        self.save_now()
        self._sealed = True
        self.ask_button.setEnabled(False)
        self.ask_button.setText("Sealed ✓")
        self.skip_button.hide()
        self.arc_label.setText("THE DAY IS SEALED")
        self.arc_label.show()
        self.statusBar().showMessage("The day is sealed. Rest well.", 6000)

    def _request_followup(self, turn) -> None:
        engine = self.ensure_engine()
        if engine is None:
            # No model must never block the review: just move on.
            self._advance(turn.index + 1, review_questions())
            return
        if engine.practice != REVIEW_PRACTICE:
            engine.set_practice(REVIEW_PRACTICE)
        engine.set_context(self.standing_context())
        self.ask_button.setEnabled(False)
        self.ask_button.setText("Thinking…")
        self.statusBar().showMessage("One more thing about that…")
        # The model sees only this question and what was written under it.
        slice_page = followup_page(turn, self.page.day, self.model_path, DEFAULT_PROMPT)
        self._streaming = False
        self.worker = AskWorker(engine, slice_page, (), tuple(turn.followups))
        self.worker.finished_ok.connect(self.on_question)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

    def finish_review(self) -> None:
        """All fourteen done: read the answers and draw where you stand."""
        self.save_now()
        self.page.blocks = self.harvest()
        session = self.page
        engine = self.ensure_engine()
        self.mode = YEAR
        self.note = None
        self._sync_header()
        self._highlight_current()
        self.date_label.setText("WHERE YOU STAND")
        self._year_summary = YearSummary()
        self.year_view.setHtml(render_html(self._year_summary, title="Where you stand"))
        if engine is None:
            self.statusBar().showMessage(
                "The model is unavailable, so the picture can't be drawn yet."
            )
            return
        self.statusBar().showMessage("Reading your answers…")
        self._review_worker = ReviewWorker(engine, session, review_questions(), self.journal_dir)
        self._review_worker.progress.connect(
            lambda i, n: self.statusBar().showMessage(f"Reading your answers… {i} of {n}")
        )
        self._review_worker.done.connect(lambda recs: self._on_review_done(session, recs))
        self._review_worker.failed.connect(
            lambda m: self.statusBar().showMessage(f"Could not read every answer — {m}")
        )
        self._review_worker.start()

    def _on_review_done(self, session: Page, records) -> None:
        summary = aggregate(list(records))
        skipped = review_unanswered(session, review_questions())
        summary.unanswered = [(session.day, q) for q in skipped]
        self._year_summary = summary
        self._portrait = None
        self._deep = None
        self._review_session = session
        self.year_view.setHtml(render_html(summary, title="Where you stand"))
        self.date_label.setText("WHERE YOU STAND")
        # The facts are up; now the reading, which is the actual value.
        engine = self.engine
        if engine is None:
            return
        self.statusBar().showMessage("Writing your reading…")
        self._portrait_worker = PortraitWorker(self.journal_dir, engine, session, review_questions())
        self._portrait_worker.progress.connect(
            lambda i, n: self.statusBar().showMessage(f"Writing your reading… {i} of {n}")
        )
        self._portrait_worker.done.connect(lambda p: self._on_portrait(summary, p))
        self._portrait_worker.failed.connect(
            lambda m: self.statusBar().showMessage(f"Could not write the reading — {m}")
        )
        self._portrait_worker.start()

    def _on_portrait(self, summary: YearSummary, portrait) -> None:
        self._portrait = portrait
        self.year_view.setHtml(render_html(summary, title="Where you stand", portrait=portrait))
        self.statusBar().showMessage(
            "This is where you stand. Ctrl+Shift+D goes deeper · Ctrl+E saves it.", 8000)

    def go_deeper(self) -> None:
        """Ctrl+Shift+D on a finished review: write the long reading -- a read of
        each answer, then a letter -- and fold it into the page."""
        if (self.mode != YEAR or self._portrait is None
                or self._review_session is None or self._deep is not None):
            return
        engine = self.ensure_engine()
        if engine is None:
            self.statusBar().showMessage("The model is unavailable, so the deeper reading can't be drawn.")
            return
        self.statusBar().showMessage("Writing the deeper reading…")
        session = self._review_session
        self._deep_worker = DeepWorker(
            self.journal_dir, engine, session, review_questions(), self._portrait)
        self._deep_worker.progress.connect(
            lambda i, n: self.statusBar().showMessage(f"Writing the deeper reading… {i} of {n}"))
        self._deep_worker.done.connect(self._on_deep)
        self._deep_worker.failed.connect(
            lambda m: self.statusBar().showMessage(f"Could not write the deeper reading — {m}"))
        self._deep_worker.start()

    def _on_deep(self, deep) -> None:
        self._deep = deep
        self.year_view.setHtml(render_html(
            self._year_summary, title="Where you stand", portrait=self._portrait, deep=deep))
        self.statusBar().showMessage("The deeper reading is in. Ctrl+E saves it.", 6000)

    def export_journal(self) -> None:
        """Write the whole journal -- or, on the Year page, the year -- to one
        Markdown file under exports/."""
        self.save_now()
        try:
            if self.mode == YEAR:
                text = render_markdown(self._year_summary, portrait=self._portrait, deep=self._deep)
                name = f"year-{self.today.isoformat()}.md"
            else:
                text = export_all(self.journal_dir)
                name = f"journal-{self.today.isoformat()}.md"
            path = write_export(self.journal_dir, text, name)
        except OSError as exc:
            self.statusBar().showMessage(f"Could not export — {exc}")
            return
        self.statusBar().showMessage(f"Exported to {path}", 4000)

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
        if self._in_review:
            script = self._guided_script()
            self.page.blocks = self.harvest()
            index = max(0, next_index(self.page, script) - 1)
            shown = min(index + 1, len(script))
            if self.page.practice == EVENING_PRACTICE:
                label = f"EVENING REVIEW · {shown} OF {len(script)}"
            else:
                label = f"YEAR REVIEW · {progress_label(index, len(script))}"
            self.arc_label.setText(label)
            self.arc_label.show()
            return
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
        self._sealed = False
        if self.engine is not None:
            self.engine.set_practice(slug)
        self._sync_header()
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

    # --- pointing at the buried phrase ----------------------------------

    def _tint(self, start: int, end: int, colour: str) -> None:
        cursor = self.editor.textCursor()
        self.editor.blockSignals(True)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))
        cursor.mergeCharFormat(fmt)
        self.editor.blockSignals(False)

    def clear_highlight(self) -> None:
        if not self._highlight:
            return
        start, end = self._highlight
        self._highlight = None
        # Only repaint if the range still fits the document.
        if end <= len(self.editor.toPlainText()):
            self._tint(start, end, INK)

    def highlight_target(self, question: str) -> None:
        """Tint the sentence in the writer's OWN words that the question is
        about, so the thing it noticed is visible at a glance. Never touches a
        question block, and is display-only -- harvest() reads block formats,
        not colour, so this can never bleed into what is saved."""
        phrase = _quoted_phrase(question)
        if not phrase:
            return
        needle = phrase.lower()
        block = self.editor.document().begin()
        while block.isValid():
            if not block.blockFormat().property(IS_QUESTION):
                idx = block.text().lower().find(needle)
                if idx != -1:
                    start = block.position() + idx
                    self._tint(start, start + len(phrase), TARGET_INK)
                    self._highlight = (start, start + len(phrase))
                    return
            block = block.next()

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
        self._highlight = None  # the document is rebuilt; old positions are void
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
        last = self.editor.document().lastBlock()
        previous = last.previous()
        after_a_question = previous.isValid() and bool(
            previous.blockFormat().property(IS_QUESTION)
        )
        # Reuse a trailing empty paragraph -- unless it is the only thing
        # separating this question from the one before it (a skipped review
        # question). Two adjacent question paragraphs would merge into one
        # block and stop matching the script.
        if last.text().strip() or after_a_question:
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
            if block.blockFormat().property(IS_GHOST):
                # A pending suggestion is not yours until you accept it.
                flush()
                kind = None
                block = block.next()
                continue
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
        # The highlight is a momentary "here is what I noticed" -- once you
        # start writing again it clears, and stale positions never linger.
        self.clear_highlight()
        self._update_counter()
        # A nudge ("write a little more") has served its purpose the moment you
        # start writing -- clear it, unless a question is actively generating.
        if not self.ask_hint.isHidden() and not (self.worker and self.worker.isRunning()):
            self._clear_ask_hint()
        # Fade the epigraph the moment there are words; restore it if emptied.
        if self.mode == PAGE and not self._in_review and self._epigraph[0]:
            self._render_epigraph(strong=not self.page.words)

    def _update_counter(self) -> None:
        if self.mode == PAGE:
            self.page.blocks = self.harvest()
            words = self.page.words
        elif self.mode == YEAR:
            words = 0
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
        # If warm-up is already loading the model, wait for it rather than
        # starting a second load. processEvents keeps the window alive and lets
        # the ready signal assign self.engine.
        if self._warmup is not None and self._warmup.isRunning():
            self.statusBar().showMessage("Warming up…")
            while self._warmup.isRunning():
                QApplication.processEvents()
                self._warmup.wait(50)
            if self.engine is not None:
                self.statusBar().clearMessage()
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

    @property
    def _in_review(self) -> bool:
        """True inside any guided sequence -- the year review or the evening
        review -- where questions are walked one at a time."""
        return self.mode == PAGE and self.page.practice in GUIDED

    def _guided_script(self) -> list[str]:
        """The list of questions for the current guided practice."""
        return list(self.practice.openings)

    def _guided_ask_text(self) -> str:
        """What the primary button says mid-sequence: 'Seal the day' on the
        last evening-review question, 'Next →' otherwise."""
        if self.page.practice == EVENING_PRACTICE:
            script = self._guided_script()
            self.page.blocks = self.harvest()
            index = max(0, next_index(self.page, script) - 1)
            if index >= len(script) - 1:
                return "Seal the day"
        return "Next →"

    def _show_ask_hint(self, text: str, kind: str = "nudge", hold: int = 4000) -> None:
        """Say -- loudly, next to the button -- why nothing came back, or that a
        question is on its way. kind sets the tone: 'nudge' (write more),
        'working' (thinking), 'miss' (no question). hold=0 stays until cleared."""
        colour = {"nudge": ACCENT, "working": FAINT, "miss": TARGET_INK}.get(kind, ACCENT)
        self.ask_hint.setStyleSheet(
            f"color:{colour}; font-size:12px; font-style:italic; padding-right:4px;"
        )
        self.ask_hint.setText(text)
        self.ask_hint.show()
        if hold:
            self._hint_timer.start(hold)
        else:
            self._hint_timer.stop()

    def _clear_ask_hint(self) -> None:
        self._hint_timer.stop()
        self.ask_hint.clear()
        self.ask_hint.hide()

    def request_question(self, avoid: tuple[str, ...] = ()) -> None:
        if self.mode != PAGE or (self.worker and self.worker.isRunning()):
            return
        if self._in_review:
            self.next_step()
            return
        if self._suggester and self._suggester.isRunning():
            return
        if self._ghost is not None:
            self.dismiss_suggestion()
        self.page.blocks = self.harvest()
        if not self.page.words:
            self._show_ask_hint("Write something first, then ask.", "nudge")
            return
        if self.page.words < MIN_ASK_WORDS:
            need = MIN_ASK_WORDS - self.page.words
            self._show_ask_hint(
                f"A little more first — about {need} more "
                f"word{'s' if need != 1 else ''} give it something real to ask about.",
                "nudge",
            )
            return

        self._clear_ask_hint()
        self.ask_button.setEnabled(False)
        self.ask_button.setText("Thinking…")
        self._show_ask_hint("Thinking… one question on its way.", "working", hold=0)
        self.save_now()

        engine = self.ensure_engine()
        if engine is None:
            self._show_ask_hint(
                "The model isn't ready yet — it may still be loading.", "miss"
            )
            self._reset_button()
            return
        if engine.practice != self.page.practice:
            engine.set_practice(self.page.practice)
        engine.set_context(self.standing_context())

        # Give an arced practice its arc: the question can build on earlier
        # days. Free writing stays clean -- no prior days are dredged in.
        history = ()
        if self.page.practice != DEFAULT_PRACTICE:
            history = practice_history(
                self.journal_dir, self.page.practice, self.page.day
            )

        self._streaming = False
        self.statusBar().showMessage("Thinking…")
        self.worker = AskWorker(engine, self.page, history, avoid)
        self.worker.finished_ok.connect(self.on_question)
        self.worker.failed.connect(self.on_failure)
        self.worker.start()

    def ask_again(self) -> None:
        """Replace the question just shown with a different one."""
        if self.mode != PAGE or (self.worker and self.worker.isRunning()):
            return
        last = self._last_q
        self._remove_last_question_block()
        self.request_question(avoid=(last,) if last else ())

    def _remove_last_question_block(self) -> None:
        blocks = self.harvest()
        if blocks and blocks[-1].kind == QUESTION:
            blocks.pop()
            self.page.blocks = blocks
            self._render_page()
            self._last_q = None

    def on_token(self, chunk: str) -> None:
        """Streaming hook: opens the question block on the first chunk. The
        best-of-N worker delivers whole questions, but this keeps live
        streaming available and is how the UI tests drive a question in."""
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
        question = (question or "").strip()
        if not question and not self._streaming:
            self._show_ask_hint("No question landed this time — press again.", "miss")
            return
        self._clear_ask_hint()
        cursor = self.editor.textCursor()
        if not self._streaming:
            self._open_question_block(cursor)
            cursor.insertText(question)
        self._streaming = False
        self._start_writing_block(cursor)
        self._last_q = question
        self.save_now()
        self.highlight_target(question)
        self.statusBar().showMessage("⌘R / Ctrl+R for a different question", 3000)
        self.editor.setFocus()

    def on_failure(self, message: str) -> None:
        self._reset_button()
        self._show_ask_hint("No question this time — press again.", "miss", hold=6000)
        self.statusBar().showMessage(f"No question this time — {message}")

    # --- the co-writer: suggest a line in your own voice ----------------

    def _ghost_format(self) -> tuple[QTextBlockFormat, QTextCharFormat]:
        bf = QTextBlockFormat()
        bf.setProperty(IS_QUESTION, False)
        bf.setProperty(IS_GHOST, True)
        bf.setTopMargin(0)
        bf.setBottomMargin(12)
        bf.setLineHeight(LINE_HEIGHT, PROPORTIONAL)
        cf = QTextCharFormat()
        cf.setFont(QFont(BODY_FONT, BODY_SIZE))
        cf.setForeground(QColor(GHOST_INK))
        cf.setFontItalic(True)
        return bf, cf

    def request_suggestion(self) -> None:
        if self.mode != PAGE or self._ghost is not None:
            return
        if self.worker and self.worker.isRunning():
            return
        if self._suggester and self._suggester.isRunning():
            return
        self.page.blocks = self.harvest()
        if not self.page.words:
            self.statusBar().showMessage("Write a little first.", 2500)
            return

        engine = self.ensure_engine()
        if engine is None:
            return
        if engine.practice != self.page.practice:
            engine.set_practice(self.page.practice)
        engine.set_context(self.standing_context())

        history = ()
        if self.page.practice != DEFAULT_PRACTICE:
            history = practice_history(
                self.journal_dir, self.page.practice, self.page.day
            )

        self.suggest_button.setEnabled(False)
        self.suggest_button.setText("Thinking…")
        self.statusBar().showMessage("Finding a line in your voice…")
        self._suggester = SuggestWorker(engine, self.page, history)
        self._suggester.done.connect(self.on_suggestion)
        self._suggester.failed.connect(self.on_suggestion_failed)
        self._suggester.start()

    def on_suggestion(self, text: str) -> None:
        self._reset_suggest_button()
        text = text.strip()
        if not text:
            self.statusBar().showMessage("No suggestion this time.", 2500)
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.blockSignals(True)
        if self.editor.document().lastBlock().text().strip():
            cursor.insertBlock()
        bf, cf = self._ghost_format()
        cursor.setBlockFormat(bf)
        cursor.setCharFormat(cf)
        anchor = cursor.position()
        cursor.insertText(text)
        self.editor.blockSignals(False)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self._ghost = anchor
        self.statusBar().showMessage("Tab to keep this line · Esc to discard")

    def on_suggestion_failed(self, message: str) -> None:
        self._reset_suggest_button()
        self.statusBar().showMessage(f"No suggestion this time — {message}")

    def accept_suggestion(self) -> None:
        if self._ghost is None:
            return
        start = self._ghost
        self._ghost = None
        end = len(self.editor.toPlainText())
        cursor = self.editor.textCursor()
        self.editor.blockSignals(True)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        bf, cf = self._writing_format()
        cursor.setBlockFormat(bf)  # clears the IS_GHOST marker
        cursor.mergeCharFormat(cf)  # your ink, upright -- it is yours now
        self.editor.blockSignals(False)
        self._start_writing_block(self.editor.textCursor())
        self.save_now()
        self.statusBar().showMessage("Kept.", 1500)

    def dismiss_suggestion(self) -> None:
        if self._ghost is None:
            return
        start = self._ghost
        self._ghost = None
        end = len(self.editor.toPlainText())
        cursor = self.editor.textCursor()
        self.editor.blockSignals(True)
        # Eat the block break inserted before the ghost, so nothing is left behind.
        cursor.setPosition(max(0, start - 1))
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.editor.blockSignals(False)
        self._start_writing_block(self.editor.textCursor())
        self.statusBar().showMessage("Discarded.", 1500)

    def _reset_suggest_button(self) -> None:
        self.suggest_button.setEnabled(True)
        self.suggest_button.setText("Suggest a line")

    def _reset_button(self) -> None:
        self.ask_button.setEnabled(True)
        self.ask_button.setText("Next →" if self._in_review else "Ask me something")

    def stop_generation(self) -> None:
        if self._ghost is not None:
            self.dismiss_suggestion()
            return
        if self.engine and self.worker and self.worker.isRunning():
            self.engine.stop()
            self.statusBar().showMessage("Stopped.", 2000)

    def save_now(self) -> None:
        if self.mode == YEAR:
            return  # the Year page is read-only; the editor holds nothing new
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
        if self._suggester is not None and self._suggester.isRunning():
            self._suggester.wait(3000)
        if self._year_worker is not None and self._year_worker.isRunning():
            self._year_worker.wait(3000)
        if self._review_worker is not None and self._review_worker.isRunning():
            self._review_worker.wait(3000)
        if self._portrait_worker is not None and self._portrait_worker.isRunning():
            self._portrait_worker.wait(3000)
        if self._deep_worker is not None and self._deep_worker.isRunning():
            self._deep_worker.wait(3000)
        if self._warmup is not None and self._warmup.isRunning():
            self._warmup.wait(3000)
        if self.engine is not None:
            self.engine.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    # REFLECT_JOURNAL_DIR points the app at another journal -- used for the
    # seeded demo year so a demo never touches your real writing.
    override = os.environ.get("REFLECT_JOURNAL_DIR", "").strip()
    journal_dir = Path(override).expanduser() if override else None
    window = Window(journal_dir=journal_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
