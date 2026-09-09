"""A year review in one sitting: fourteen questions, a follow-up when an
answer is thin, and at the end a picture of where you stand.

The questions live in `practices/year-review.md` -- a practice, so the script
is a file, not code, and the arc is the number of questions. A session is an
ordinary journal page: each question is a QUESTION block, each answer the
WRITING after it, and a follow-up is just another QUESTION. So the whole
review is plain Markdown on disk like everything else, and a skipped question
shows up, truthfully, as one you never answered.

Topic flow is deterministic: the app advances on a rule (enough words, or the
follow-up budget spent), and the model only ever writes the follow-up itself,
which is the thing it is good at. Nothing here scores the writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from journal.practices import load_practice
from journal.store import QUESTION, WRITING, Block, Page
from journal.year import ExtractorLike, INSTRUCTIONS, SCHEMA, Record, parse_record

PRACTICE = "year-review"
# The nightly examen -- a short guided practice that walks its questions one at
# a time like the year review, but closes on "Seal the day" rather than a
# year's portrait.
EVENING_PRACTICE = "evening"
# Practices driven as a guided sequence (one question at a time, Next/Skip)
# rather than as open free-writing.
GUIDED = frozenset({PRACTICE, EVENING_PRACTICE})
SUFFICIENT_WORDS = 30   # below this, ask for the missing piece
MAX_FOLLOWUPS = 2       # then move on regardless
MINUTES_PER_QUESTION = 4


def questions() -> list[str]:
    return list(load_practice(PRACTICE).openings)


def meanings() -> list[tuple[str, str]]:
    """(label, why-this-question) per question, padded if the file is short."""
    raw = list(load_practice(PRACTICE).meanings)
    out: list[tuple[str, str]] = []
    for i in range(len(questions())):
        text = raw[i] if i < len(raw) else ""
        label, _, why = text.partition("\n")
        out.append((label.strip() or f"Question {i + 1}", " ".join(why.split())))
    return out


@dataclass
class Turn:
    """One premade question, its follow-ups, and everything written under it."""

    index: int
    question: str
    answer: str = ""
    followups: list[str] = field(default_factory=list)
    # The closing question asks for ONE sentence; a brief answer is the point.
    brief: bool = False

    @property
    def words(self) -> int:
        return len(self.answer.split())

    @property
    def sufficient(self) -> bool:
        if self.brief:
            return bool(self.answer.strip())
        return self.words >= SUFFICIENT_WORDS

    @property
    def exhausted(self) -> bool:
        return len(self.followups) >= MAX_FOLLOWUPS


def _norm(text: str) -> str:
    return " ".join(text.split())


def _split_questions(text: str, script: list[str]) -> list[tuple[int | None, str]]:
    """Break a question block into (script index or None, text) pieces.

    Questions wrap across lines in the file and in the editor, and two script
    questions can end up in one block (a skipped question against the next),
    so matching is whitespace-insensitive and peels script questions off the
    front one at a time. Anything left over is a follow-up.
    """
    pieces: list[tuple[int | None, str]] = []
    rest = _norm(text)
    ordered = sorted(enumerate(script), key=lambda iq: -len(iq[1]))
    while rest:
        for index, q in ordered:
            nq = _norm(q)
            if rest.startswith(nq):
                pieces.append((index, q.strip()))
                rest = rest[len(nq):].strip()
                break
        else:
            pieces.append((None, rest))
            break
    return pieces


def turns(page: Page, script: list[str] | None = None) -> list[Turn]:
    """Read a session page back into turns.

    A block that matches a script question starts a new turn; any other
    question is a follow-up inside the current one; writing accumulates
    into the current turn's answer.
    """
    script = script if script is not None else questions()
    out: list[Turn] = []
    current: Turn | None = None
    last = len(script) - 1
    for block in page.blocks:
        text = block.text.strip()
        if block.kind == QUESTION:
            for index, piece in _split_questions(text, script):
                if index is not None:
                    current = Turn(index, piece, brief=(index == last))
                    out.append(current)
                elif current is not None:
                    current.followups.append(piece)
        elif block.kind == WRITING and current is not None and text:
            current.answer = (current.answer + "\n\n" + text).strip()
    return out


def next_index(page: Page, script: list[str] | None = None) -> int:
    """Index of the next premade question to ask; len(script) when done."""
    script = script if script is not None else questions()
    done = turns(page, script)
    return (done[-1].index + 1) if done else 0


def needs_followup(turn: Turn) -> bool:
    return bool(turn.answer.strip()) and not turn.sufficient and not turn.exhausted


def minutes_left(index: int, total: int) -> int:
    return max(0, (total - index) * MINUTES_PER_QUESTION)


def progress_label(index: int, total: int) -> str:
    """'5 OF 14 · ~35 MIN LEFT' -- progress, never a score."""
    shown = min(index + 1, total)
    left = minutes_left(index, total)
    tail = f" · ~{left} MIN LEFT" if left else ""
    return f"{shown} OF {total}{tail}"


def followup_page(turn: Turn, day, model: str, prompt_version: str) -> Page:
    """The slice of the session the model sees when asked for a follow-up:
    just this question and what was written under it -- not the whole review,
    so the follow-up stays on the one topic."""
    blocks = [Block(QUESTION, turn.question)]
    if turn.answer:
        blocks.append(Block(WRITING, turn.answer))
    for f in turn.followups:
        blocks.append(Block(QUESTION, f))
    return Page(day=day, model=model, prompt_version=prompt_version,
                practice=PRACTICE, blocks=blocks)


# --- the picture at the end -----------------------------------------------

REVIEW_INSTRUCTIONS = INSTRUCTIONS.replace(
    "You read one private journal entry",
    "You read one answer from someone's private year review",
)


def extract_turn(engine: ExtractorLike, turn: Turn, day) -> Record | None:
    """One Record for one answered question (None if it was skipped)."""
    if not turn.answer.strip():
        return None
    content = f"QUESTION:\n{turn.question}\n\nANSWER:\n{turn.answer}\n\nJSON:"
    raw = engine.extract_json(REVIEW_INSTRUCTIONS, content, SCHEMA)
    record = parse_record(raw, day, turn.words)
    if record is not None:
        record.topic = turn.question
    return record


def review_records(engine: ExtractorLike, page: Page,
                   script: list[str] | None = None) -> list[Record]:
    """One Record per answered question, in question order."""
    records: list[Record] = []
    for turn in turns(page, script):
        record = extract_turn(engine, turn, page.day)
        if record is not None:
            records.append(record)
    return records


def review_records_cached(directory, engine: ExtractorLike | None, page: Page,
                          script: list[str], on_progress=None) -> list[Record]:
    """Like review_records, but each answer is read once and cached beside the
    journal, so a finished session comes back instantly."""
    import hashlib
    import json
    from dataclasses import asdict
    from pathlib import Path

    from journal.year import cache_dir

    directory = Path(directory)
    all_turns = turns(page, script)
    records: list[Record] = []
    for i, turn in enumerate(all_turns):
        if turn.answer.strip():
            key = hashlib.sha256((turn.question + "\n" + turn.answer).encode("utf-8")).hexdigest()[:20]
            path = cache_dir(directory) / f"review-{page.day.isoformat()}-{turn.index:02d}-{key}.json"
            record = None
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["day"] = page.day
                    record = Record(**data)
                except (ValueError, TypeError, KeyError):
                    record = None
            if record is None and engine is not None:
                record = extract_turn(engine, turn, page.day)
                if record is not None:
                    cache_dir(directory).mkdir(parents=True, exist_ok=True)
                    data = asdict(record)
                    data["day"] = page.day.isoformat()
                    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if record is not None:
                records.append(record)
        if on_progress:
            on_progress(i + 1, len(all_turns))
    return records


def unanswered(page: Page, script: list[str] | None = None) -> list[str]:
    """Script questions that were reached but never answered (skipped)."""
    return [t.question for t in turns(page, script) if not t.answer.strip()]
