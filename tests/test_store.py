from datetime import datetime
from pathlib import Path

from journal.store import Session, Turn, render, parse, save, load, list_sessions


def make_session():
    return Session(
        started=datetime(2026, 9, 3, 14, 32, 11),
        model="Qwen_Qwen3-4B-Q4_K_M",
        prompt_version="v3",
        turns=[
            Turn("ai", "How was your day?"),
            Turn("me", "Long and strange."),
        ],
    )


def test_render_then_parse_round_trips():
    original = make_session()
    restored = parse(render(original))
    assert restored == original


def test_render_contains_frontmatter_and_speakers():
    text = render(make_session())
    assert text.startswith("---\n")
    assert "prompt_version: v3" in text
    assert "## ai" in text
    assert "## me" in text


def test_parse_survives_missing_frontmatter():
    session = parse("## me\n\nJust text, no header.\n")
    assert session.model == "unknown"
    assert session.turns == [Turn("me", "Just text, no header.")]


def test_parse_survives_garbage_timestamp():
    session = parse("---\nstarted: not-a-date\n---\n\n## me\n\nhi\n")
    assert session.turns[0].text == "hi"


def test_round_trip_preserves_unicode_and_blank_lines():
    original = Session(
        started=datetime(2026, 1, 1, 9, 0),
        model="m",
        prompt_version="v1",
        turns=[Turn("me", "café — naïve\n\nsecond paragraph 🙂")],
    )
    assert parse(render(original)).turns[0].text == original.turns[0].text


def test_save_and_load(tmp_path: Path):
    original = make_session()
    path = save(original, tmp_path)
    assert path.name == "2026-09-03-1432.md"
    assert load(path) == original


def test_list_sessions_is_sorted_and_tolerates_missing_dir(tmp_path: Path):
    assert list_sessions(tmp_path / "nope") == []
    save(make_session(), tmp_path)
    assert [p.name for p in list_sessions(tmp_path)] == ["2026-09-03-1432.md"]
