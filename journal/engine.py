"""Turns a journal session into exactly one question.

Stateless on purpose: every call rebuilds the transcript and resets the chat,
so the evaluation harness and the UI exercise identical behaviour.
"""
from __future__ import annotations

from typing import Callable, Iterator, Protocol, Sequence

from journal.practices import DEFAULT as DEFAULT_PRACTICE
from journal.practices import load_practice
from journal.prompts import load_prompt
from journal.store import QUESTION, WRITING, Page

DEFAULT_MODEL = (
    "huggingface:NobodyWho/Qwen_Qwen3-4B-GGUF/Qwen_Qwen3-4B-Q4_K_M.gguf"
)
DEFAULT_PROMPT = "v6-direct"

_ASKED = "A question already asked (now ask about something else):"


class ChatLike(Protocol):
    def set_system_prompt(self, text: str) -> None: ...
    def set_template_variable(self, name: str, value) -> None: ...
    def reset_history(self) -> None: ...
    def ask(self, prompt: str): ...
    def stop_generation(self) -> None: ...


def first_question(text: str) -> str:
    """Keep only the first question. Guards against multi-question replies."""
    cleaned = text.strip()
    mark = cleaned.find("?")
    if mark == -1:
        return cleaned
    return cleaned[: mark + 1].strip()


import re as _re

# Feelings-fishing: the one move the whole app is built to avoid. A small model
# reaches for it whenever the page is thin, so we score it down hard.
_FEELINGS_RE = _re.compile(
    r"(how (did|does|do)\s+(that|it|this|you)\b.*\bfeel"
    r"|mak(e|es|ing)\s+you\s+feel"
    r"|made\s+you\s+feel"
    r"|feel\s+that\s+way"
    r"|what\s+(feeling|emotion))",
    _re.IGNORECASE,
)
_THIRD_PERSON_RE = _re.compile(r"\bthey\b|\bthe (writer|person)\b", _re.IGNORECASE)


def score_question(question: str, writing_lower: str) -> float:
    """Heuristic for best-of-N: reward a question that speaks to 'you' and
    quotes the writer's own words; punish feelings-fishing and third person.
    No model call, so ranking N candidates stays fast."""
    q = question.strip()
    ql = q.lower()
    score = 0.0
    if ql.endswith("?"):
        score += 1
    if _re.search(r"\byou(r)?\b", ql):
        score += 1
    for quoted in _re.findall(r'["“]([^"”]{4,})["”]', q):
        if quoted.lower().strip() in writing_lower:
            score += 3
            break
    if _FEELINGS_RE.search(ql):
        score -= 4
    if _THIRD_PERSON_RE.search(ql):
        score -= 2
    words = len(q.split())
    if words < 5 or words > 40:
        score -= 1
    return score


CONTEXT_TOKENS = 8192


def _default_factory(model_path: str) -> ChatLike:
    from nobodywho import Chat

    # The portrait reads a whole fourteen-answer transcript in one prompt, so
    # ask for a roomy window; fall back to the library default if the build
    # does not take the argument.
    try:
        return Chat(model_path, n_ctx=CONTEXT_TOKENS)
    except TypeError:
        return Chat(model_path)


def _excerpt(page: Page, limit: int = 240) -> str:
    """A short, whitespace-collapsed taste of a day's writing (no questions)."""
    written = " ".join(
        b.text for b in page.blocks if b.kind == WRITING and b.text.strip()
    )
    written = " ".join(written.split())
    if len(written) > limit:
        written = written[:limit].rstrip() + "…"
    return written


def _history_preamble(history: Sequence[Page]) -> str:
    """Earlier days of the same practice, framed as context and nothing more.

    The arc of a practice should reach the QUESTION, not just the header. But
    this is the exact spot where a journal quietly turns into a report card, so
    the instruction is blunt: it is background, the question is still about
    today, and the model must never tally the days or grade the arc.
    """
    lines = [
        "Earlier days of this same practice, for continuity only. This is "
        "background, not part of today's page: do not quote it back, do not "
        "count the days, and do not judge whether they are making progress. "
        "Let it make your one question about today more informed, nothing more.",
    ]
    for prev in history:
        excerpt = _excerpt(prev)
        if excerpt:
            lines.append(f"{prev.day.isoformat()} — {excerpt}")
    return "\n".join(lines)


