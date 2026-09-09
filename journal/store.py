"""A day's journal page on disk, as plain Markdown.

Deliberately dependency-free: a journal should outlive the app that wrote it.

The unit is the DAY, not a session or a conversation. Opening the app twice on
the same date continues one page rather than starting something new.

Your own writing is stored as ordinary paragraphs. Questions are stored as
Markdown blockquotes, so the file reads correctly in any editor and your words
remain the bulk of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from pathlib import Path

WRITING = "me"
QUESTION = "ai"


@dataclass
class Block:
    kind: str  # WRITING | QUESTION
    text: str


@dataclass
class Page:
    day: Date
    model: str
    prompt_version: str
    practice: str = "free"
    blocks: list[Block] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks if b.kind == WRITING)


def render(page: Page) -> str:
    lines = [
        "---",
        f"date: {page.day.isoformat()}",
        f"model: {page.model}",
        f"prompt_version: {page.prompt_version}",
        f"practice: {page.practice}",
        "---",
        "",
    ]
    for block in page.blocks:
        if block.kind == QUESTION:
            for line in block.text.strip().splitlines():
                lines.append(f"> {line}")
        else:
            lines.extend(block.text.strip("\n").splitlines())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse(text: str) -> Page:
    meta: dict[str, str] = {}
    body = text

    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            body = text[end + 4 :]

    blocks: list[Block] = []
    kind: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if kind is None:
            return
        joined = "\n".join(buffer).strip("\n")
        if joined.strip():
            blocks.append(Block(kind, joined))

    for line in body.splitlines():
        line_kind = QUESTION if line.startswith(">") else WRITING
        content = line[1:].lstrip() if line_kind is QUESTION else line
        if line_kind != kind:
            flush()
            kind = line_kind
            buffer = [content]
        else:
            buffer.append(content)
    flush()

    try:
        day = Date.fromisoformat(meta.get("date", ""))
    except ValueError:
        day = Date.min

    return Page(
        day=day,
        model=meta.get("model", "unknown"),
        prompt_version=meta.get("prompt_version", "unknown"),
        practice=meta.get("practice", "free"),
        blocks=blocks,
    )


def path_for(directory: Path, day: Date) -> Path:
    return directory / f"{day.isoformat()}.md"


def save(page: Page, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = path_for(directory, page.day)
    path.write_text(render(page), encoding="utf-8")
    return path


def load(path: Path) -> Page:
    return parse(path.read_text(encoding="utf-8"))


def open_day(
    directory: Path,
    model: str,
    prompt_version: str,
    day: Date | None = None,
) -> Page:
    """Today's page, continued if it already exists."""
    day = day or datetime.now().date()
    path = path_for(directory, day)
    if path.exists():
        page = load(path)
        page.model = model
        page.prompt_version = prompt_version
        return page
    return Page(day=day, model=model, prompt_version=prompt_version)


def practice_day(directory: Path, practice: str, upto: Date) -> int:
    """Which day of a practice `upto` is -- 1-based, counting only days written.

    Deliberately counts days PRESENT, never days missed. Skip Tuesday and
    Wednesday is still the next day of the practice, not a broken streak.
    """
    count = 0
    for path in list_pages(directory):
        try:
            day = Date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day > upto:
            continue
        page = load(path)
        if page.practice == practice and (page.blocks or day == upto):
            count += 1
    return max(1, count)


def practice_history(
    directory: Path,
    practice: str,
    upto: Date,
    limit: int = 3,
) -> list[Page]:
    """Earlier pages written inside the same practice, before `upto`.

    Newest first, capped at `limit`, and only pages that were actually written
    on (skips empty ones). This is what gives a practice an arc the FOLLOW-UP
    QUESTION can feel, not just a header counter: on day 3 of an Attention
    Inventory the question can build on what was noticed on days 1 and 2.

    It is context, never a transcript -- see engine.page_text for how it is
    framed to the model, with an explicit instruction never to tally the days
    or grade the arc.
    """
    history: list[Page] = []
    for page in recent_pages(directory):  # newest first
        if page.day >= upto:
            continue
        if page.practice != practice:
            continue
        if not any(b.kind == WRITING and b.text.strip() for b in page.blocks):
            continue
        history.append(page)
        if limit and len(history) >= limit:
            break
    return history


def list_pages(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))


def _months_before(day: Date, months: int) -> Date | None:
    """The same day-of-month, `months` earlier. None if it doesn't exist
    (e.g. no 31 January when stepping back from 31 March)."""
    total = (day.year * 12 + (day.month - 1)) - months
    year, month = divmod(total, 12)
    try:
        return day.replace(year=year, month=month + 1)
    except ValueError:
        return None


def on_this_day(directory: Path, today: Date, max_items: int = 3) -> list[tuple[str, Page]]:
    """Past entries worth rereading today: the same date in earlier years, and
    a month ago. Newest first, labelled ("A year ago", "A month ago", ...).

    Rereading is half of what makes a journal a journal. This is a door back
    in, never a judgment -- there is no count of what you missed, only what you
    once wrote on a day like this.
    """
    def written(page: Page) -> bool:
        return any(b.kind == WRITING and b.text.strip() for b in page.blocks)

    found: list[tuple[str, Page]] = []

    for page in recent_pages(directory):
        d = page.day
        if d >= today or not written(page):
            continue
        if d.month == today.month and d.day == today.day:
            years = today.year - d.year
            label = "A year ago" if years == 1 else f"{years} years ago"
            found.append((label, page))

    month_ago = _months_before(today, 1)
    if month_ago is not None:
        path = path_for(directory, month_ago)
        if path.exists():
            page = load(path)
            if written(page):
                found.append(("A month ago", page))

    return found[:max_items]


