"""Prompt variants, kept as files so they can be diffed and versioned."""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    path = _DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt variant named {name!r} in {_DIR}")
    return path.read_text(encoding="utf-8").strip()


def list_prompts() -> list[str]:
    return sorted(p.stem for p in _DIR.glob("*.md"))


def starters() -> list[str]:
    raw = (_DIR / "starters.txt").read_text(encoding="utf-8")
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("#")
    ]
