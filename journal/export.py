"""Bundle a journal into a single Markdown document for archiving or printing.

This is not a report. It makes no scores, no streaks, no judgements -- it only
gathers the days you already wrote into one readable, self-contained file you
could print, email to your future self, or keep in a drawer. Everything is
plain Markdown and pure stdlib, in keeping with the promise that your journal
outlives this app.

The unit remains the DAY. Pages live one-per-date as ``YYYY-MM-DD.md`` in a
directory; here we read them back, group them by month, and lay them out oldest
first so the output is deterministic and the story reads forwards.
"""
from __future__ import annotations

from datetime import date as Date
from pathlib import Path

from journal.store import QUESTION, Page, list_pages, load

# Days within a bundle are separated by a Markdown horizontal rule.
_DAY_SEPARATOR = "\n---\n"


def _page_date(path: Path) -> Date | None:
    """The date a page file stands for, or None if the name is not a date."""
    try:
        return Date.fromisoformat(path.stem)
    except ValueError:
        return None


def _all_pages(directory: Path) -> list[Page]:
    """Every dated page, oldest first. Non-date files are ignored."""
    pages: list[Page] = []
    for path in list_pages(directory):
        if _page_date(path) is None:
            continue
        pages.append(load(path))
    return pages


def pages_in_month(directory: Path, year: int, month: int) -> list[Page]:
    """All pages whose date falls in ``year``/``month``, oldest first.

    Files whose name is not an ISO date are skipped, so notes and stray files
    never leak into the timeline.
    """
    pages = [
        page
        for page in _all_pages(directory)
        if page.day.year == year and page.day.month == month
    ]
    pages.sort(key=lambda page: page.day)
    return pages


def _render_day(page: Page, level: int = 2) -> str:
    """One day as readable Markdown: a dated heading, then the day's content.

    ``level`` sets the heading depth so a day sits under a month heading when
    it needs to. Your own writing becomes ordinary paragraphs; questions become
    ``>`` blockquotes, the same convention the store uses on disk, so the bundle
    reads exactly like the files it came from.
    """
    heading = page.day.strftime("%A, %d %B %Y")
    lines = [f"{'#' * level} {heading}", ""]

    if page.practice and page.practice != "free":
        lines.append(f"*{page.practice}*")
        lines.append("")

    for block in page.blocks:
        if block.kind == QUESTION:
            for line in block.text.strip().splitlines():
                lines.append(f"> {line}")
        else:
            lines.extend(block.text.strip("\n").splitlines())
        lines.append("")

    # Light, factual metadata -- a count, never a verdict.
    words = page.words
    if words:
        measure = "word" if words == 1 else "words"
        lines.append(f"*{words} {measure} written.*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _month_title(year: int, month: int) -> str:
    return Date(year, month, 1).strftime("%B %Y")


def export_month(directory: Path, year: int, month: int) -> str:
    """A single Markdown string bundling every page in ``year``/``month``.

    Begins with a ``# Journal -- <Month Year>`` title, then one section per day
    written that month, oldest first, separated by horizontal rules. A month
    with no entries yields a short "No entries" document rather than raising.
    """
    title = _month_title(year, month)
    pages = pages_in_month(directory, year, month)

    if not pages:
        return f"# Journal -- {title}\n\nNo entries.\n"

    sections = [_render_day(page) for page in pages]
    body = _DAY_SEPARATOR.join(sections)
    return f"# Journal -- {title}\n\n{body}"


def export_all(directory: Path) -> str:
    """Every month present, grouped under month headings, oldest first overall.

    A single self-contained archive of the whole journal. Reuses
    ``export_month`` so a month reads the same whether exported alone or as
    part of the whole. An empty journal yields a short "No entries" document.
    """
    pages = _all_pages(directory)
    if not pages:
        return "# Journal\n\nNo entries.\n"

    # The distinct (year, month) pairs present, in chronological order.
    months: list[tuple[int, int]] = []
    for page in sorted(pages, key=lambda p: p.day):
        key = (page.day.year, page.day.month)
        if key not in months:
            months.append(key)

    parts = ["# Journal", ""]
    for year, month in months:
        parts.append(f"## {_month_title(year, month)}")
        parts.append("")
        # Days nest one level below the month heading.
        day_sections = [
            _render_day(page, level=3)
            for page in pages_in_month(directory, year, month)
        ]
        parts.append(_DAY_SEPARATOR.join(day_sections).rstrip())
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def write_export(directory: Path, text: str, name: str) -> Path:
    """Write ``text`` to ``directory/exports/name``, creating the dir.

    Exports live alongside the journal they came from, so an archive is never
    orphaned from its source. Returns the path written.
    """
    target = directory / "exports"
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_text(text, encoding="utf-8")
    return path
