"""Your year on one page: aggregate the records, render one readable page.

Everything here is plain Python over `year.Record`s -- no model call. The page
is a MIRROR, not a report card: no streaks, no percentages, no comparisons,
no grade. Energy is a faint textual arc with no numbers on it. Threads are
told through the writer's own quoted words rather than model prose.

The renderer emits the subset of HTML Qt's rich-text engine understands
(headings, paragraphs, spans with colour, simple tables), so it can be shown
in a QTextBrowser and also saved as a file.
"""
from __future__ import annotations

import calendar
import html
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta

from journal.year import Record

PAPER = "#f7f1e3"
INK = "#3a3226"
FAINT = "#b0a488"
ACCENT = "#8a7b4e"
QUOTE = "#6f6551"
CHIP = "#ece2cf"
ARC = "#d9cca8"

SPARK = "▁▂▃▄▅▆▇"


@dataclass
class Person:
    name: str
    count: int
    first: Date
    last: Date


@dataclass
class Thread:
    theme: str
    count: int
    months: int
    quotes: list[tuple[Date, str]] = field(default_factory=list)


@dataclass
class YearSummary:
    days: int = 0
    words: int = 0
    first: Date | None = None
    last: Date | None = None
    people: list[Person] = field(default_factory=list)
    places: list[tuple[str, int]] = field(default_factory=list)
    threads: list[Thread] = field(default_factory=list)
    circling: list[Thread] = field(default_factory=list)
    energy_weeks: list[tuple[Date, float]] = field(default_factory=list)
    unresolved: list[tuple[Date, str]] = field(default_factory=list)
    unanswered: list[tuple[Date, str]] = field(default_factory=list)
    in_your_words: list[tuple[Date, str]] = field(default_factory=list)
    # A review session: (question, the writer's key phrase), in question order.
    answers: list[tuple[str, str]] = field(default_factory=list)


# --- aggregation -----------------------------------------------------------


def _week_start(day: Date) -> Date:
    return day - timedelta(days=day.weekday())


def _spread(items: list, k: int) -> list:
    """k items spread across the list (first, middle, last...), order kept."""
    if len(items) <= k:
        return list(items)
    step = (len(items) - 1) / (k - 1)
    return [items[round(i * step)] for i in range(k)]


def aggregate(records: list[Record], top: int = 8) -> YearSummary:
    if not records:
        return YearSummary()
    records = sorted(records, key=lambda r: r.day)
    summary = YearSummary(
        days=len(records),
        words=sum(r.words for r in records),
        first=records[0].day,
        last=records[-1].day,
    )

    # People: who kept showing up, and the span of their appearances.
    seen: dict[str, list[Date]] = defaultdict(list)
    for r in records:
        for name in r.people:
            seen[name.strip().lower()].append(r.day)
    display: dict[str, str] = {}
    for r in records:
        for name in r.people:
            display.setdefault(name.strip().lower(), name.strip())
    people = [
        Person(display[k], len(days), min(days), max(days)) for k, days in seen.items()
    ]
    people.sort(key=lambda p: (-p.count, p.first))
    summary.people = people[:top]

    # Places. "By the river" and "the river" are one place.
    def place_key(place: str) -> str:
        key = " ".join(place.lower().split()).strip(".,;:")
        for lead in ("by the ", "at the ", "in the ", "by ", "at ", "in ", "to "):
            if key.startswith(lead):
                key = key[len(lead):]
                break
        return "the " + key if not key.startswith("the ") and " " not in key and key[:1].islower() else key

    place_counts: Counter[str] = Counter()
    place_display: dict[str, str] = {}
    for r in records:
        for place in r.places:
            key = place_key(place)
            place_counts[key] += 1
            place_display.setdefault(key, place.strip())
    summary.places = [(place_display[k], n) for k, n in place_counts.most_common(top)]

    # Threads: each theme, how many months it spans, told in the writer's words.
    by_theme: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        for theme in r.themes:
            by_theme[theme].append(r)
    threads: list[Thread] = []
    for theme, rs in by_theme.items():
        months = len({(r.day.year, r.day.month) for r in rs})
        quotes = [(r.day, r.key_phrase) for r in rs if r.key_phrase]
        threads.append(Thread(theme, len(rs), months, _spread(quotes, 3)))
    threads.sort(key=lambda t: (-t.count, t.theme))
    summary.threads = threads[:6]
    # "Circling back": the threads that ran across most of the year -- or, in
    # a one-sitting review (everything on a day or two), across many answers.
    distinct_days = len({r.day for r in records})
    if distinct_days <= 2:
        summary.circling = [t for t in threads if t.count >= 3][:3]
    else:
        summary.circling = [t for t in threads if t.months >= 4 and t.count >= 4][:3]

    summary.answers = [(r.topic, r.key_phrase) for r in records if r.topic and r.key_phrase]

    # Energy: a weekly mean, kept as a shape -- never a number on the page.
    # In a one-sitting review every answer gets its own step instead.
    if distinct_days <= 2:
        summary.energy_weeks = [(r.day, float(r.energy)) for r in records]
    else:
        weeks: dict[Date, list[int]] = defaultdict(list)
        for r in records:
            weeks[_week_start(r.day)].append(r.energy)
        summary.energy_weeks = [
            (w, sum(v) / len(v)) for w, v in sorted(weeks.items())
        ]

    summary.unresolved = [(r.day, r.unresolved) for r in records if r.unresolved][-6:]
    summary.unanswered = [(r.day, q) for r in records for q in r.unanswered]
    summary.in_your_words = _spread(
        [(r.day, r.key_phrase) for r in records if r.key_phrase], 8
    )
    return summary


