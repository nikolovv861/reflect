"""Run every prompt variant against every fixture entry, side by side.

Question quality is not unit-testable. This makes it comparable, which is the
next best thing -- and it is the loop that makes an afternoon of prompt
iteration possible.

Usage:
    python evaluate.py                     # all variants, all entries
    python evaluate.py --variants v2-specific v3-buried
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from journal.engine import DEFAULT_MODEL, Engine
from journal.prompts import list_prompts
from journal.store import WRITING, Block, Page

ENTRIES = Path("fixtures/entries")
RESULTS = Path("fixtures/results")


def load_entries() -> list[tuple[str, str]]:
    if not ENTRIES.exists():
        return []
    return [
        (p.name, p.read_text(encoding="utf-8").strip())
        for p in sorted(ENTRIES.glob("*.md"))
        if p.name != "README.md"
    ]


def as_page(text: str) -> Page:
    return Page(
        day=datetime.now().date(),
        model=DEFAULT_MODEL,
        prompt_version="harness",
        blocks=[Block(WRITING, text)],
    )


JUDGE_SYS = (
    "You grade one follow-up question asked about a journal entry, against three "
    "rules a good question here must obey.\n"
    "1. SPECIFIC: it points at something concrete the writer actually wrote, "
    "not a generic prompt that would fit any entry.\n"
    "2. OPEN: it is curious, not evaluative -- it does not assess, score, "
    "praise, advise, or summarise the writer back to themselves.\n"
    "3. NOT_FEELING: it is not 'How did that make you feel?' or any rephrasing "
    "of it.\n"
    "For each rule decide yes or no. Reply with exactly one line, three tokens, "
    "nothing else. For example, if it is specific and open but is a feelings "
    "question you would reply:\n"
    "SPECIFIC=yes OPEN=yes NOT_FEELING=no\n"
    "Now judge the question you are given. Do not repeat the example."
)


def _clean_verdict(raw: str) -> str:
    """Keep only real yes/no tokens; drop any echoed 'yes|no' template."""
    out = []
    for tok in raw.replace("\n", " ").split():
        key, _, val = tok.partition("=")
        if key in {"SPECIFIC", "OPEN", "NOT_FEELING"} and val in {"yes", "no"}:
            out.append(f"{key}={val}")
    return " ".join(out)


def judge(engine: Engine, entry: str, question: str) -> str:
    """One rubric verdict line for a question, scored by the same local model."""
    content = f"ENTRY:\n{entry}\n\nQUESTION:\n{question}\n\nVerdict:"
    raw = engine.score_reply(JUDGE_SYS, content).strip()
    return _clean_verdict(raw) or raw.replace("\n", " ")[:60]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Score each question against the rubric with the same local model.",
    )
    args = parser.parse_args()

    entries = load_entries()
    if not entries:
        print(
            "No fixture entries found. Add real .md entries to fixtures/entries/ "
            "and run again. See fixtures/entries/README.md.",
            file=sys.stderr,
        )
        return 1

    variants = args.variants or list_prompts()
    print("Loading model (first run downloads ~2.5GB)...", flush=True)
    engine = Engine(args.model, variants[0])

    lines = [
        f"# Prompt evaluation -- {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Model: `{args.model}`",
        "",
    ]

    for name, text in entries:
        words = len(text.split())
        print(f"\n=== {name} ({words} words) ===", flush=True)
        lines += [f"## {name}", "", f"_{words} words_", ""]
        for variant in variants:
            engine.set_prompt_version(variant)
            question = engine.ask_text(as_page(text))
            verdict = ""
            if args.judge:
                verdict = judge(engine, text, question)
                engine.set_prompt_version(variant)  # judge restored the prompt
            suffix = f"   [{verdict}]" if verdict else ""
            print(f"  {variant:<16} -> {question}{suffix}", flush=True)
            lines.append(
                f"- **{variant}** -- {question}"
                + (f"  \n  _rubric: {verdict}_" if verdict else "")
            )
        lines.append("")

    engine.close()

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y-%m-%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
