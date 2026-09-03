"""Turns a journal session into exactly one question.

Stateless on purpose: every call rebuilds the transcript and resets the chat,
so the evaluation harness and the UI exercise identical behaviour.
"""
from __future__ import annotations

from typing import Callable, Iterator, Protocol

from journal.prompts import load_prompt
from journal.store import QUESTION, Page

DEFAULT_MODEL = (
    "huggingface:NobodyWho/Qwen_Qwen3-4B-GGUF/Qwen_Qwen3-4B-Q4_K_M.gguf"
)
DEFAULT_PROMPT = "v3-buried"

_ASKED = "A question you put to them earlier:"


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


def _default_factory(model_path: str) -> ChatLike:
    from nobodywho import Chat

    return Chat(model_path)


def page_text(page: Page) -> str:
    """The day's page as the model sees it.

    Not a chat transcript -- a document. Prior questions are included as
    context so the model does not repeat itself, but they are framed as notes
    in the margin rather than turns in a conversation.
    """
    parts = [f"This is today's journal page, written on {page.day.isoformat()}."]
    for block in page.blocks:
        if block.kind == QUESTION:
            parts.append(f"{_ASKED}\n{block.text}")
        else:
            parts.append(block.text)
    parts.append("Ask one question about the page above.")
    return "\n\n".join(parts)


class Engine:
    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        prompt_version: str = DEFAULT_PROMPT,
        chat_factory: Callable[[str], ChatLike] | None = None,
    ) -> None:
        factory = chat_factory or _default_factory
        self.prompt_version = prompt_version
        self._chat = factory(model_path)
        # Qwen3 emits reasoning tokens by default. They must never reach the
        # transcript, and they waste time we would rather spend on the answer.
        self._chat.set_template_variable("enable_thinking", False)
        self._chat.set_system_prompt(load_prompt(prompt_version))

    def set_prompt_version(self, prompt_version: str) -> None:
        self.prompt_version = prompt_version
        self._chat.set_system_prompt(load_prompt(prompt_version))

    def ask(self, page: Page) -> Iterator[str]:
        # reset_history(), not reset(): reset() would also wipe the system
        # prompt, which is the entire product.
        self._chat.reset_history()
        return iter(self._chat.ask(page_text(page)))

    def ask_text(self, page: Page) -> str:
        return first_question("".join(self.ask(page)))

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