def recent_pages(directory: Path, limit: int | None = None) -> list[Page]:
    """Every day written, newest first. This is how you reread your past."""
    pages: list[Page] = []
    for path in reversed(list_pages(directory)):
        try:
            Date.fromisoformat(path.stem)
        except ValueError:
            continue
        pages.append(load(path))
        if limit and len(pages) >= limit:
            break
    return pages


# --- standing notes --------------------------------------------------------
#
# Undated documents that persist: core values, the goal, anything you return
# to. A dated page is a record of one day; a note is a thing you keep editing.


@dataclass
class Note:
    slug: str
    title: str
    text: str = ""

    @property
    def words(self) -> int:
        return len(self.text.split())


def notes_dir(directory: Path) -> Path:
    return directory / "notes"


def slugify(title: str) -> str:
    kept = [c.lower() if c.isalnum() else "-" for c in title.strip()]
    slug = "".join(kept)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "note"


def render_note(note: Note) -> str:
    return f"---\ntitle: {note.title}\n---\n\n{note.text.strip()}\n"


def parse_note(slug: str, raw: str) -> Note:
    title = slug.replace("-", " ").title()
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            for line in raw[4:end].splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "title" and value.strip():
                    title = value.strip()
            body = raw[end + 4 :]
    return Note(slug=slug, title=title, text=body.strip())


def save_note(directory: Path, note: Note) -> Path:
    target = notes_dir(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{note.slug}.md"
    path.write_text(render_note(note), encoding="utf-8")
    return path


def load_note(directory: Path, slug: str) -> Note:
    path = notes_dir(directory) / f"{slug}.md"
    return parse_note(slug, path.read_text(encoding="utf-8"))


def list_notes(directory: Path) -> list[Note]:
    target = notes_dir(directory)
    if not target.exists():
        return []
    return [
        parse_note(p.stem, p.read_text(encoding="utf-8"))
        for p in sorted(target.glob("*.md"))
    ]


SEEDS = {
    "core-values": (
        "Core values",
        "The three things that matter most to you.\n\n"
        "For each one:\n"
        "- Why could you not live without it?\n"
        "- Where did it come from -- what happened that made it matter?\n"
        "- What has holding it actually cost you?\n"
        "- What would a life that ignored it look like?\n\n"
        "(Most people never spend five minutes on this. The point is not to "
        "pick impressive values -- it is to find out which ones are already "
        "running things.)\n",
    ),
    "goal": (
        "Goal",
        "What are you actually working toward right now?\n\n"
        "- What is the project? One sentence.\n"
        "- Which of your values does it serve? If none, that is worth "
        "knowing.\n"
        "- What does the smallest honest version of a good day on it look "
        "like?\n"
        "- What would tell you it is finished?\n",
    ),
}


def seed_notes(directory: Path) -> bool:
    """Create starter notes the first time, so the shelf is never bare.

    Only ever runs when no notes directory exists. Never overwrites.
    """
    if notes_dir(directory).exists():
        return False
    for slug, (title, text) in SEEDS.items():
        save_note(directory, Note(slug=slug, title=title, text=text))
    return True


def delete_note(directory: Path, slug: str) -> None:
    path = notes_dir(directory) / f"{slug}.md"
    if path.exists():
        path.unlink()


# --- search ----------------------------------------------------------------


@dataclass
class Hit:
    kind: str  # "page" | "note"
    key: str  # ISO date, or note slug
    title: str
    snippet: str


def _snippet(text: str, needle: str, width: int = 70) -> str:
    lowered = text.lower()
    at = lowered.find(needle.lower())
    if at == -1:
        return text[:width].strip()
    start = max(0, at - width // 3)
    end = min(len(text), at + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ").strip() + suffix


def _match(haystack: str, terms: list[str]) -> int:
    """Total occurrences of every term, or 0 unless ALL terms are present.

    Multi-word queries are an AND: "deadline standup" finds only text that
    mentions both. The count is used to rank -- denser matches float up.
    """
    lowered = haystack.lower()
    if not all(term in lowered for term in terms):
        return 0
    return sum(lowered.count(term) for term in terms)


def search(directory: Path, query: str) -> list[Hit]:
    """Search every page and note. Case-insensitive, multi-term (AND), ranked.

    A single word behaves exactly as a plain substring search always did. Two
    or more words must all appear, and results come back densest-match first so
    the page that is most about what you asked is at the top.
    """
    terms = query.strip().lower().split()
    if not terms:
        return []

    scored: list[tuple[int, Hit]] = []
    first = terms[0]

    for page in recent_pages(directory):
        body = "\n".join(b.text for b in page.blocks)
        score = _match(body, terms)
        if score:
            scored.append(
                (
                    score,
                    Hit(
                        "page",
                        page.day.isoformat(),
                        page.day.strftime("%d %B %Y"),
                        _snippet(body, first),
                    ),
                )
            )

    for note in list_notes(directory):
        haystack = f"{note.title}\n{note.text}"
        score = _match(haystack, terms)
        if score:
            scored.append(
                (score, Hit("note", note.slug, note.title, _snippet(note.text, first)))
            )

    # Densest match first; recent_pages already gives a sensible newest-first
    # order within a tie, so a stable sort preserves it.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [hit for _, hit in scored]
