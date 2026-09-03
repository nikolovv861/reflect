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


def list_pages(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))
