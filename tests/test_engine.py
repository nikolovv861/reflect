import re

from datetime import date

from journal.engine import Engine, first_question
from journal.store import QUESTION, WRITING, Block, Page


class StubChat:
    """Stands in for nobodywho.Chat so tests need no 2.5GB model."""

    def __init__(self, model_path, reply="Why did you stop there?"):
        self.model_path = model_path
        self.reply = reply
        self.system_prompt = None
        self.template_vars = {}
        self.resets = 0
        self.prompts = []
        self.stopped = False

    def set_system_prompt(self, text):
        self.system_prompt = text

    def set_template_variable(self, name, value):
        self.template_vars[name] = value

    def reset_history(self):
        self.resets += 1

    def ask(self, prompt):
        self.prompts.append(prompt)
        # Real tokenizers carry their own whitespace, so tokens must rejoin
        # into the original string. Splitting on spaces and dropping them
        # would make the stub lie about how generation behaves.
        return iter(re.findall(r"\S+\s*", self.reply))

    def stop_generation(self):
        self.stopped = True


def make_page(*blocks):
    return Page(
        day=date(2026, 9, 3),
        model="stub",
        prompt_version="v3-buried",
        blocks=list(blocks),
    )


def build(reply="Why did you stop there?"):
    captured = {}

    def factory(model_path):
        captured["chat"] = StubChat(model_path, reply)
        return captured["chat"]

    engine = Engine("model://stub", "v3-buried", chat_factory=factory)
    return engine, captured["chat"]


def test_first_question_truncates_to_one_question():
    text = "What happened there? And why did you leave it out?"
    assert first_question(text) == "What happened there?"


def test_first_question_passes_through_a_single_question():
    assert first_question("  What happened?  ") == "What happened?"


def test_first_question_returns_text_without_question_mark_unchanged():
    assert first_question("Tell me more about the review.") == (
        "Tell me more about the review."
    )


def test_engine_disables_thinking_and_sets_the_system_prompt():
    engine, chat = build()
    engine.ask_text(make_page(Block(WRITING, "A long day.")))
    assert chat.template_vars["enable_thinking"] is False
    assert "curious" in chat.system_prompt.lower()


def test_engine_resets_before_each_ask():
    engine, chat = build()
    session = make_page(Block(WRITING, "One."))
    engine.ask_text(session)
    engine.ask_text(session)
    assert chat.resets == 2


def test_prompt_includes_the_whole_page():
    engine, chat = build()
    engine.ask_text(
        make_page(Block(QUESTION, "How was your day?"), Block(WRITING, "Strange."))
    )
    sent = chat.prompts[0]
    assert "How was your day?" in sent
    assert "Strange." in sent


def test_prompt_frames_the_page_as_a_document_not_a_chat():
    engine, chat = build()
    engine.ask_text(make_page(Block(WRITING, "A quiet day.")))
    sent = chat.prompts[0]
    assert "journal page" in sent
    # No chat framing anywhere in what the model sees.
    for tell in ("User:", "Assistant:", "They wrote", "You asked"):
        assert tell not in sent


def test_ask_streams_tokens():
    engine, _ = build()
    tokens = list(engine.ask(make_page(Block(WRITING, "hi"))))
    assert len(tokens) > 1
    assert "".join(tokens).strip().startswith("Why")


def test_ask_text_truncates_a_two_question_reply():
    engine, _ = build(reply="What happened? Also, why now?")
    assert engine.ask_text(make_page(Block(WRITING, "hi"))) == "What happened?"


def test_stop_delegates_to_the_chat():
    engine, chat = build()
    engine.ask_text(make_page(Block(WRITING, "hi")))
    engine.stop()
    assert chat.stopped is True


def test_standing_context_reaches_the_system_prompt():
    engine, chat = build()
    engine.set_context("Curiosity, honesty, and not wasting people's time.")
    assert "Curiosity, honesty" in chat.system_prompt
    # And it must be framed as background, never as a yardstick.
    assert "never measure the day against it" in chat.system_prompt


def test_empty_context_adds_nothing():
    engine, chat = build()
    before = chat.system_prompt
    engine.set_context("   ")
    assert chat.system_prompt == before
