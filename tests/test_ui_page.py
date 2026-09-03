"""The risky part of the journal UI: does a question stay a question?

Questions are marked with a per-paragraph block property. If that marker
bleeds into typed text, or fails to survive a save/reload cycle, the page
silently turns back into a chat log -- or worse, quotes the writer's own
words back at them as though the app had said them.
"""
from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from journal.store import QUESTION, WRITING, Block, load, path_for  # noqa: E402
from journal.ui import Window  # noqa: E402

DAY = date(2026, 9, 3)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    yield win
    win._autosave.stop()


def test_a_blank_day_starts_empty(window):
    assert window.harvest() == []
    assert window.page.words == 0


def test_typed_text_is_harvested_as_writing(window):
    window.editor.setPlainText("A quiet morning.")
    assert window.harvest() == [Block(WRITING, "A quiet morning.")]


def test_streamed_question_is_marked_as_a_question(window):
    window.editor.setPlainText("A quiet morning.")
    window._streaming = False
    window.on_token("Why quiet?")
    window.on_question("Why quiet?")
    kinds = [b.kind for b in window.harvest()]
    assert kinds == [WRITING, QUESTION]


def test_writing_after_a_question_is_not_marked_as_a_question(window):
    """The bug that would ruin the page: format bleeding into typed text."""
    window.editor.setPlainText("A quiet morning.")
    window._streaming = False
    window.on_token("Why quiet?")
    window.on_question("Why quiet?")

    # Simulate the writer continuing to type where the cursor was left.
    window.editor.insertPlainText("Because nobody called.")

    blocks = window.harvest()
    assert [b.kind for b in blocks] == [WRITING, QUESTION, WRITING]
    assert blocks[-1].text == "Because nobody called."


def test_page_survives_save_and_reopen(window, tmp_path, app):
    window.editor.setPlainText("A quiet morning.")
    window._streaming = False
    window.on_token("Why quiet?")
    window.on_question("Why quiet?")
    window.editor.insertPlainText("Because nobody called.")
    window.save_now()

    on_disk = load(path_for(tmp_path, DAY))
    assert [b.kind for b in on_disk.blocks] == [WRITING, QUESTION, WRITING]

    # Reopening the same day continues the page rather than starting fresh.
    reopened = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        assert [b.kind for b in reopened.harvest()] == [
            WRITING,
            QUESTION,
            WRITING,
        ]
        assert reopened.page.words == 6
    finally:
        reopened._autosave.stop()


def test_questions_do_not_count_towards_the_word_count(window):
    window.editor.setPlainText("one two three")
    window._streaming = False
    window.on_token("A rather long question with many words in it?")
    window.on_question("A rather long question with many words in it?")
    window._update_counter()
    assert window.page.words == 3


def test_asking_with_an_empty_page_is_refused(window):
    window.request_question()
    assert "Write something first." in window.statusBar().currentMessage()
    assert window.ask_button.isEnabled()