# --- rendering -------------------------------------------------------------


def _month(day: Date) -> str:
    return calendar.month_name[day.month]


def _short(day: Date) -> str:
    return f"{day.day} {calendar.month_abbr[day.month]}"


def sparkline(values: list[float]) -> str:
    """-2..2 mapped onto seven block heights. A shape, not a scale."""
    out = []
    for v in values:
        level = int(round((max(-2.0, min(2.0, v)) + 2.0) / 4.0 * (len(SPARK) - 1)))
        out.append(SPARK[level])
    return "".join(out)


def _chip(text: str, note: str = "") -> str:
    inner = html.escape(text)
    if note:
        inner += f' <span style="color:{FAINT}">{html.escape(note)}</span>'
    return (
        f'<span style="background-color:{CHIP}; color:{INK};">&nbsp;{inner}&nbsp;</span>'
    )


def _quote(day: Date, text: str) -> str:
    return (
        f'<p style="margin-left:18px; color:{QUOTE};"><i>“{html.escape(text)}”</i>'
        f' <span style="color:{FAINT}; font-size:11px;">— {_short(day)}</span></p>'
    )


def _h2(text: str) -> str:
    return (
        f'<p style="margin-top:22px; color:{FAINT}; font-size:11px; letter-spacing:2px;">'
        f"{html.escape(text).upper()}</p>"
    )


def _paragraphs(text: str, colour: str = INK, size: int = 15) -> str:
    out = []
    for para in [p.strip() for p in text.split("\n") if p.strip()] or [text]:
        out.append(f'<p style="color:{colour}; font-size:{size}px; line-height:150%;">{html.escape(para)}</p>')
    return "\n".join(out)


_ARROW = {"rising": "↗", "falling": "↘", "steady": "→"}


def _meter(score: int) -> str:
    """A twenty-segment bar in the accent over the arc track -- a shape for the
    number, in the same spirit as the energy sparkline: read at a glance, no
    tick marks to grade against."""
    n = max(0, min(20, round(score / 5)))
    return (
        f'<span style="color:{ACCENT}; letter-spacing:1px;">{"▮" * n}</span>'
        f'<span style="color:{ARC}; letter-spacing:1px;">{"▮" * (20 - n)}</span>'
    )


