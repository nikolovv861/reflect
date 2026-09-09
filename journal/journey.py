"""The journey: open the app once and be walked through fourteen questions.

Not a journal with a review feature tucked in a sidebar -- a stage. Deep ink,
one question at a time in a large serif, each with a line on why it is being
asked, a path of fourteen nodes lighting up as you go, a stoic line at the
threshold and at the midpoint. When an answer is thin the model asks for the
one missing piece, beneath the question. After the fourteenth the screen turns
to paper and you are shown where you stand.

Everything the engine does is the same code as the journal (review.py,
year.py, yearpage.py); this module is presentation. The session is saved as
today's page, plain Markdown, so the journal can show it afterwards.
"""
from __future__ import annotations

import math
from datetime import date as Date
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.demo import demo_deep, demo_portrait, demo_summary
from journal.engine import DEFAULT_MODEL, DEFAULT_PROMPT, Engine
from journal.export import write_export
from journal.review import (
    MAX_FOLLOWUPS,
    PRACTICE,
    Turn,
    extract_turn,
    followup_page,
    meanings,
    minutes_left,
    needs_followup,
    questions,
    turns,
)
from journal.store import QUESTION, WRITING, Block, Page, list_pages, load, save
from journal.ui import AskWorker, DeepWorker, PortraitWorker, ReviewWorker, WarmupWorker
from journal.yearpage import YearSummary, aggregate, render_html, render_markdown

INK_BG = "#1b1a18"
PAPER = "#fbf9f4"
CREAM = "#e9e4d8"
FAINT = "#8a8577"
LINE = "#3a3833"
ACCENT = "#cfc4e6"
SERIF = "Georgia"

QUOTES = {
    "threshold": ("Begin at once to live, and count each separate day as a "
                  "separate life.", "Seneca"),
    "midpoint": ("First say to yourself what you would be; and then do what "
                 "you have to do.", "Epictetus"),
    "reading": ("The soul becomes dyed with the colour of its thoughts.",
                "Marcus Aurelius"),
}
MIDPOINT = 7  # show the midpoint quote before this question index

DONE_MARKER = ".journey-done"


# --- small animated pieces --------------------------------------------------


def fade_in(widget: QWidget, ms: int = 700) -> None:
    """Fade a widget from nothing to full. The effect is kept on the widget."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
    widget._fade = anim  # keep alive


class PathWidget(QWidget):
    """Fourteen nodes on a line; the lit part advances as the journey does."""

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self._total = max(2, total)
        self._progress = 0.0
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = Property(float, get_progress, set_progress)

    def animate_to(self, value: float, ms: int = 800) -> None:
        anim = QPropertyAnimation(self, b"progress", self)
        anim.setStartValue(self._progress)
        anim.setEndValue(float(value))
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.start()
        self._anim = anim

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        y = h / 2
        x0, x1 = 14.0, w - 14.0
        span = x1 - x0
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        frac = min(1.0, max(0.0, self._progress / (self._total - 1)))
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawLine(QPointF(x0, y), QPointF(x0 + span * frac, y))
        for i in range(self._total):
            x = x0 + span * i / (self._total - 1)
            reached = i <= self._progress + 1e-6
            colour = QColor(ACCENT if reached else LINE)
            p.setPen(QPen(colour, 1))
            p.setBrush(QBrush(colour if reached else QColor(INK_BG)))
            r = 4.5 if reached else 3.0
            p.drawEllipse(QPointF(x, y), r, r)


class BreathingMark(QWidget):
    """A single slow-breathing point of light. Calm, not busy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self) -> None:
        self._t += 0.033
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        pulse = (math.sin(self._t * 1.1) + 1) / 2  # 0..1, ~5.7s per breath
        halo = QColor(ACCENT)
        halo.setAlphaF(0.10 + 0.15 * pulse)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(c, 16 + 8 * pulse, 16 + 8 * pulse)
        core = QColor(ACCENT)
        core.setAlphaF(0.75 + 0.25 * pulse)
        p.setBrush(QBrush(core))
        p.drawEllipse(c, 4.5, 4.5)


# --- the journey ------------------------------------------------------------


def journey_done(journal_dir: Path) -> bool:
    return (journal_dir / DONE_MARKER).exists()


