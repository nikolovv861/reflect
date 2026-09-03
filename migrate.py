"""One-off: fold old per-session files into per-day pages.

The app used to write one file per session in a chat-shaped format
(`## ai` / `## me`). It now writes one page per day with questions as
blockquotes. This merges any old files into the new shape, in chronological
order, without losing a word.

Safe to run twice: already-migrated files are skipped.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from journal.store import QUESTION, WRITING, Block, Page, load, path_for, save

OLD_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{4})\.md$")
TURN = re.compile(r"^## (ai|me)\s*$", re.MULTILINE)


def read_old(path: Path) -> list[Block]:
    text = path.read_text(encoding="utf-8")
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            body = text[end + 4 :]
    blocks: list[Block] = []
    matches = list(TURN.finditer(body))
    for i, m in enumerate(matches):
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[m.end() : stop].strip()
        if content:
            blocks.append(
                Block(QUESTION if m.group(1) == "ai" else WRITING, content)
            )
    return blocks


def main(directory: Path) -> int:
    by_day: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(directory.glob("*.md")):
        m = OLD_NAME.match(path.name)
        if m:
            by_day[m.group(1)].append(path)

    if not by_day:
        print("Nothing to migrate.")
        return 0

    for day_str, paths in sorted(by_day.items()):
        day = date.fromisoformat(day_str)
        target = path_for(directory, day)

        blocks: list[Block] = []
        if target.exists():
            blocks.extend(load(target).blocks)
        for path in paths:  # sorted by name == sorted by time
            blocks.extend(read_old(path))

        page = Page(
            day=day,
            model="migrated",
            prompt_version="migrated",
            blocks=blocks,
        )
        save(page, directory)
        words = page.words
        print(f"{day_str}: merged {len(paths)} session(s) -> {target.name} "
              f"({len(blocks)} blocks, {words} words)")
        for path in paths:
            path.unlink()
    return 0


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Documents" / "journal"
    raise SystemExit(main(d))