def _area_block(area: dict) -> str:
    label = html.escape(str(area.get("area", "")))
    score = int(area.get("score", 0))
    arrow = _ARROW.get(area.get("direction", "steady"), "→")
    working = html.escape(str(area.get("working", "")))
    nxt = html.escape(str(area.get("next", "")))
    parts = [
        '<p style="margin:16px 0 0 0;">'
        f'<b style="font-size:16px; color:{INK};">{label}</b>'
        f'<span style="color:{ACCENT}; font-size:17px;">&nbsp;&nbsp;{score}</span>'
        f'<span style="color:{FAINT}; font-size:12px;">/100&nbsp;&nbsp;{arrow}</span></p>',
        f'<p style="margin:3px 0 0 0; font-size:13px;">{_meter(score)}</p>',
    ]
    if working:
        parts.append(f'<p style="color:{INK}; font-size:14px; margin:4px 0 0 0; line-height:145%;">{working}</p>')
    if nxt:
        parts.append(
            f'<p style="color:{QUOTE}; font-size:13px; margin:2px 0 0 0; line-height:145%;">'
            f'<b style="color:{ACCENT};">Next</b>&nbsp;&nbsp;{nxt}</p>'
        )
    return "\n".join(parts)


def render_areas(areas: list[dict]) -> str:
    if not areas:
        return ""
    parts = [
        _h2("How you're doing"),
        f'<p style="color:{FAINT}; font-size:12px; margin:0 0 2px 0;">'
        "A generous read, not a grade — where the year gave you life, and the one "
        "thing to tend next.</p>",
    ]
    parts += [_area_block(a) for a in areas]
    return "\n".join(parts)


def render_deep(deep) -> str:
    """The long form: a read of each answer, then the closing letter."""
    if deep is None or not (getattr(deep, "answers", None) or getattr(deep, "letter", "")):
        return ""
    parts: list[str] = []
    if deep.answers:
        parts.append(_h2("Your year, answer by answer"))
        for a in deep.answers:
            q = html.escape(str(a.get("question", "")))
            parts.append(
                f'<p style="margin:16px 0 0 0; color:{FAINT}; font-size:12px;">'
                f'{int(a.get("index", 0)) + 1}. {q}</p>'
            )
            parts.append(_paragraphs(str(a.get("reading", "")), size=14))
    if deep.letter:
        parts.append(_h2("A letter, at the end"))
        parts.append(_paragraphs(deep.letter, size=15))
    return "\n".join(parts)


def render_portrait(portrait, summary: YearSummary, title: str = "Where you stand",
                    deep=None) -> str:
    """The reading first, in full; the facts as a small appendix underneath."""
    parts: list[str] = [f'<div style="color:{INK}; font-family:Georgia;">']
    name = portrait.get("name")
    parts.append(f'<p style="color:{FAINT}; font-size:11px; letter-spacing:3px;">{html.escape(title).upper()}</p>')
    if name and name.name:
        parts.append(f'<h2 style="color:{ACCENT}; font-size:30px; font-weight:normal; margin:4px 0 6px 0;">{html.escape(name.name)}</h2>')
        if name.text:
            parts.append(f'<p style="color:{QUOTE}; font-size:14px;"><i>{html.escape(name.text)}</i></p>')
    parts.append(
        f'<p style="color:{FAINT}; font-size:11px;">Read from your own answers, on this machine. '
        "Nothing left it.</p>"
    )
    parts.append(render_areas(getattr(portrait, "areas", [])))
    for section in portrait.sections:
        if section.key == "name":
            continue
        parts.append(_h2(section.title))
        if section.name:
            parts.append(f'<p style="font-size:18px; margin-bottom:2px;"><b>{html.escape(section.name)}</b></p>')
        if section.items:
            for item in section.items:
                parts.append(
                    f'<p><b>{html.escape(item["name"])}</b>'
                    f'<br/><span style="color:{QUOTE};"><i>{html.escape(item["evidence"])}</i></span></p>'
                )
        if section.text:
            parts.append(_paragraphs(section.text))
        if section.keep:
            parts.append(
                f'<p style="margin:16px 0 0 18px; color:{ACCENT}; font-size:17px;">'
                f'<i>“{html.escape(section.keep)}”</i></p>'
                f'<p style="margin-left:18px; color:{FAINT}; font-size:11px;">the sentence to keep</p>'
            )

    parts.append(render_deep(deep))

    # The receipts: small, factual, underneath.
    if summary.days:
        parts.append(f'<p style="margin-top:34px; color:{FAINT}; font-size:11px; letter-spacing:2px;">THE FACTS YOU GAVE</p>')
        if summary.people:
            parts.append("<p>" + " ".join(_chip(p.name, f"×{p.count}") for p in summary.people[:8]) + "</p>")
        if summary.places:
            parts.append("<p>" + " ".join(_chip(n, f"×{c}") for n, c in summary.places[:6]) + "</p>")
        if summary.unanswered:
            parts.append(f'<p style="color:{FAINT}; font-size:12px;">Questions you chose not to answer:</p>')
            for _day, q in summary.unanswered:
                parts.append(f'<p style="margin-left:18px; color:{QUOTE}; font-size:13px;"><i>{html.escape(q)}</i></p>')
    parts.append("</div>")
    return "\n".join(parts)


