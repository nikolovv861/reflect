"""The whole reason this app exists: nothing you write ever leaves the machine.

reflect keeps a journal you can be honest in precisely because it never uploads
a word -- the model runs locally, the pages are plain files on your disk. That
promise is not a feature to be tested lightly; it is the product. So this file
does the bluntest possible check: it makes *any* attempt to open a socket blow
up, then runs the real store, engine, and UI code paths and asserts they finish
without ever reaching for the network.

If some future change quietly adds an HTTP call -- telemetry, a "sync" button, a
crash reporter, a model download that fires at the wrong time -- one of these
tests fails loudly rather than the breach shipping silently.
"""
from __future__ import annotations

import re
import socket
from datetime import date

import pytest

from journal.engine import Engine
from journal.store import (
    QUESTION,
    WRITING,
    Block,
    Note,
    Page,
    list_notes,
    load,
    open_day,
    recent_pages,
    save,
    save_note,
    search,
    seed_notes,
)

DAY = date(2026, 9, 3)


@pytest.fixture
def no_network(monkeypatch):
    """Turn every socket attempt into a loud failure.

    Constructing a socket, opening a connection, or resolving a hostname all
    raise, so any code that tries to talk to the network trips this instead of
    silently succeeding (or hanging on a real DNS lookup).
    """

    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    return forbidden


# --- a stub model, so no 2.5GB download and no native side ------------------
#
# Mirrors tests/test_engine.py deliberately: replicated rather than imported so
# this file stands on its own and does not couple to another test module.


class StubChat:
    """Stands in for nobodywho.Chat so tests need no model and no network."""

    def __init__(self, model_path, reply="Why did you stop there?"):
        self.model_path = model_path
        self.reply = reply
        self.system_prompt = None
        self.template_vars = {}
        self.prompts = []

    def set_system_prompt(self, text):
        self.system_prompt = text

    def set_template_variable(self, name, value):
        self.template_vars[name] = value

    def reset_history(self):
        pass

    def ask(self, prompt):
        self.prompts.append(prompt)
        return iter(re.findall(r"\S+\s*", self.reply))

    def stop_generation(self):
        pass


def _stub_engine(reply="Why did you stop there?"):
    def factory(model_path):
        return StubChat(model_path, reply)

    return Engine("model://stub", "v3-buried", chat_factory=factory)


# --- store ------------------------------------------------------------------


def test_store_never_touches_network(no_network, tmp_path):
    """A full round-trip through the disk layer touches only the disk."""
    page = open_day(tmp_path, model="stub", prompt_version="v3-buried", day=DAY)
    assert page.blocks == []

    page.blocks = [
        Block(WRITING, "A quiet morning."),
        Block(QUESTION, "Why quiet?"),
        Block(WRITING, "Because nobody called."),
    ]
    save(page, tmp_path)

    reloaded = load(tmp_path / f"{DAY.isoformat()}.md")
    assert [b.kind for b in reloaded.blocks] == [WRITING, QUESTION, WRITING]
    assert reloaded.words == 6

    recent = recent_pages(tmp_path)
    assert len(recent) == 1
    assert recent[0].day == DAY

    assert seed_notes(tmp_path) is True
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    slugs = {n.slug for n in list_notes(tmp_path)}
    assert "values" in slugs

    hits = search(tmp_path, "quiet")
    assert any(h.kind == "page" for h in hits)


# --- engine -----------------------------------------------------------------


def test_engine_never_touches_network(no_network):
    """The engine's orchestration is offline; only the local model would run.

    We inject a stub chat, so no real model loads -- proving that everything
    the Engine itself does (prompt assembly, reset, streaming, truncation)
    happens without a socket.
    """
    engine = _stub_engine()
    page = Page(
        day=DAY,
        model="stub",
        prompt_version="v3-buried",
        blocks=[Block(WRITING, "A long day.")],
    )
    question = engine.ask_text(page)
    assert isinstance(question, str)
    assert question == "Why did you stop there?"


# --- ui ---------------------------------------------------------------------

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from journal.ui import Window  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - headless init failure
        pytest.skip(f"PySide6 cannot initialise headless: {exc}")


def test_ui_roundtrip_never_touches_network(no_network, app, tmp_path):
    """Opening the window and using it -- save, sidebar, search -- stays local.

    The window loads no model unless request_question() is called, so building
    it and exercising the everyday editing paths must never open a socket.
    """
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.editor.setPlainText("A quiet morning at the desk.")
        win.save_now()
        assert load(tmp_path / f"{DAY.isoformat()}.md").blocks[0].text == (
            "A quiet morning at the desk."
        )

        win.refresh_sidebar()
        win.search_box.setText("quiet")
        # No assertion on results needed: the point is that none of this
        # reached the network. If it had, `no_network` would have raised.
    finally:
        win._autosave.stop()
