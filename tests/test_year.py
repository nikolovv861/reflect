"""The Year page's foundation: one structured record per written day.

The model is stubbed. What matters here is the plumbing a demo depends on:
JSON is parsed tolerantly, themes stay inside the closed list, the cache means
a year is extracted once, and the app's unanswered questions are found
structurally (no model needed for that at all).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from journal.store import QUESTION, WRITING, Block, Page, save
from journal.year import (
    THEMES,
    Record,
    cache_dir,
    extract,
    parse_record,
    unanswered_questions,
    year_records,
)


class StubExtractor:
    """Returns canned JSON and counts how often the model was consulted."""

    def __init__(self, payload: dict | str):
        self.payload = payload
        self.calls = 0

    def extract_json(self, instructions, content, schema):
        self.calls += 1
        assert "JSON" in instructions
        assert schema["type"] == "object"
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def page(day, *blocks):
    return Page(day=day, model="stub", prompt_version="v6-direct", blocks=list(blocks))


GOOD = {
    "people": ["Maria", "maria", " my manager "],
    "places": ["the office"],
    "themes": ["work", "work", "not-a-theme", "avoidance"],
    "energy": -7,
    "unresolved": "the deadline nobody owns",
    "key_phrase": "nobody wants to own it",
}


def test_parse_record_dedupes_clamps_and_keeps_only_known_themes():
    rec = parse_record(json.dumps(GOOD), date(2026, 3, 4), 40)
    assert rec.people == ["Maria", "my manager"]
    assert rec.themes == ["work", "avoidance"]
    assert all(t in THEMES for t in rec.themes)
    assert rec.energy == -2  # clamped into [-2, 2]
    assert rec.key_phrase == "nobody wants to own it"


def test_parse_record_drops_non_people_and_keeps_a_key_phrase_short():
    payload = dict(GOOD)
    payload["people"] = ["Maria", "other people", "my phone", "Dad"]
    payload["key_phrase"] = (
        "Mostly work, honestly. The export pipeline ate the spring, then the "
        "migration ate the summer. Evenings went to my phone more than I'd like "
        "to admit, and weekends went to Plovdiv or the river."
    )
    rec = parse_record(json.dumps(payload), date(2026, 3, 4), 40)
    assert rec.people == ["Maria", "Dad"]
    assert rec.key_phrase == "Mostly work, honestly."


def test_parse_record_survives_broken_json():
    assert parse_record("not json at all", date(2026, 3, 4), 10) is None
    assert parse_record("[1, 2, 3]", date(2026, 3, 4), 10) is None


def test_unanswered_questions_are_found_structurally():
    p = page(
        date(2026, 3, 4),
        Block(WRITING, "The deadline came up again."),
        Block(QUESTION, "Why do you think it got skipped over?"),
        Block(WRITING, "Because nobody wants to own it."),
        Block(QUESTION, "What would owning it cost you?"),
    )
    assert unanswered_questions(p) == ["What would owning it cost you?"]


def test_extract_skips_days_with_no_writing():
    stub = StubExtractor(GOOD)
    only_question = page(date(2026, 3, 4), Block(QUESTION, "Anything?"))
    assert extract(stub, only_question) is None
    assert stub.calls == 0


def test_year_records_extracts_once_then_serves_from_cache(tmp_path: Path):
    save(page(date(2026, 3, 4), Block(WRITING, "Maria and the deadline again.")), tmp_path)
    save(page(date(2026, 3, 5), Block(WRITING, "A quiet day at the office.")), tmp_path)
    stub = StubExtractor(GOOD)

    first = year_records(tmp_path, stub)
    assert [r.day.day for r in first] == [4, 5]  # oldest first
    assert stub.calls == 2
    assert cache_dir(tmp_path).exists()

    # Second pass: nothing new was written, so the model is never consulted.
    second = year_records(tmp_path, stub)
    assert stub.calls == 2
    assert [r.people for r in second] == [["Maria", "my manager"]] * 2

    # And with no engine at all, cached records still come back for the page.
    assert len(year_records(tmp_path, None)) == 2


def test_year_records_re_extracts_when_the_writing_changes(tmp_path: Path):
    save(page(date(2026, 3, 4), Block(WRITING, "First version.")), tmp_path)
    stub = StubExtractor(GOOD)
    year_records(tmp_path, stub)
    save(page(date(2026, 3, 4), Block(WRITING, "Rewritten, so a new fingerprint.")), tmp_path)
    year_records(tmp_path, stub)
    assert stub.calls == 2


def test_record_is_a_plain_dataclass_the_page_can_render():
    rec = Record(day=date(2026, 3, 4), words=12, people=["Maria"], energy=1)
    assert rec.themes == [] and rec.unanswered == []
