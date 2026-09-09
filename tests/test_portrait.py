"""The portrait's plumbing, with the model stubbed: the transcript the model
reads, the rule that a section reads their answers back in its OWN words (and is
asked again if it copies a stretch of them verbatim), and the cache that makes a
finished session instant."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from journal.portrait import (
    SECTIONS,
    Portrait,
    Section,
    load_cached_portrait,
    portrait_for,
    save_cached_portrait,
    transcript,
    write_portrait,
)
from journal.review import PRACTICE, questions
from journal.store import QUESTION, WRITING, Block, Page

DAY = date(2026, 9, 5)


def session():
    qs = questions()
    blocks = []
    for i, q in enumerate(qs):
        blocks.append(Block(QUESTION, q))
        if i != 5:
            blocks.append(Block(WRITING, f"Answer {i}: mostly work, honestly, and the deadline nobody owns."))
    return Page(day=DAY, model="stub", prompt_version="v6-direct", practice=PRACTICE, blocks=blocks)


class StubWriter:
    """With copy_first_time, the first reply lifts a long verbatim run from the
    answers (sent back); otherwise it reads them back in its own words and is
    accepted. The retry is always interpretive. Counts calls per section."""

    # An 8-word run straight out of session()'s answers -- the paraphrase gate.
    COPIED = "mostly work, honestly, and the deadline nobody owns"
    READ = "You keep score by what slips, never by what ships."

    def __init__(self, copy_first_time=False):
        self.calls = 0
        self.copy_first_time = copy_first_time

    def extract_json(self, instructions, content, schema):
        self.calls += 1
        assert "Their fourteen answers" in content
        props = schema["properties"]
        if "areas" in props:  # the four measures -- distinct, specific, non-generic
            from journal.portrait import AREAS
            canned = [
                ("Your friends stayed close through a loud year.", "Ring the friend you keep meaning to."),
                ("The marriage steadied after a rough spring.", "Book the weekend you both keep postponing."),
                ("Work shipped and it clearly mattered to you.", "Hand the next project off before it eats you."),
                ("You slept better once the pool reopened.", "Keep the Thursday swim on the calendar."),
            ]
            return json.dumps({"areas": [
                {"area": label, "score": 60 + 3 * i, "direction": "steady",
                 "working": canned[i][0], "next": canned[i][1]}
                for i, (label, _d, _f) in enumerate(AREAS)
            ]})
        copying = self.copy_first_time and "was sent back because" not in instructions
        body = self.COPIED if copying else self.READ
        if "items" in props:
            return json.dumps({"items": [{"name": "Shipping quietly", "evidence": body}] * 3})
        out = {"text": body}
        if "name" in props:
            out["name"] = "The quiet shipper"
        if "keep" in props:
            out["keep"] = "I am someone."
        return json.dumps(out)


def test_transcript_numbers_answers_and_marks_skips():
    text = transcript(session(), questions())
    assert text.startswith("Their fourteen answers:")
    assert "6. " in text and "(skipped)" in text
    assert "14. " in text


def test_an_interpretive_section_is_accepted_in_one_draft():
    stub = StubWriter(copy_first_time=False)
    p = write_portrait(stub, session(), questions())
    assert len(p.sections) == len(SECTIONS)
    # No verbatim copying, no drift: every section is accepted on the first draft,
    # plus one call for the four measures.
    assert stub.calls == len(SECTIONS) + 1
    assert p.get("name").name == "The quiet shipper"
    assert p.get("standing").keep == "I am someone."


def test_copying_a_verbatim_run_triggers_one_retry():
    stub = StubWriter(copy_first_time=True)
    p = write_portrait(stub, session(), questions())
    assert len(p.sections) == len(SECTIONS)
    # Each section lifts a long run first, is sent back once, then accepted; the
    # four-measures call is clean in one draft.
    assert stub.calls == 2 * len(SECTIONS) + 1
    assert all(StubWriter.COPIED not in (s.text or s.items[0]["evidence"]) for s in p.sections)


def test_the_four_measures_are_scored_labelled_and_bounded():
    from journal.portrait import AREAS, write_areas

    stub = StubWriter()
    areas = write_areas(stub, "Their fourteen answers:\n...", "some answers")
    assert [a["area"] for a in areas] == [label for label, _d, _f in AREAS]
    assert all(1 <= a["score"] <= 100 for a in areas)
    assert all(a["direction"] in ("rising", "steady", "falling") for a in areas)
    assert all(a["working"] and a["next"] for a in areas)


def test_the_portrait_carries_the_four_measures():
    p = write_portrait(StubWriter(), session(), questions())
    assert len(p.areas) == 4
    assert p.areas[0]["area"] == "Social"


def test_deep_reads_every_answered_question_and_writes_a_letter():
    from journal.portrait import write_deep

    p = write_portrait(StubWriter(), session(), questions())
    deep = write_deep(StubWriter(), session(), questions(), p)
    # session() skips question 6 (index 5); every OTHER question gets a reading.
    assert len(deep.answers) == len(questions()) - 1
    assert 5 not in [a["index"] for a in deep.answers]
    assert all(a["reading"] and a["question"] for a in deep.answers)
    assert deep.letter


def test_deep_is_cached_beside_the_portrait(tmp_path: Path):
    from journal.portrait import deep_for

    stub = StubWriter()
    first = deep_for(tmp_path, stub, session(), questions())
    calls = stub.calls
    assert first is not None and first.letter
    again = deep_for(tmp_path, None, session(), questions())  # no engine: cache only
    assert again is not None and len(again.answers) == len(first.answers)
    assert deep_for(tmp_path, stub, session(), questions()) is not None
    assert stub.calls == calls  # never re-written


def test_answer_number_references_are_stripped_from_prose():
    from journal.portrait import _tidy

    assert _tidy("You said 'x' in answer 4, and 'y' in answers 4 and 10.") == "You said 'x', and 'y'."
    assert _tidy("Plain text stays.") == "Plain text stays."


def test_portrait_is_cached_by_transcript(tmp_path: Path):
    stub = StubWriter(copy_first_time=True)
    first = portrait_for(tmp_path, stub, session(), questions())
    calls_after_first = stub.calls
    assert first is not None and calls_after_first >= len(SECTIONS)
    again = portrait_for(tmp_path, None, session(), questions())  # no engine: cache only
    assert again is not None and again.get("name").name == "The quiet shipper"
    assert portrait_for(tmp_path, stub, session(), questions()) is not None
    assert stub.calls == calls_after_first  # never asked again


def test_cache_round_trip_keeps_items(tmp_path: Path):
    p = Portrait(sections=[Section("strengths", "What you are actually good at",
                                   items=[{"name": "a", "evidence": "b"}])])
    save_cached_portrait(tmp_path, session(), questions(), p)
    back = load_cached_portrait(tmp_path, session(), questions())
    assert back.get("strengths").items == [{"name": "a", "evidence": "b"}]
