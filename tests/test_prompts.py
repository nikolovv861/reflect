from journal.engine import DEFAULT_PROMPT
from journal.prompts import load_prompt, list_prompts, starters


def test_the_known_variants_are_discoverable():
    assert set(list_prompts()) == {
        "v1-plain", "v2-specific", "v3-buried", "v4-evaluative",
        "v5-thread", "v6-direct",
    }


def test_load_prompt_returns_non_empty_text():
    assert len(load_prompt("v3-buried")) > 100


def test_the_default_prompt_is_a_real_variant():
    assert DEFAULT_PROMPT in list_prompts()
    assert len(load_prompt(DEFAULT_PROMPT)) > 100


def test_open_variants_ban_the_feelings_question():
    for name in ("v2-specific", "v3-buried", "v5-thread", "v6-direct"):
        assert "How did that make you feel?" in load_prompt(name)


def test_starters_are_stripped_and_non_empty():
    values = starters()
    assert len(values) >= 3
    assert all(v == v.strip() and v for v in values)


def test_unknown_prompt_raises():
    try:
        load_prompt("nope")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")