def mark_done(journal_dir: Path) -> None:
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / DONE_MARKER).write_text(datetime.now().isoformat(), encoding="utf-8")


def seeded_session(journal_dir: Path, script: list[str]) -> Page | None:
    """A finished review already on disk (for the stage fast-forward)."""
    for path in reversed(list_pages(journal_dir)):
        try:
            page = load(path)
        except OSError:
            continue
        if page.practice == PRACTICE and len(turns(page, script)) >= len(script) - 1:
            return page
    return None


class Journey(QWidget):
    open_journal = Signal()
    finished = Signal()

    def __init__(
        self,
        journal_dir: Path,
        model_path: str = DEFAULT_MODEL,
        day: Date | None = None,
    ):
        super().__init__()
        self.setWindowTitle("reflect — a year, in fourteen questions")
        self.resize(1120, 900)
        self.setStyleSheet(f"background:{INK_BG};")

        self.journal_dir = journal_dir
        self.model_path = model_path
        self.day = day or datetime.now().date()
        self.script = questions()
        self.meanings = meanings()
        self.index = 0
        self.followups: list[str] = []
        self.marks: list[int] = []  # editor length when each follow-up arrived
        self.blocks: list[Block] = []  # the session so far
        self.engine: Engine | None = None
        self.worker: AskWorker | None = None
        self._warmup: WarmupWorker | None = None
        self._reader: ReviewWorker | None = None
        self._writer: PortraitWorker | None = None
        self._deep_worker = None
        self.summary = YearSummary()
        self.portrait = None
        self.deep = None
        self.session: Page | None = None

        self.stack = QStackedWidget()
        self.intro = self._build_intro()
        self.question_screen = self._build_question()
        self.reading = self._build_reading()
        self.report = self._build_report()
        for screen in (self.intro, self.question_screen, self.reading, self.report):
            self.stack.addWidget(screen)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)

        QShortcut(QKeySequence("Ctrl+Return"), self, self.next_step)
        QShortcut(QKeySequence("Return"), self.intro, self.begin)
        QShortcut(QKeySequence("Ctrl+E"), self, self.save_report)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, self.fast_forward)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, self.see_demo)

        self._start_warmup()

    # --- screens -----------------------------------------------------------

    @staticmethod
    def _label(text: str, size: int, colour: str, italic: bool = False, spacing: int = 0) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        font = QFont(SERIF, size)
        font.setItalic(italic)
        lab.setFont(font)
        style = f"color:{colour}; background:transparent;"
        if spacing:
            style += f" letter-spacing:{spacing}px;"
        lab.setStyleSheet(style)
        return lab

    def _column(self, width: int = 720) -> tuple[QWidget, QVBoxLayout]:
        holder = QWidget()
        holder.setMaximumWidth(width)
        holder.setStyleSheet("background:transparent;")
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)
        page = QWidget()
        page.setStyleSheet(f"background:{INK_BG};")
        row = QHBoxLayout(page)
        row.setContentsMargins(40, 40, 40, 40)
        row.addStretch(1)
        row.addWidget(holder)
        row.addStretch(1)
        page._column = col
        page._holder = holder
        return page, col

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(42)
        if primary:
            b.setStyleSheet(
                f"QPushButton {{ background:{ACCENT}; color:{INK_BG}; border:none;"
                " border-radius:6px; padding:8px 22px; font-size:14px; }"
                "QPushButton:hover { background:#ddd4f0; }"
                "QPushButton:disabled { background:#4a4650; color:#8a8577; }"
            )
        else:
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{FAINT};"
                f" border:1px solid {LINE}; border-radius:6px; padding:8px 18px;"
                " font-size:13px; }"
                f"QPushButton:hover {{ color:{CREAM}; border-color:{FAINT}; }}"
            )
        return b

    def _build_intro(self) -> QWidget:
        page, col = self._column(640)
        col.addStretch(2)
        self.mark = BreathingMark()
        centred = QHBoxLayout()
        centred.addStretch(1)
        centred.addWidget(self.mark)
        centred.addStretch(1)
        col.addLayout(centred)
        col.addSpacing(18)
        self.intro_title = self._label("reflect", 15, FAINT, spacing=6)
        self.intro_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.intro_title)
        quote, who = QUOTES["threshold"]
        self.intro_quote = self._label(f"“{quote}”", 24, CREAM, italic=True)
        self.intro_quote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.intro_quote)
        self.intro_who = self._label(f"— {who}", 12, FAINT, spacing=2)
        self.intro_who.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.intro_who)
        col.addSpacing(30)
        self.intro_sub = self._label(
            "Fourteen questions. About an hour.\nNothing you write leaves this machine.",
            14, FAINT,
        )
        self.intro_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.intro_sub)
        col.addSpacing(26)
        begin = self._button("Begin", primary=True)
        begin.clicked.connect(self.begin)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(begin)
        row.addStretch(1)
        col.addLayout(row)
        self.intro_hint = self._label("press Enter", 11, LINE, spacing=1)
        self.intro_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.intro_hint)
        col.addSpacing(22)
        demo = QPushButton("See a sample reading")
        demo.setCursor(Qt.CursorShape.PointingHandCursor)
        demo.setFlat(True)
        demo.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{FAINT}; border:none;"
            " font-size:12px; text-decoration:underline; }"
            f"QPushButton:hover {{ color:{CREAM}; }}"
        )
        demo.clicked.connect(self.see_demo)
        drow = QHBoxLayout()
        drow.addStretch(1)
        drow.addWidget(demo)
        drow.addStretch(1)
        col.addLayout(drow)
        col.addStretch(3)
        return page

    def _build_question(self) -> QWidget:
        page, col = self._column(760)
        self.path = PathWidget(len(self.script))
        col.addWidget(self.path)
        self.q_where = self._label("", 11, FAINT, spacing=3)
        col.addWidget(self.q_where)
        col.addSpacing(6)
        self.q_text = self._label("", 26, CREAM)
        col.addWidget(self.q_text)
        self.q_meaning = self._label("", 14, FAINT, italic=True)
        col.addWidget(self.q_meaning)
        self.q_followup = self._label("", 16, ACCENT, italic=True)
        self.q_followup.hide()
        col.addWidget(self.q_followup)
        col.addSpacing(6)
        self.editor = QTextEdit()
        self.editor.setFrameStyle(0)
        self.editor.setFont(QFont(SERIF, 16))
        self.editor.setPlaceholderText("Write here…")
        self.editor.setStyleSheet(
            f"QTextEdit {{ background:#232220; color:{CREAM}; border:none;"
            f" border-radius:8px; padding:14px; selection-background-color:#3d3a48; }}"
            "QScrollBar:vertical { background:transparent; width:8px; }"
            f"QScrollBar::handle:vertical {{ background:{LINE}; border-radius:4px; }}"
        )
        self.editor.setMinimumHeight(220)
        col.addWidget(self.editor, 1)
        footer = QHBoxLayout()
        self.q_status = self._label("", 12, FAINT)
        footer.addWidget(self.q_status, 1)
        self.skip_button = self._button("Skip")
        self.skip_button.clicked.connect(self.skip)
        footer.addWidget(self.skip_button)
        self.next_button = self._button("Next  →", primary=True)
        self.next_button.clicked.connect(self.next_step)
        footer.addWidget(self.next_button)
        col.addLayout(footer)
        self.q_hint = self._label("Ctrl+Enter for next", 11, LINE, spacing=1)
        self.q_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        col.addWidget(self.q_hint)
        return page

    def _build_reading(self) -> QWidget:
        page, col = self._column(640)
        col.addStretch(2)
        self.reading_path = PathWidget(len(self.script))
        col.addWidget(self.reading_path)
        col.addSpacing(24)
        self.reading_title = self._label("Reading your answers…", 22, CREAM)
        self.reading_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.reading_title)
        self.reading_status = self._label("", 13, FAINT)
        self.reading_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self.reading_status)
        col.addSpacing(30)
        quote, who = QUOTES["reading"]
        q = self._label(f"“{quote}”", 17, FAINT, italic=True)
        q.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(q)
        w = self._label(f"— {who}", 11, LINE, spacing=2)
        w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(w)
        col.addStretch(3)
        return page

    def _build_report(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background:{PAPER};")
        row = QHBoxLayout(page)
        row.setContentsMargins(40, 36, 40, 24)
        holder = QWidget()
        holder.setMaximumWidth(760)
        holder.setStyleSheet(f"background:{PAPER};")
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        self.report_view = QTextBrowser()
        self.report_view.setFrameStyle(0)
        self.report_view.setOpenExternalLinks(False)
        self.report_view.setFont(QFont(SERIF, 15))
        self.report_view.setStyleSheet(
            f"QTextBrowser {{ background:{PAPER}; color:#33312c; border:none; }}"
            "QScrollBar:vertical { background:transparent; width:8px; }"
            "QScrollBar::handle:vertical { background:#ddd8cc; border-radius:4px; }"
        )
        self.report_view.document().setDocumentMargin(0)
        col.addWidget(self.report_view, 1)
        footer = QHBoxLayout()
        self.report_status = QLabel("")
        self.report_status.setStyleSheet("color:#a9a396; font-size:11px; background:transparent;")
        footer.addWidget(self.report_status, 1)
        save_b = QPushButton("Save as Markdown")
        save_b.setCursor(Qt.CursorShape.PointingHandCursor)
        save_b.setStyleSheet(
            "QPushButton { background:transparent; color:#7a6fa8; border:1px solid #d8d2e6;"
            " border-radius:6px; padding:8px 16px; font-size:13px; }"
            "QPushButton:hover { background:#f0ecf8; }"
        )
        save_b.clicked.connect(self.save_report)
        self.deeper_b = QPushButton("Go deeper  ↓")
        self.deeper_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deeper_b.setStyleSheet(
            "QPushButton { background:transparent; color:#7a6fa8; border:1px solid #d8d2e6;"
            " border-radius:6px; padding:8px 16px; font-size:13px; }"
            "QPushButton:hover { background:#f0ecf8; }"
            "QPushButton:disabled { color:#c7c2b6; border-color:#e4e0d6; }"
        )
        self.deeper_b.clicked.connect(self.go_deeper)
        footer.addWidget(self.deeper_b)
        footer.addWidget(save_b)
        open_b = QPushButton("Open your journal  →")
        open_b.setCursor(Qt.CursorShape.PointingHandCursor)
        open_b.setStyleSheet(
            "QPushButton { background:#7a6fa8; color:white; border:none; border-radius:6px;"
            " padding:8px 20px; font-size:13px; }"
            "QPushButton:hover { background:#8d82bb; }"
        )
        open_b.clicked.connect(self.open_journal.emit)
        footer.addWidget(open_b)
        col.addLayout(footer)
        row.addStretch(1)
        row.addWidget(holder)
        row.addStretch(1)
        return page

    # --- the model ---------------------------------------------------------

    def _start_warmup(self) -> None:
        if not self.model_path or self.model_path.startswith("model://"):
            return
        self._warmup = WarmupWorker(self.model_path, PRACTICE)
        self._warmup.ready.connect(self._on_warm)
        self._warmup.start()

    def _on_warm(self, engine) -> None:
        if engine is None:
            return
        if self.engine is None:
            self.engine = engine
        else:
            engine.close()

    def ensure_engine(self) -> Engine | None:
        if self.engine is not None:
            return self.engine
        if self._warmup is not None and self._warmup.isRunning():
            while self._warmup.isRunning():
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                self._warmup.wait(50)
            if self.engine is not None:
                return self.engine
        try:
            self.engine = Engine(self.model_path, DEFAULT_PROMPT, PRACTICE)
        except Exception:  # noqa: BLE001 - the journey must never block on the model
            return None
        return self.engine

    # --- flow --------------------------------------------------------------

    def begin(self) -> None:
        if self.stack.currentWidget() is not self.intro:
            return
        self.mark.stop()
        self.stack.setCurrentWidget(self.question_screen)
        self._show_question(0)

    def _show_question(self, index: int) -> None:
        self.index = index
        self.followups = []
        self.marks = []
        label, why = self.meanings[index]
        left = minutes_left(index, len(self.script))
        self.q_where.setText(
            f"{index + 1} OF {len(self.script)}   ·   {label.upper()}"
            + (f"   ·   ~{left} MIN LEFT" if left else "")
        )
        self.q_text.setText(self.script[index])
        self.q_meaning.setText(why)
        self.q_followup.hide()
        self.q_followup.setText("")
        self.editor.clear()
        self.q_status.setText("")
        self.next_button.setEnabled(True)
        self.next_button.setText("Next  →")
        self.path.animate_to(index)
        fade_in(self.q_text, 800)
        fade_in(self.q_meaning, 1100)
        if index == MIDPOINT:
            quote, who = QUOTES["midpoint"]
            self.q_status.setText(f"“{quote}”  — {who}")
        self.editor.setFocus()

    def _current_turn(self) -> Turn:
        text = self.editor.toPlainText().strip()
        turn = Turn(self.index, self.script[self.index], answer=text,
                    followups=list(self.followups),
                    brief=(self.index == len(self.script) - 1))
        return turn

    def next_step(self) -> None:
        if self.stack.currentWidget() is not self.question_screen:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        turn = self._current_turn()
        if not turn.answer:
            self.q_status.setText("Write something here, or skip it.")
            return
        if needs_followup(turn):
            self._request_followup(turn)
            return
        self._commit_and_advance()

    def skip(self) -> None:
        if self.stack.currentWidget() is not self.question_screen:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.editor.clear()
        self.followups = []
        self.marks = []
        self._commit_and_advance()

    def _request_followup(self, turn: Turn) -> None:
        engine = self.ensure_engine()
        if engine is None:
            self._commit_and_advance()  # no model: never block the journey
            return
        if engine.practice != PRACTICE:
            engine.set_practice(PRACTICE)
        self.next_button.setEnabled(False)
        self.next_button.setText("Thinking…")
        self.q_status.setText("One more thing about that…")
        slice_page = followup_page(turn, self.day, self.model_path, DEFAULT_PROMPT)
        self.worker = AskWorker(engine, slice_page, (), tuple(self.followups))
        self.worker.finished_ok.connect(self._on_followup)
        self.worker.failed.connect(lambda _m: self._commit_and_advance())
        self.worker.start()

    def _on_followup(self, question: str) -> None:
        self.next_button.setEnabled(True)
        self.next_button.setText("Next  →")
        question = (question or "").strip()
        if not question or len(self.followups) >= MAX_FOLLOWUPS:
            self._commit_and_advance()
            return
        self.followups.append(question)
        self.marks.append(len(self.editor.toPlainText()))
        self.q_followup.setText(question)
        self.q_followup.show()
        fade_in(self.q_followup, 600)
        self.q_status.setText("")
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        if not self.editor.toPlainText().endswith("\n"):
            self.editor.insertPlainText("\n\n")
        self.editor.setFocus()

    def _commit_and_advance(self) -> None:
        """Write this question into the session -- question, answer, and any
        follow-ups in the order they happened -- then move on."""
        text = self.editor.toPlainText()
        self.blocks.append(Block(QUESTION, self.script[self.index]))
        cuts = [0] + self.marks + [len(text)]
        pieces = [text[a:b].strip() for a, b in zip(cuts, cuts[1:])]
        for i, piece in enumerate(pieces):
            if piece:
                self.blocks.append(Block(WRITING, piece))
            if i < len(self.followups):
                self.blocks.append(Block(QUESTION, self.followups[i]))
        self._save_session()
        nxt = self.index + 1
        if nxt >= len(self.script):
            self._finish()
        else:
            self._show_question(nxt)

    def _save_session(self) -> Page:
        self.session = Page(day=self.day, model=self.model_path, prompt_version=DEFAULT_PROMPT,
                            practice=PRACTICE, blocks=list(self.blocks))
        try:
            save(self.session, self.journal_dir)
        except OSError:
            pass
        return self.session

    def _finish(self, session: Page | None = None) -> None:
        session = session or self._save_session()
        self.session = session
        self.stack.setCurrentWidget(self.reading)
        self.reading_path.set_progress(len(self.script) - 1)
        self.reading_status.setText("")
        engine = self.ensure_engine()
        if engine is None:
            self.reading_title.setText("The model is unavailable, so the picture can't be drawn yet.")
            return
        self._reader = ReviewWorker(engine, session, self.script, self.journal_dir)
        self._reader.progress.connect(
            lambda i, n: self.reading_status.setText(f"{i} of {n}")
        )
        self._reader.done.connect(self._on_read)
        self._reader.failed.connect(
            lambda m: self.reading_title.setText(f"Could not read every answer — {m}")
        )
        self._reader.start()

    def _on_read(self, records) -> None:
        from journal.review import unanswered

        summary = aggregate(list(records))
        summary.unanswered = [(self.session.day, q) for q in unanswered(self.session, self.script)]
        self.summary = summary
        # Phase two: the reading itself -- the part that is actually worth an hour.
        engine = self.ensure_engine()
        if engine is None:
            self._show_report()
            return
        self.reading_title.setText("Writing your reading…")
        self.reading_status.setText("")
        self._writer = PortraitWorker(self.journal_dir, engine, self.session, self.script)
        self._writer.progress.connect(lambda i, n: self.reading_status.setText(f"{i} of {n}"))
        self._writer.done.connect(self._on_written)
        self._writer.failed.connect(lambda _m: self._show_report())
        self._writer.start()

    def _on_written(self, portrait) -> None:
        self.portrait = portrait
        self._show_report()

    def _show_report(self) -> None:
        self._render_report()
        self.stack.setCurrentWidget(self.report)
        fade_in(self.report_view, 900)
        mark_done(self.journal_dir)
        self.report_status.setText("Read on this machine. Nothing left it.")
        # A deeper reading is only offered once the short one, and its portrait,
        # are actually here to build on.
        self.deeper_b.setVisible(self.portrait is not None and self.deep is None)
        self.finished.emit()

    def _render_report(self) -> None:
        self.report_view.setHtml(render_html(
            self.summary, title="Where you stand", portrait=self.portrait, deep=self.deep))

    def go_deeper(self) -> None:
        if self.portrait is None or self.session is None or self.deep is not None:
            return
        engine = self.ensure_engine()
        if engine is None:
            self.report_status.setText("The model is unavailable, so the deeper reading can't be drawn.")
            return
        self.deeper_b.setDisabled(True)
        self.report_status.setText("Writing the deeper reading… this takes a minute.")
        self._deep_worker = DeepWorker(
            self.journal_dir, engine, self.session, self.script, self.portrait)
        self._deep_worker.progress.connect(
            lambda i, n: self.report_status.setText(f"Writing the deeper reading… {i} of {n}"))
        self._deep_worker.done.connect(self._on_deep)
        self._deep_worker.failed.connect(
            lambda m: (self.deeper_b.setDisabled(False),
                       self.report_status.setText(f"Could not write the deeper reading — {m}")))
        self._deep_worker.start()

    def _on_deep(self, deep) -> None:
        self.deep = deep
        self._render_report()
        self.deeper_b.setVisible(False)
        self.report_status.setText("Read on this machine. Nothing left it.")

    def see_demo(self) -> None:
        """Jump straight to a fully-worked sample report, built without the
        model or any real answers. A preview of what the hour earns you."""
        self.mark.stop()
        self.summary = demo_summary()
        self.portrait = demo_portrait()
        self.deep = demo_deep()
        self.session = None
        self._render_report()
        self.stack.setCurrentWidget(self.report)
        fade_in(self.report_view, 900)
        self.deeper_b.setVisible(False)  # the deeper reading is already shown
        self.report_status.setText(
            "A sample reading — invented, to show the shape. Your own is drawn "
            "from your answers, on this machine."
        )

    def fast_forward(self) -> None:
        """Stage shortcut: use a finished session already on disk."""
        session = seeded_session(self.journal_dir, self.script)
        if session is None:
            self.q_status.setText("No finished session on disk to jump to.")
            return
        self.mark.stop()
        self.blocks = list(session.blocks)
        self._finish(session)

    def save_report(self) -> None:
        if self.stack.currentWidget() is not self.report or not self.summary.days:
            return
        name = (
            "sample-reading.md" if self.session is None
            else f"where-you-stand-{self.day.isoformat()}.md"
        )
        try:
            path = write_export(
                self.journal_dir,
                render_markdown(self.summary, title="Where you stand",
                                portrait=self.portrait, deep=self.deep),
                name,
            )
            self.report_status.setText(f"Saved to {path}")
        except OSError as exc:
            self.report_status.setText(f"Could not save — {exc}")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)
        if self._reader is not None and self._reader.isRunning():
            self._reader.wait(3000)
        if self._writer is not None and self._writer.isRunning():
            self._writer.wait(3000)
        if self._deep_worker is not None and self._deep_worker.isRunning():
            self._deep_worker.wait(3000)
        if self._warmup is not None and self._warmup.isRunning():
            self._warmup.wait(3000)
        if self.engine is not None:
            self.engine.close()
        event.accept()