def render_html(summary: YearSummary, title: str = "Your year", portrait=None, deep=None) -> str:
    if portrait is not None and getattr(portrait, "sections", None):
        return render_portrait(portrait, summary, title, deep=deep)
    if not summary.days:
        return (
            f'<div style="color:{INK}; font-family:Georgia;">'
            f"<h2>{html.escape(title)}</h2>"
            f'<p style="color:{FAINT};">Nothing written yet. The page fills in as you do.</p></div>'
        )

    parts: list[str] = [f'<div style="color:{INK}; font-family:Georgia;">']
    span = (
        f"{_month(summary.first)} to {_month(summary.last)}"
        if summary.first.month != summary.last.month
        else _month(summary.first)
    )
    headline = f"You wrote on {summary.days} days, {span}."
    if summary.people:
        n = len([p for p in summary.people if p.count >= 3])
        if n:
            headline += f" {n} {'person' if n == 1 else 'people'} kept showing up."
    if summary.circling:
        c = summary.circling[0]
        headline += f" One thread ran through {c.months} months of it."
    parts.append(f"<h2>{html.escape(title)}</h2>")
    parts.append(f'<p style="font-size:16px;">{html.escape(headline)}</p>')
    parts.append(
        f'<p style="color:{FAINT}; font-size:11px;">{summary.words:,} words, all of them yours. '
        "Nothing on this page left your machine.</p>"
    )

    if summary.energy_weeks:
        arc = sparkline([v for _, v in summary.energy_weeks])
        parts.append(_h2("How you sounded"))
        parts.append(
            f'<p style="color:{ARC}; font-size:20px; letter-spacing:1px;">{arc}</p>'
            f'<p style="color:{FAINT}; font-size:11px;">'
            f"{_short(summary.energy_weeks[0][0])} → {_short(summary.energy_weeks[-1][0])}"
            " · a shape, not a score</p>"
        )

    if summary.people:
        parts.append(_h2("People"))
        chips = " ".join(
            _chip(p.name, f"×{p.count} · {_short(p.first)}–{_short(p.last)}")
            for p in summary.people
        )
        parts.append(f"<p>{chips}</p>")

    if summary.places:
        parts.append(_h2("Places"))
        parts.append("<p>" + " ".join(_chip(n, f"×{c}") for n, c in summary.places) + "</p>")

    if summary.circling:
        parts.append(_h2("You kept circling back to"))
        for t in summary.circling:
            parts.append(
                f'<p><b>{html.escape(t.theme)}</b> <span style="color:{FAINT};">'
                f"— {t.count} days across {t.months} months</span></p>"
            )
            for day, q in t.quotes:
                parts.append(_quote(day, q))

    other = [t for t in summary.threads if t not in summary.circling]
    if other:
        parts.append(_h2("Threads"))
        for t in other:
            parts.append(
                f'<p><b>{html.escape(t.theme)}</b> <span style="color:{FAINT};">'
                f"— {t.count} {'day' if t.count == 1 else 'days'}</span></p>"
            )
            for day, q in t.quotes[:2]:
                parts.append(_quote(day, q))

    if summary.unresolved:
        parts.append(_h2("Left open"))
        for day, text in summary.unresolved:
            parts.append(
                f'<p>{html.escape(text)} <span style="color:{FAINT}; font-size:11px;">— {_short(day)}</span></p>'
            )

    if summary.unanswered:
        parts.append(_h2("Questions you never answered"))
        for day, q in summary.unanswered[-8:]:
            parts.append(
                f'<p style="color:{ACCENT};"><i>{html.escape(q)}</i> '
                f'<span style="color:{FAINT}; font-size:11px;">— {_short(day)}</span></p>'
            )

    if summary.answers:
        parts.append(_h2("Question by question, in your words"))
        for question, phrase in summary.answers:
            parts.append(
                f'<p style="color:{FAINT}; font-size:12px; margin-bottom:0;">'
                f"{html.escape(question)}</p>"
                f'<p style="margin-top:2px; margin-left:18px; color:{QUOTE};">'
                f"<i>“{html.escape(phrase)}”</i></p>"
            )
    elif summary.in_your_words:
        parts.append(_h2("The year, in your words"))
        for day, phrase in summary.in_your_words:
            parts.append(_quote(day, phrase))

    parts.append("</div>")
    return "\n".join(parts)