def page_text(page: Page, history: Sequence[Page] = ()) -> str:
    """The day's page as the model sees it.

    Not a chat transcript -- a document. Prior questions are included as
    context so the model does not repeat itself, but they are framed as notes
    in the margin rather than turns in a conversation.

    `history` is earlier pages of the same practice (see store.practice_history):
    when present, a compact digest is placed ahead of today's page so a day-N
    question can build on the arc. When it is empty the output is unchanged.
    """
    parts: list[str] = []
    if history:
        parts.append(_history_preamble(history))
    parts.append(f"This is today's journal page, written on {page.day.isoformat()}.")
    for block in page.blocks:
        if block.kind == QUESTION:
            parts.append(f"{_ASKED}\n{block.text}")
        else:
            parts.append(block.text)
    parts.append(
        "Ask one question about today's page above."
        if history
        else "Ask one question about the page above."
    )
    return "\n\n".join(parts)


SUGGEST_SYS = (
    "You help someone continue their own journal entry, in their exact voice.\n"
    "Read what they have written and offer ONE short continuation -- a single "
    "sentence, two at the very most -- that could plausibly be their own next "
    "line. Match their tone, their vocabulary, their rhythm, and stay in the "
    "first person.\n"
    "Do not summarise, praise, advise, analyse, or ask a question. Do not "
    "explain yourself. Write only the continuation itself -- no quotation "
    "marks, no preamble, no 'Here is'."
)

_SENTENCE_END = tuple(".!?…")


def _suggest_text(page: Page) -> str:
    """The in-progress entry, framed as something to continue rather than
    question. Prior margin questions are kept as light context so a suggestion
    does not simply answer them."""
    parts = ["Here is a journal entry in progress:", ""]
    for block in page.blocks:
        if block.kind == QUESTION:
            parts.append(f"(a question resting in the margin: {block.text})")
        else:
            parts.append(block.text)
    parts.append("")
    parts.append("Continue it with one short line, in the same voice.")
    return "\n".join(parts)


def clean_suggestion(text: str, max_sentences: int = 2) -> str:
    """Trim a raw completion to a short, quote-free continuation."""
    cleaned = " ".join(text.split()).strip().strip("\"“”")
    if not cleaned:
        return ""
    sentences: list[str] = []
    start = 0
    for i, ch in enumerate(cleaned):
        if ch in _SENTENCE_END:
            sentences.append(cleaned[start : i + 1].strip())
            start = i + 1
            if len(sentences) >= max_sentences:
                break
    if start < len(cleaned) and len(sentences) < max_sentences:
        sentences.append(cleaned[start:].strip())
    return " ".join(s for s in sentences if s).strip()


