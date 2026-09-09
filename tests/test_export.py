from datetime import date
from pathlib import Path

from journal.export import (
    export_all,
    export_month,
    pages_in_month,
    write_export,
)
from journal.store import QUESTION, WRITING, Block, Page, save


def make_pages(directory: Path) -> None:
    """Two days in 2026-09 and one in 2026-08, each with a question."""
    save(
        Page(
            day=date(2026, 8, 14),
            model="m",
            prompt_version="v1",
            practice="morning-pages",
            blocks=[
                Block(WRITING, "August felt slow and warm."),
                Block(QUESTION, "What slowed you down?"),
                Block(WRITING, "Nothing urgent, and that was the gift."),
            ],
        ),
        directory,
    )
    save(
        Page(
            day=date(2026, 9, 3),
            model="m",
            prompt_version="v1",
            blocks=[
                Block(WRITING, "The review went badly."),
                Block(QUESTION, "You mentioned it twice. What happened?"),
            ],
        ),
        directory,
    )
    save(
        Page(
            day=date(2026, 9, 20),
            model="m",
            prompt_version="v1",
            blocks=[
                Block(WRITING, "Autumn arriving early this year."),
                Block(QUESTION, "What are you letting go of?"),
            ],
        ),
        directory,
    )


def test_pages_in_month_returns_right_pages_chronological(tmp_path: Path):
    make_pages(tmp_path)
    september = pages_in_month(tmp_path, 2026, 9)
    assert [p.day for p in september] == [date(2026, 9, 3), date(2026, 9, 20)]

    august = pages_in_month(tmp_path, 2026, 8)
    assert [p.day for p in august] == [date(2026, 8, 14)]


def test_pages_in_month_ignores_non_date_files(tmp_path: Path):
    make_pages(tmp_path)
    (tmp_path / "notaday.md").write_text("stray file\n", encoding="utf-8")
    assert [p.day for p in pages_in_month(tmp_path, 2026, 9)] == [
        date(2026, 9, 3),
        date(2026, 9, 20),
    ]


def test_export_month_has_title_dates_writing_and_blockquotes(tmp_path: Path):
    make_pages(tmp_path)
    text = export_month(tmp_path, 2026, 9)

    assert "# Journal -- September 2026" in text
    # Each day's date appears as a heading.
    assert "Thursday, 03 September 2026" in text
    assert "Sunday, 20 September 2026" in text
    # The writing itself is present, unquoted.
    assert "The review went badly." in text
    # Questions render as blockquotes.
    assert "> You mentioned it twice. What happened?" in text
    # Chronological: the 3rd comes before the 20th.
    assert text.index("03 September") < text.index("20 September")


def test_export_month_shows_practice_when_not_free(tmp_path: Path):
    make_pages(tmp_path)
    august = export_month(tmp_path, 2026, 8)
    assert "morning-pages" in august
    september = export_month(tmp_path, 2026, 9)
    # "free" practice is not advertised.
    assert "free" not in september


def test_export_month_with_no_entries_says_so_without_raising(tmp_path: Path):
    make_pages(tmp_path)
    text = export_month(tmp_path, 2026, 1)
    assert "No entries" in text
    assert "# Journal -- January 2026" in text


def test_export_all_includes_both_months(tmp_path: Path):
    make_pages(tmp_path)
    text = export_all(tmp_path)
    assert text.strip()
    assert "August 2026" in text
    assert "September 2026" in text
    # Content from both months.
    assert "August felt slow and warm." in text
    assert "Autumn arriving early this year." in text
    # Oldest first overall.
    assert text.index("August 2026") < text.index("September 2026")


def test_export_all_empty_journal_does_not_raise(tmp_path: Path):
    text = export_all(tmp_path)
    assert "No entries" in text


def test_write_export_creates_file_under_exports_and_round_trips(tmp_path: Path):
    text = export_month(tmp_path, 2026, 9)
    path = write_export(tmp_path, text, "september.md")

    assert path == tmp_path / "exports" / "september.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == text
