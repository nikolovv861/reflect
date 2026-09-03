from datetime import date
from pathlib import Path

from journal.store import (
    QUESTION,
    WRITING,
    Block,
    Page,
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
