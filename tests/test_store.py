from datetime import date, time
from pathlib import Path

from journal.store import (
    QUESTION,
    WRITING,
    Block,
    Entry,
    Page,
    append_capture,
    entries,
    list_pages,
    load,
    open_day,
    parse,
    path_for,
    render,
    save,
)


def make_page():
    return Page(
        day=date(2026, 9, 3),
        model="Qwen_Qwen3-4B-Q4_K_M",
        prompt_version="v3-buried",
        blocks=[
            Block(WRITING, "Long stretch of writing.\n\nA second paragraph."),
            Block(QUESTION, "You mentioned the review twice. What happened?"),
            Block(WRITING, "Well, it went badly."),
        ],
    )


def test_render_then_parse_round_trips():
    original = make_page()
    assert parse(render(original)) == original


def test_questions_render_as_blockquotes():
    text = render(make_page())
    assert "> You mentioned the review twice. What happened?" in text
    assert "date: 2026-09-03" in text


def test_your_own_writing_is_not_quoted():
    text = render(make_page())
    assert "\nLong stretch of writing." in text
    assert "> Long stretch" not in text


def test_paragraph_breaks_inside_writing_survive():
    page = parse(render(make_page()))
    assert page.blocks[0].text == "Long stretch of writing.\n\nA second paragraph."


def test_consecutive_writing_lines_stay_one_block():
    page = parse("---\ndate: 2026-09-03\n---\n\nline one\nline two\n")
    assert len(page.blocks) == 1
    assert page.blocks[0].text == "line one\nline two"


def test_multiline_question_is_one_block():
    page = parse("---\ndate: 2026-09-03\n---\n\n> part one\n> part two\n")
    assert page.blocks == [Block(QUESTION, "part one\npart two")]


def test_word_count_ignores_questions():
    page = Page(
        day=date(2026, 1, 1),
        model="m",
        prompt_version="v1",
        blocks=[
            Block(WRITING, "one two three"),
            Block(QUESTION, "a question with many words in it here now"),
        ],
    )
    assert page.words == 3


def test_parse_survives_missing_frontmatter():
    page = parse("just some text\n")
    assert page.model == "unknown"
    assert page.blocks == [Block(WRITING, "just some text")]


def test_parse_survives_garbage_date():
    page = parse("---\ndate: not-a-date\n---\n\nhi\n")
    assert page.blocks[0].text == "hi"


def test_round_trip_preserves_unicode():
    page = Page(
        day=date(2026, 1, 1),
        model="m",
        prompt_version="v1",
        blocks=[Block(WRITING, "café — naïve 🙂")],
    )
    assert parse(render(page)).blocks[0].text == "café — naïve 🙂"


def test_filename_is_the_date(tmp_path: Path):
    path = save(make_page(), tmp_path)
    assert path.name == "2026-09-03.md"
    assert load(path) == make_page()


def test_open_day_continues_an_existing_page(tmp_path: Path):
    save(make_page(), tmp_path)
    reopened = open_day(tmp_path, "m", "v1", day=date(2026, 9, 3))
    assert len(reopened.blocks) == 3
    assert reopened.model == "m"


def test_open_day_creates_a_blank_page_when_none_exists(tmp_path: Path):
    page = open_day(tmp_path, "m", "v1", day=date(2026, 9, 4))
    assert page.blocks == []
    assert page.day == date(2026, 9, 4)


def test_saving_twice_in_a_day_overwrites_one_file(tmp_path: Path):
    page = make_page()
    save(page, tmp_path)
    page.blocks.append(Block(WRITING, "later that evening"))
    save(page, tmp_path)
    assert len(list_pages(tmp_path)) == 1

    # Adjacent writing merges into one block on reload, and should: two
    # consecutive paragraphs of your own writing are one continuous stretch,
    # and Markdown has no way to record a boundary that isn't there.
    reloaded = load(path_for(tmp_path, page.day))
    assert [b.kind for b in reloaded.blocks] == [WRITING, QUESTION, WRITING]
    assert reloaded.blocks[-1].text == "Well, it went badly.\n\nlater that evening"


def test_list_pages_tolerates_missing_dir(tmp_path: Path):
    assert list_pages(tmp_path / "nope") == []


def test_capture_writes_a_prefixed_line(tmp_path):
    page = append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    assert page.blocks == [Block(WRITING, "[09:14] call the bank")]
    assert "[09:14] call the bank" in path_for(tmp_path, date(2026, 9, 4)).read_text(encoding="utf-8")


def test_two_captures_share_one_block_but_stay_separate_entries(tmp_path):
    append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    page = append_capture(tmp_path, "annoyed at standup", at=time(11, 2), day=date(2026, 9, 4))
    assert len(page.blocks) == 1
    assert entries(page) == [
        Entry(time(9, 14), "call the bank"),
        Entry(time(11, 2), "annoyed at standup"),
    ]


def test_capture_survives_a_save_and_reload(tmp_path):
    append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    reloaded = load(path_for(tmp_path, date(2026, 9, 4)))
    assert entries(reloaded) == [Entry(time(9, 14), "call the bank")]


