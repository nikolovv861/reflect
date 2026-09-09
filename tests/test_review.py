"""A year review in one sitting: the script is a practice file, a session is an
ordinary page, and the topic flow is a deterministic rule -- the model only
ever writes the follow-up."""
from __future__ import annotations

import json
from datetime import date

from journal.review import (
    MAX_FOLLOWUPS,
    PRACTICE,
    SUFFICIENT_WORDS,
    Turn,
    followup_page,
    needs_followup,
    next_index,
    progress_label,
    questions,
    review_records,
    turns,
    unanswered,
)
from journal.store import QUESTION, WRITING, Block, Page

DAY = date(2026, 9, 5)


def page(*blocks):
    return Page(day=DAY, model="stub", prompt_version="v6-direct", practice=PRACTICE,
                blocks=list(blocks))


def test_the_script_is_fourteen_real_questions_from_the_practice_file():
    qs = questions()
    assert len(qs) == 14
    assert all(q.endswith("?") for q in qs)
    assert "love" in qs[1].lower()
    assert "where do you stand" in qs[-1].lower()


def test_every_question_has_a_label_and_a_meaning():
    from journal.review import meanings

    ms = meanings()
    assert len(ms) == len(questions())
    labels = [label for label, _ in ms]
    assert labels[1] == "Love" and labels[-1] == "Where you stand"
    assert all(why for _, why in ms)  # never a blank line under a question


def test_turns_split_a_session_into_question_answer_and_followups():
    qs = questions()
    p = page(
        Block(QUESTION, qs[0]), Block(WRITING, "Mostly work, honestly."),
        Block(QUESTION, "Which part of work took the most days?"),   # a follow-up
        Block(WRITING, "The export pipeline. Months of it."),
        Block(QUESTION, qs[1]), Block(WRITING, "Elena. Quiet evenings."),
    )
    t = turns(p, qs)
    assert [x.index for x in t] == [0, 1]
    assert t[0].followups == ["Which part of work took the most days?"]
    assert "Months of it" in t[0].answer and t[0].answer.startswith("Mostly work")
    assert t[1].answer == "Elena. Quiet evenings."
    assert next_index(p, qs) == 2
    assert next_index(page(), qs) == 0


def test_turns_survive_two_questions_merged_into_one_block_and_rewrapping():
    qs = questions()
    # A skipped question against the next one, merged; and wrapped differently.
    merged = qs[1] + "\n" + " ".join(qs[2].split())
    p = page(
        Block(QUESTION, qs[0]), Block(WRITING, "Mostly work."),
        Block(QUESTION, merged), Block(WRITING, "Elena."),
    )
    t = turns(p, qs)
    assert [x.index for x in t] == [0, 1, 2]
    assert t[1].answer == "" and t[2].answer == "Elena."
    assert next_index(p, qs) == 3


def test_a_thin_answer_needs_a_followup_until_the_budget_is_spent():
    thin = Turn(0, "Q?", answer="Mostly work.")
    assert not thin.sufficient and needs_followup(thin)
    full = Turn(0, "Q?", answer="word " * SUFFICIENT_WORDS)
    assert full.sufficient and not needs_followup(full)
    spent = Turn(0, "Q?", answer="Mostly work.", followups=["a?"] * MAX_FOLLOWUPS)
    assert spent.exhausted and not needs_followup(spent)
    empty = Turn(0, "Q?", answer="")
    assert not needs_followup(empty)  # nothing to elaborate on; skip or write


def test_the_closing_one_sentence_question_never_gets_a_followup():
    qs = questions()
    p = page(Block(QUESTION, qs[-1]),
             Block(WRITING, "Waiting for permission, and I'm the one who gives it."))
    last = turns(p, qs)[-1]
    assert last.brief and last.sufficient and not needs_followup(last)
    # But an empty closing answer is still empty: write, or skip.
    assert not Turn(len(qs) - 1, qs[-1], brief=True).sufficient


def test_progress_is_a_position_and_a_time_never_a_score():
    assert progress_label(4, 14) == "5 OF 14 · ~40 MIN LEFT"
    assert progress_label(13, 14) == "14 OF 14 · ~4 MIN LEFT"
    assert "%" not in progress_label(0, 14)


def test_followup_page_shows_the_model_only_this_topic():
    t = Turn(3, "What did work ask of you?", answer="Too much.", followups=["Such as?"])
    p = followup_page(t, DAY, "m", "v6-direct")
    assert [b.kind for b in p.blocks] == [QUESTION, WRITING, QUESTION]
    assert p.practice == PRACTICE
    assert p.blocks[0].text == "What did work ask of you?"


class StubExtractor:
    def __init__(self):
        self.calls = 0

    def extract_json(self, instructions, content, schema):
        self.calls += 1
        assert "year review" in instructions
        assert "QUESTION:" in content
        return json.dumps({"people": ["Elena"], "places": [], "themes": ["relationships"],
                           "energy": 1, "unresolved": "", "key_phrase": "quiet evenings"})


def test_review_records_one_per_answered_question_with_topic_and_skips_unanswered():
    qs = questions()
    p = page(
        Block(QUESTION, qs[0]), Block(WRITING, "Mostly work."),
        Block(QUESTION, qs[1]),                      # skipped: no writing
        Block(QUESTION, qs[2]), Block(WRITING, "Elena, quiet evenings."),
    )
    stub = StubExtractor()
    recs = review_records(stub, p, qs)
    assert stub.calls == 2
    assert [r.topic for r in recs] == [qs[0], qs[2]]
    assert recs[0].people == ["Elena"] and recs[0].day == DAY
    assert unanswered(p, qs) == [qs[1]]
