"""Turns a journal session into exactly one question.

Stateless on purpose: every call rebuilds the transcript and resets the chat,
so the evaluation harness and the UI exercise identical behaviour.
"""
from __future__ import annotations

from typing import Callable, Iterator, Protocol

from journal.prompts import load_prompt
from journal.store import Session

DEFAULT_MODEL = (
    "huggingface:NobodyWho/Qwen_Qwen3-4B-GGUF/Qwen_Qwen3-4B-Q4_K_M.gguf"
)
DEFAULT_PROMPT = "v3-buried"

_LABELS = {"ai": "You asked", "me": "They wrote"}


class ChatLike(Protocol):
    def set_system_prompt(self, text: str) -> None: ...
    def set_allow_thinking(self, value: bool) -> None: ...
    def reset(self) -> None: ...
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


def transcript(session: Session) -> str:
    parts = [
        f"{_LABELS.get(turn.speaker, turn.speaker)}:\n{turn.text}"
        for turn in session.turns
    ]
    parts.append("Ask one question.")
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
        self._chat.set_allow_thinking(False)
        self._chat.set_system_prompt(load_prompt(prompt_version))

    def set_prompt_version(self, prompt_version: str) -> None:
        self.prompt_version = prompt_version
        self._chat.set_system_prompt(load_prompt(prompt_version))

    def ask(self, session: Session) -> Iterator[str]:
        self._chat.reset()
        return iter(self._chat.ask(transcript(session)))

    def ask_text(self, session: Session) -> str:
        return first_question("".join(self.ask(session)))

    def stop(self) -> None:
        self._chat.stop_generation()