def test_a_multi_line_capture_stays_one_entry(tmp_path):
    page = append_capture(
        tmp_path, "annoyed at standup\nagain", at=time(11, 2), day=date(2026, 9, 4)
    )
    assert page.blocks[0].text == "[11:02] annoyed at standup\n        again"
    assert entries(page) == [Entry(time(11, 2), "annoyed at standup\nagain")]


def test_a_capture_after_a_question_starts_a_new_block(tmp_path):
    append_capture(tmp_path, "first", at=time(9, 0), day=date(2026, 9, 4))
    page = load(path_for(tmp_path, date(2026, 9, 4)))
    page.blocks.append(Block(QUESTION, "What happened?"))
    save(page, tmp_path)
    page = append_capture(tmp_path, "second", at=time(10, 0), day=date(2026, 9, 4))
    assert [b.kind for b in page.blocks] == [WRITING, QUESTION, WRITING]


def test_entries_reads_a_page_written_before_prefixes_existed():
    page = Page(day=date(2026, 9, 3), model="m", prompt_version="p")
    page.blocks = [Block(WRITING, "Long stretch of writing.")]
    assert entries(page) == [Entry(None, "Long stretch of writing.")]


def test_entries_ignores_questions():
    page = Page(day=date(2026, 9, 3), model="m", prompt_version="p")
    page.blocks = [Block(QUESTION, "What happened?")]
    assert entries(page) == []


# --- standing notes --------------------------------------------------------

from journal.store import (  # noqa: E402
    Note,
    delete_note,
    list_notes,
    load_note,
    parse_note,
    recent_pages,
    render_note,
    save_note,
    search,
    slugify,
)


def test_slugify_handles_punctuation_and_spacing():
    assert slugify("Core Values!") == "core-values"
    assert slugify("  My   Goal  ") == "my-goal"
    assert slugify("???") == "note"


def test_note_round_trips():
    note = Note("values", "Core values", "Curiosity.\n\nHonesty.")
    assert parse_note("values", render_note(note)) == note


def test_note_without_frontmatter_gets_a_title_from_its_slug():
    assert parse_note("core-values", "just text").title == "Core Values"


def test_notes_save_load_list_delete(tmp_path: Path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    save_note(tmp_path, Note("goal", "Goal", "Ship the thing."))
    assert [n.slug for n in list_notes(tmp_path)] == ["goal", "values"]
    assert load_note(tmp_path, "values").text == "Curiosity."
    delete_note(tmp_path, "goal")
    assert [n.slug for n in list_notes(tmp_path)] == ["values"]


def test_notes_live_beside_pages_not_among_them(tmp_path: Path):
    """A note must never be mistaken for a day, or it corrupts the timeline."""
    save_page = make_page()
    save(save_page, tmp_path)
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    assert [p.name for p in list_pages(tmp_path)] == ["2026-09-03.md"]
    assert len(recent_pages(tmp_path)) == 1


def test_recent_pages_is_newest_first(tmp_path: Path):
    for d in (date(2026, 9, 1), date(2026, 9, 3), date(2026, 9, 2)):
        save(Page(day=d, model="m", prompt_version="v1",
                  blocks=[Block(WRITING, f"day {d.day}")]), tmp_path)
    assert [p.day.day for p in recent_pages(tmp_path)] == [3, 2, 1]


# --- search ----------------------------------------------------------------


def test_search_finds_pages_and_notes(tmp_path: Path):
    save(Page(day=date(2026, 9, 3), model="m", prompt_version="v1",
              blocks=[Block(WRITING, "The deadline slipped again.")]), tmp_path)
    save_note(tmp_path, Note("values", "Core values", "Honesty about deadlines."))

    hits = search(tmp_path, "deadline")
    assert {h.kind for h in hits} == {"page", "note"}
    assert len(hits) == 2


def test_search_is_case_insensitive_and_snippets_around_the_match(tmp_path: Path):
    save(Page(day=date(2026, 9, 3), model="m", prompt_version="v1",
              blocks=[Block(WRITING, "x" * 200 + " NEEDLE " + "y" * 200)]), tmp_path)
    hit = search(tmp_path, "needle")[0]
    assert "NEEDLE" in hit.snippet
    assert hit.snippet.startswith("…")


def test_search_ignores_questions_free_empty_query(tmp_path: Path):
    save(Page(day=date(2026, 9, 3), model="m", prompt_version="v1",
              blocks=[Block(WRITING, "hello")]), tmp_path)
    assert search(tmp_path, "   ") == []


def test_search_returns_nothing_for_a_miss(tmp_path: Path):
    save(make_page(), tmp_path)
    assert search(tmp_path, "zzzzzz") == []


def test_seed_notes_creates_starters_once(tmp_path: Path):
    from journal.store import seed_notes

    assert seed_notes(tmp_path) is True
    slugs = [n.slug for n in list_notes(tmp_path)]
    assert slugs == ["core-values", "goal"]
    assert "matter most" in load_note(tmp_path, "core-values").text

    # Never a second time, and never over your edits.
    edited = load_note(tmp_path, "goal")
    edited.text = "mine now"
    save_note(tmp_path, edited)
    assert seed_notes(tmp_path) is False
    assert load_note(tmp_path, "goal").text == "mine now"