class Engine:
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        prompt_version: str = DEFAULT_PROMPT,
        practice: str = DEFAULT_PRACTICE,
        chat_factory: Callable[[str], ChatLike] | None = None,
    ) -> None:
        factory = chat_factory or _default_factory
        self.prompt_version = prompt_version
        self.practice = practice
        self._context = ""
        self._chat = factory(model_path)
        # Qwen3 emits reasoning tokens by default. They must never reach the
        # transcript, and they waste time we would rather spend on the answer.
        self._chat.set_template_variable("enable_thinking", False)
        self._apply_system_prompt()

    def _apply_system_prompt(self) -> None:
        """Base question style, the practice frame, then standing context."""
        parts = [load_prompt(self.prompt_version)]
        addendum = load_practice(self.practice).addendum.strip()
        if addendum:
            parts.append(addendum)
        if self._context.strip():
            parts.append(
                "The writer has separately written down what matters to them:\n\n"
                f"{self._context.strip()}\n\n"
                "Draw on this only where it is genuinely relevant to what they "
                "wrote today. Never quote it back at them, never remind them of "
                "it, and never measure the day against it."
            )
        self._chat.set_system_prompt("\n\n".join(parts))

    def set_context(self, context: str) -> None:
        """Standing notes -- values, goals -- that outlive a single day."""
        self._context = context or ""
        self._apply_system_prompt()

    def set_prompt_version(self, prompt_version: str) -> None:
        self.prompt_version = prompt_version
        self._apply_system_prompt()

    def set_practice(self, practice: str) -> None:
        self.practice = practice
        self._apply_system_prompt()

    def ask(self, page: Page, history: Sequence[Page] = ()) -> Iterator[str]:
        # reset_history(), not reset(): reset() would also wipe the system
        # prompt, which is the entire product.
        self._chat.reset_history()
        return iter(self._chat.ask(page_text(page, history)))

    def ask_text(self, page: Page, history: Sequence[Page] = ()) -> str:
        return first_question("".join(self.ask(page, history)))

    def _set_sampler(self, config) -> None:
        # Defensive: test stubs don't implement sampler control, and warming a
        # question must never crash on a chat backend that lacks it.
        try:
            self._chat.set_sampler_config(config)
        except Exception:  # noqa: BLE001
            pass

    def ask_best_of(
        self,
        page: Page,
        history: Sequence[Page] = (),
        n: int = 3,
        avoid: Sequence[str] = (),
    ) -> str:
        """Ask n times with varied seeds and keep the best by score_question().

        A single greedy shot from a 4B model is a coin-flip between a sharp
        question and a generic one; generating a few and picking the one that
        quotes the writer and avoids feelings-fishing is the cheapest way to
        raise the floor. `avoid` lets a re-roll skip a question just shown.
        """
        from nobodywho import SamplerBuilder, SamplerPresets

        writing_lower = " ".join(
            b.text.lower() for b in page.blocks if b.kind == WRITING
        )
        prompt = page_text(page, history)
        candidates: list[str] = []
        try:
            for i in range(max(1, n)):
                self._set_sampler(
                    SamplerBuilder().temperature(0.85).seed(1009 + i * 7).dist()
                )
                self._chat.reset_history()
                q = first_question("".join(self._chat.ask(prompt)))
                if q:
                    candidates.append(q)
        finally:
            self._set_sampler(SamplerPresets.default())

        if not candidates:
            return ""
        avoid_set = {a.strip() for a in avoid if a}
        fresh = [c for c in candidates if c.strip() not in avoid_set] or candidates
        return max(fresh, key=lambda c: score_question(c, writing_lower))

    def suggest(self, page: Page, history: Sequence[Page] = ()) -> str:
        """One short continuation in the writer's own voice -- the co-writer.

        Deliberately separate from ask(): asking is the journal's default and
        never puts words in your mouth; suggesting only ever offers, and in the
        UI nothing is saved until you accept it.
        """
        self._chat.set_system_prompt(SUGGEST_SYS)
        self._chat.reset_history()
        try:
            raw = "".join(self._chat.ask(_suggest_text(page)))
        finally:
            self._apply_system_prompt()
        return clean_suggestion(raw)

    def extract_json(self, instructions: str, content: str, schema: dict) -> str:
        """One schema-constrained completion under a temporary system prompt.

        The sampler is forced to emit JSON matching `schema`, so even a 4B
        model cannot hand back broken output. Prompt and sampler are both
        restored afterwards. Used by journal.year for the Year page.
        """
        from nobodywho import SamplerPresets

        self._chat.set_system_prompt(instructions)
        self._chat.reset_history()
        try:
            constrained = SamplerPresets.constrain_with_json_schema(schema)
        except Exception:  # noqa: BLE001 - fall back to free sampling
            constrained = None
        if constrained is not None:
            self._set_sampler(constrained)
        try:
            return "".join(self._chat.ask(content))
        finally:
            self._set_sampler(SamplerPresets.default())
            self._apply_system_prompt()

    def score_reply(self, instructions: str, content: str) -> str:
        """Run one off-topic completion with a temporary system prompt, then
        restore the journaling prompt. Used by the evaluation harness to let the
        same local model judge a question against a rubric -- no second model,
        no network. Not used by the app itself.
        """
        self._chat.set_system_prompt(instructions)
        self._chat.reset_history()
        try:
            return "".join(self._chat.ask(content))
        finally:
            self._apply_system_prompt()

    def stop(self) -> None:
        self._chat.stop_generation()

    def close(self) -> None:
        """Shut the native side down cleanly.

        Without this, the Rust runtime panics on interpreter exit with
        "threads should not terminate unexpectedly" -- which surfaces to the
        user as a crash when they close the app.
        """
        try:
            from nobodywho import cleanup_logging
        except ImportError:
            return
        cleanup_logging()
