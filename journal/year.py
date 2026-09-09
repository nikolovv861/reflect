"""Your year on one page: structured records drawn from every entry.

Runs entirely on the local model. Each day's writing becomes one small JSON
record -- the people who appear, the places, a few themes from a fixed list,
how the writer sounded, one thing left open, and a phrase in their own words.
The sampler is constrained to the schema, so a 4B model cannot hand back
broken JSON; and themes come from a closed list because a small model is far
better at picking from a menu than at inventing tags.

Records are cached by content hash beside the journal, so a year is extracted
once and then updated incrementally as you write.

Nothing here is a score. `energy` is how you *sounded*, kept as a faint line
and never shown as a number; there are no streaks and no comparisons. The page
this feeds is a mirror, not a grade.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date as Date
from pathlib import Path
from typing import Callable, Protocol

from journal.store import QUESTION, WRITING, Page, list_pages, load

THEMES: tuple[str, ...] = (
    "work",
    "family",
    "health",
    "money",
    "creativity",
    "relationships",
    "avoidance",
    "rest",
    "friends",
    "learning",
)

SCHEMA: dict = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "string"}},
        "themes": {
            "type": "array",
            "items": {"type": "string", "enum": list(THEMES)},
        },
        "energy": {"type": "integer", "minimum": -2, "maximum": 2},
        "unresolved": {"type": "string"},
        "key_phrase": {"type": "string"},
    },
    "required": ["people", "places", "themes", "energy", "unresolved", "key_phrase"],
}

INSTRUCTIONS = (
    "You read one private journal entry and fill in a JSON record about it.\n"
    "people: names or roles that appear (e.g. 'Maria', 'my manager'); empty if "
    "none. places: locations mentioned; empty if none. themes: one to three, "
    "chosen ONLY from the allowed list. energy: how the writer sounds, from -2 "
    "(drained) to 2 (alive); 0 is neutral. unresolved: one thing left open, in "
    "a few words, or an empty string. key_phrase: a short phrase copied "
    "exactly from the entry, in the writer's own words.\n"
    "Output only the JSON."
)


class ExtractorLike(Protocol):
    def extract_json(self, instructions: str, content: str, schema: dict) -> str: ...


@dataclass
class Record:
    day: Date
    words: int
    people: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    energy: int = 0
    unresolved: str = ""
    key_phrase: str = ""
    # The app's own questions that got no writing after them.
    unanswered: list[str] = field(default_factory=list)
    # For a year-review session: the premade question this answer belongs to.
    topic: str = ""


# --- one entry -----------------------------------------------------------


def writing_of(page: Page) -> str:
    return "\n\n".join(b.text for b in page.blocks if b.kind == WRITING and b.text.strip())


def unanswered_questions(page: Page) -> list[str]:
    """Questions the app asked that were never followed by any writing."""
    left: list[str] = []
    for i, block in enumerate(page.blocks):
        if block.kind != QUESTION:
            continue
        followed = any(
            later.kind == WRITING and later.text.strip() for later in page.blocks[i + 1 :]
        )
        if not followed:
            left.append(block.text.strip())
    return left


def _dedupe(items: list, stop: frozenset[str] = frozenset()) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip().strip(".,;:")
        key = text.lower()
        if text and key not in seen and key not in stop:
            seen.add(key)
            out.append(text)
    return out


# Not people: a small model reads "other people's deadlines" as a person.
_NOT_PEOPLE = frozenset({
    "people", "other people", "someone", "nobody", "everyone", "anyone",
    "no one", "myself", "me", "i", "you", "my phone", "the phone", "them",
})

_KEY_PHRASE_MAX = 160


def _first_sentence(text: str, limit: int = _KEY_PHRASE_MAX) -> str:
    """A key phrase should be a phrase. If the model copied a whole answer,
    keep its first sentence (or the first `limit` characters)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    for end in (". ", "! ", "? ", "; "):
        cut = text.find(end)
        if 20 <= cut <= limit:
            return text[: cut + 1].strip()
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def parse_record(raw: str, day: Date, words: int) -> Record | None:
    """Turn the model's JSON into a Record, tolerating small slips."""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    themes = [
        t for t in _dedupe(obj.get("themes") or []) if t.lower() in THEMES
    ]
    try:
        energy = int(obj.get("energy", 0))
    except (TypeError, ValueError):
        energy = 0
    energy = max(-2, min(2, energy))

    return Record(
        day=day,
        words=words,
        people=_dedupe(obj.get("people") or [], _NOT_PEOPLE),
        places=_dedupe(obj.get("places") or []),
        themes=[t.lower() for t in themes][:3],
        energy=energy,
        unresolved=str(obj.get("unresolved") or "").strip(),
        key_phrase=_first_sentence(str(obj.get("key_phrase") or "")),
    )


def extract(engine: ExtractorLike, page: Page) -> Record | None:
    text = writing_of(page)
    if not text.strip():
        return None
    raw = engine.extract_json(INSTRUCTIONS, f"ENTRY:\n{text}\n\nJSON:", SCHEMA)
    record = parse_record(raw, page.day, len(text.split()))
    if record is not None:
        record.unanswered = unanswered_questions(page)
    return record


# --- the cache -------------------------------------------------------------


def cache_dir(directory: Path) -> Path:
    return directory / ".year"


def _fingerprint(page: Page) -> str:
    return hashlib.sha256(writing_of(page).encode("utf-8")).hexdigest()[:24]


def _cache_path(directory: Path, page: Page) -> Path:
    return cache_dir(directory) / f"{page.day.isoformat()}-{_fingerprint(page)}.json"


def load_cached(directory: Path, page: Page) -> Record | None:
    path = _cache_path(directory, page)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["day"] = Date.fromisoformat(data["day"])
        return Record(**data)
    except (ValueError, TypeError, KeyError):
        return None


def save_cached(directory: Path, page: Page, record: Record) -> Path:
    target = cache_dir(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = _cache_path(directory, page)
    data = asdict(record)
    data["day"] = record.day.isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- the whole journal -------------------------------------------------------


def dated_pages(directory: Path) -> list[Page]:
    """Every written day, oldest first."""
    pages: list[Page] = []
    for path in list_pages(directory):
        try:
            Date.fromisoformat(path.stem)
        except ValueError:
            continue
        page = load(path)
        if writing_of(page).strip():
            pages.append(page)
    return pages


def year_records(
    directory: Path,
    engine: ExtractorLike | None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Record]:
    """Records for every written day, oldest first, extracted once and cached.

    With `engine=None` only cached records are returned -- enough to draw the
    page instantly while a background pass fills in anything new.
    """
    pages = dated_pages(directory)
    records: list[Record] = []
    for index, page in enumerate(pages):
        record = load_cached(directory, page)
        if record is None and engine is not None:
            record = extract(engine, page)
            if record is not None:
                save_cached(directory, page, record)
        if record is not None:
            # Unanswered questions are structural and cheap: always fresh.
            record.unanswered = unanswered_questions(page)
            records.append(record)
        if on_progress:
            on_progress(index + 1, len(pages))
    return records
