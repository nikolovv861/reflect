"""The Year page is a mirror, not a report card.

These tests pin the shape of the page: people are ranked by how often they
appear, threads are told in the writer's own words, 'circling back' needs a
thread that spans months, energy is a shape with no numbers, and unanswered
questions surface. And the renderer must never print a percentage or a streak.
"""
from __future__ import annotations

import re
from datetime import date

from journal.year import Record
from journal.yearpage import aggregate, render_html, render_markdown, sparkline


def rec(iso, people=(), places=(), themes=(), energy=0, phrase="", unanswered=(), unresolved=""):
    return Record(
        day=date.fromisoformat(iso),
        words=40,
        people=list(people),
        places=list(places),
        themes=list(themes),
        energy=energy,
        key_phrase=phrase,
        unresolved=unresolved,
        unanswered=list(unanswered),
    )


def a_year():
    return [
        rec("2026-01-10", ["Maria"], ["the office"], ["work"], -1, "the deadline slipped"),
        rec("2026-02-14", ["Maria", "Dad"], ["Plovdiv"], ["work", "family"], -2, "nobody wants to own it"),
        rec("2026-03-03", ["Elena"], ["the river"], ["health"], 0, "the first two were awful"),
        rec("2026-04-20", ["Maria"], ["the office"], ["work", "avoidance"], -1, "someone will notice eventually",
            unanswered=["What would owning it cost you?"]),
        rec("2026-06-08", ["Dad"], ["Plovdiv"], ["family"], 1, "we fixed the fence", unresolved="Dad's knee"),
        rec("2026-08-01", ["Maria"], [], ["work"], 2, "shipped the migration"),
    ]


def test_people_are_ranked_by_appearances_with_their_span():
    s = aggregate(a_year())
    assert s.people[0].name == "Maria"
    assert s.people[0].count == 4
    assert (s.people[0].first, s.people[0].last) == (date(2026, 1, 10), date(2026, 8, 1))
    assert s.days == 6 and s.first == date(2026, 1, 10) and s.last == date(2026, 8, 1)


def test_circling_back_needs_a_thread_that_spans_months():
    s = aggregate(a_year())
    assert [t.theme for t in s.circling] == ["work"]  # 4 days across 4 months
    assert all(t.theme != "health" for t in s.circling)  # one day is not a thread
    # Told in the writer's own words, spread across the span.
    quotes = [q for _, q in s.circling[0].quotes]
    assert quotes[0] == "the deadline slipped" and quotes[-1] == "shipped the migration"


def test_unanswered_and_left_open_surface():
    s = aggregate(a_year())
    assert s.unanswered == [(date(2026, 4, 20), "What would owning it cost you?")]
    assert s.unresolved == [(date(2026, 6, 8), "Dad's knee")]


def test_energy_is_a_shape_not_a_number():
    assert sparkline([-2, 0, 2]) == "▁▄▇"
    html = render_html(aggregate(a_year()))
    assert "a shape, not a score" in html
    # No percentages, no streaks, no 'better'/'worse' anywhere on the page.
    assert "%" not in html
    assert not re.search(r"\bstreak\b|\bbetter than\b|\bworse\b", html, re.IGNORECASE)


def test_render_html_uses_the_writers_words_and_is_qt_friendly():
    html = render_html(aggregate(a_year()))
    assert "You wrote on 6 days" in html
    assert "nobody wants to own it" in html
    # Section headings are uppercased for Qt rich text (no text-transform).
    assert "QUESTIONS YOU NEVER ANSWERED" in html
    assert "What would owning it cost you?" in html
    # Only simple tags Qt rich text understands -- no divs with flex, no svg.
    assert "<svg" not in html and "flex" not in html


def test_empty_year_renders_gently():
    html = render_html(aggregate([]))
    assert "Nothing written yet" in html
    assert render_markdown(aggregate([])).startswith("# Your year")


def test_markdown_export_mirrors_the_page():
    md = render_markdown(aggregate(a_year()))
    assert md.startswith("# Your year")
    assert "## People" in md and "Maria" in md
    assert "## Questions you never answered" in md
