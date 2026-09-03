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
from journal.store import Session, Turn

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


def as_session(text: str) -> Session:
    return Session(
        started=datetime.now(),
        model=DEFAULT_MODEL,
        prompt_version="harness",
        turns=[Turn("me", text)],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
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
            question = engine.ask_text(as_session(text))
            print(f"  {variant:<16} -> {question}", flush=True)
            lines.append(f"- **{variant}** -- {question}")
        lines.append("")

    engine.close()

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y-%m-%d-%H%M}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