def render_markdown(summary: YearSummary, title: str = "Your year", portrait=None, deep=None) -> str:
    """The same page as plain Markdown, for export."""
    if portrait is not None and getattr(portrait, "sections", None):
        lines = [f"# {title}", ""]
        name = portrait.get("name")
        if name and name.name:
            lines += [f"## {name.name}", "", f"_{name.text}_", ""]
        areas = getattr(portrait, "areas", [])
        if areas:
            lines.append("## How you're doing")
            lines.append("_A generous read, not a grade._")
            lines.append("")
            for a in areas:
                arrow = _ARROW.get(a.get("direction", "steady"), "→")
                lines.append(f"- **{a.get('area','')}** — {int(a.get('score',0))}/100 {arrow}")
                if a.get("working"):
                    lines.append(f"  - {a['working']}")
                if a.get("next"):
                    lines.append(f"  - **Next** {a['next']}")
            lines.append("")
        for s in portrait.sections:
            if s.key == "name":
                continue
            lines.append(f"## {s.title}")
            if s.name:
                lines.append(f"**{s.name}**")
            for item in s.items:
                lines.append(f"- **{item['name']}** — _{item['evidence']}_")
            if s.text:
                lines.append(s.text)
            if s.keep:
                lines += ["", f"> {s.keep}"]
            lines.append("")
        if deep is not None and (getattr(deep, "answers", None) or getattr(deep, "letter", "")):
            if deep.answers:
                lines += ["## Your year, answer by answer", ""]
                for a in deep.answers:
                    lines += [f"**{int(a.get('index', 0)) + 1}. {a.get('question', '')}**",
                              "", str(a.get("reading", "")), ""]
            if deep.letter:
                lines += ["## A letter, at the end", "", deep.letter, ""]
        if summary.unanswered:
            lines.append("## Questions you chose not to answer")
            lines += [f"- {q}" for _, q in summary.unanswered]
        return "\n".join(lines).rstrip() + "\n"
    if not summary.days:
        return f"# {title}\n\nNothing written yet.\n"
    lines = [f"# {title}", ""]
    lines.append(f"You wrote on {summary.days} days ({summary.words:,} words).")
    lines.append("")
    if summary.people:
        lines.append("## People")
        lines += [f"- {p.name} — ×{p.count}, {_short(p.first)}–{_short(p.last)}" for p in summary.people]
        lines.append("")
    if summary.places:
        lines.append("## Places")
        lines += [f"- {n} — ×{c}" for n, c in summary.places]
        lines.append("")
    for heading, threads in (("You kept circling back to", summary.circling),
                             ("Threads", [t for t in summary.threads if t not in summary.circling])):
        if threads:
            lines.append(f"## {heading}")
            for t in threads:
                lines.append(f"**{t.theme}** — {t.count} days across {t.months} months")
                lines += [f"> “{q}” — {_short(d)}" for d, q in t.quotes]
                lines.append("")
    if summary.unanswered:
        lines.append("## Questions you never answered")
        lines += [f"- {q} — {_short(d)}" for d, q in summary.unanswered]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
