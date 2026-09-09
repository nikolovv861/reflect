"""Practices: named reflective frames a page can be written inside.

A practice supplies two things a blank page cannot: an opening prompt so the
writer never faces nothing, and an addendum to the system prompt so the
follow-up question knows what kind of writing this is.

A practice also has an ARC -- a number of days after which it is simply
finished. That is the honest alternative to a streak: a reason to come back
tomorrow that ends, rather than a counter that can be broken and shame you.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).parent
DEFAULT = "free"

# Openings within a practice are separated by a line containing only "--".
_SPLIT = "\n--\n"


@dataclass(frozen=True)
class Practice:
    slug: str
    name: str
    arc: int  # 0 = open-ended, 1 = one-off, N = an N-day practice
    openings: tuple[str, ...]
    addendum: str
    # Optional, one per opening: a short label on the first line, then a line
    # on why this question is being asked. Used by the guided journey.
    meanings: tuple[str, ...] = ()

    def opening_for(self, day_index: int) -> str:
        """The prompt to seed day N with. Cycles if the arc outruns the list."""
        if not self.openings:
            return ""
        return self.openings[max(0, day_index) % len(self.openings)]

    @property
    def is_open_ended(self) -> bool:
        return self.arc == 0


def _section(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    nxt = body.find("\n## ", start)
    return body[start : nxt if nxt != -1 else len(body)].strip()


def load_practice(slug: str) -> Practice:
    path = _DIR / f"{slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"no practice named {slug!r} in {_DIR}")
    raw = path.read_text(encoding="utf-8")

    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip()] = value.strip()
            body = raw[end + 4 :]

    opening_text = _section(body, "opening")
    openings = tuple(
        part.strip() for part in opening_text.split(_SPLIT) if part.strip()
    )

    try:
        arc = int(meta.get("arc", "0"))
    except ValueError:
        arc = 0

    meaning_text = _section(body, "meanings")
    meanings = tuple(
        part.strip() for part in meaning_text.split(_SPLIT) if part.strip()
    )

    return Practice(
        slug=slug,
        name=meta.get("name", slug),
        arc=arc,
        openings=openings,
        addendum=_section(body, "addendum"),
        meanings=meanings,
    )


def list_practices() -> list[Practice]:
    """All practices, with free writing first and the rest alphabetical."""
    slugs = sorted(p.stem for p in _DIR.glob("*.md"))
    ordered = [DEFAULT] + [s for s in slugs if s != DEFAULT]
    return [load_practice(s) for s in ordered if (_DIR / f"{s}.md").exists()]
