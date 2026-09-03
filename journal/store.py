"""Journal sessions on disk, as plain Markdown.

Deliberately dependency-free: a journal should outlive the app that wrote it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SPEAKERS = ("ai", "me")
_TURN_RE = re.compile(r"^## (ai|me)\s*$", re.MULTILINE)


@dataclass
class Turn:
    speaker: str
    text: str


@dataclass
class Session:
    started: datetime
    model: str
    prompt_version: str
    turns: list[Turn] = field(default_factory=list)


def render(session: Session) -> str:
    lines = [
        "---",
        f"started: {session.started.isoformat()}",
        f"model: {session.model}",
        f"prompt_version: {session.prompt_version}",
        "---",
        "",
    ]
    for turn in session.turns:
        lines.append(f"## {turn.speaker}")
        lines.append("")
        lines.append(turn.text.strip())
        lines.append("")
    return "\n".join(lines)


def parse(text: str) -> Session:
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

    turns: list[Turn] = []
    matches = list(_TURN_RE.finditer(body))
    for index, match in enumerate(matches):
        start = match.end()
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        turns.append(Turn(match.group(1), body[start:stop].strip()))

    started_raw = meta.get("started", "")
    try:
        started = datetime.fromisoformat(started_raw)
    except ValueError:
        started = datetime.min

    return Session(
        started=started,
        model=meta.get("model", "unknown"),
        prompt_version=meta.get("prompt_version", "unknown"),
        turns=turns,
    )


def save(session: Session, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session.started:%Y-%m-%d-%H%M}.md"
    path.write_text(render(session), encoding="utf-8")
    return path


def load(path: Path) -> Session:
    return parse(path.read_text(encoding="utf-8"))


def list_sessions(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.md"))
