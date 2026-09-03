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

from PySide6.QtCore import Qt  # noqa: E402
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


# --- practices -------------------------------------------------------------


def test_free_writing_leaves_the_page_blank(window):
    assert window.page.practice == "free"
    assert window.harvest() == []


def test_choosing_a_practice_seeds_its_opening_as_a_question(window):
    window.practice_box.setCurrentIndex(window.practice_box.findData("attention"))
    blocks = window.harvest()
    assert window.page.practice == "attention"
    assert blocks and blocks[0].kind == QUESTION
    assert "attention" in blocks[0].text.lower()


def test_writing_after_a_seeded_opening_is_your_own(window):
    window.practice_box.setCurrentIndex(window.practice_box.findData("attention"))
    window.editor.insertPlainText("On my phone, and it just ended up there.")
    blocks = window.harvest()
    assert [b.kind for b in blocks] == [QUESTION, WRITING]
    assert blocks[1].text == "On my phone, and it just ended up there."


def test_practice_is_persisted_and_restored(window, tmp_path):
    window.practice_box.setCurrentIndex(window.practice_box.findData("story"))
    window.editor.insertPlainText("A chapter about waiting.")
    window.save_now()
    assert load(path_for(tmp_path, DAY)).practice == "story"

    reopened = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        assert reopened.page.practice == "story"
        assert reopened.practice_box.currentData() == "story"
    finally:
        reopened._autosave.stop()


def test_arc_label_counts_days_present_never_days_missed(window):
    window.practice_box.setCurrentIndex(window.practice_box.findData("attention"))
    assert "DAY 1 OF 7" in window.arc_label.text()


def test_open_ended_practice_shows_no_arc_label(window):
    assert window.arc_label.text() == ""


def test_one_off_practice_shows_no_arc_label(window):
    window.practice_box.setCurrentIndex(window.practice_box.findData("values"))
    assert window.arc_label.text() == ""


# --- sidebar, notes, search ------------------------------------------------

from datetime import date as _date  # noqa: E402

from journal.store import (  # noqa: E402
    Note,
    Page,
    list_notes,
    load_note,
    save,
    save_note,
)
from journal.ui import NOTE, PAGE  # noqa: E402


def _sidebar_entries(win):
    out = []
    for row in range(win.sidebar.count()):
        item = win.sidebar.item(row)
        out.append((item.data(Qt.UserRole), item.text()))
    return out


def test_sidebar_lists_today_even_before_anything_is_written(window):
    keys = [d for d, _ in _sidebar_entries(window)]
    assert (PAGE, DAY.isoformat()) in keys


def test_sidebar_lists_past_days_newest_first(app, tmp_path):
    from journal.store import WRITING as W

    for d in (_date(2026, 9, 1), _date(2026, 9, 2)):
        save(Page(day=d, model="m", prompt_version="v1",
                  blocks=[Block(W, f"day {d.day}")]), tmp_path)
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        pages = [k for (kind, k), _ in _sidebar_entries(win) if kind == PAGE]
        assert pages == ["2026-09-03", "2026-09-02", "2026-09-01"]
    finally:
        win._autosave.stop()


def test_opening_a_past_day_loads_it_without_losing_today(app, tmp_path):
    from journal.store import WRITING as W

    save(Page(day=_date(2026, 9, 1), model="m", prompt_version="v1",
              blocks=[Block(W, "an older day")]), tmp_path)
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.editor.insertPlainText("written today")
        win.open_page(_date(2026, 9, 1))
        assert win.page.day == _date(2026, 9, 1)
        assert "an older day" in win.editor.toPlainText()
        # Today was saved on the way out, not discarded.
        assert "written today" in load(path_for(tmp_path, DAY)).blocks[0].text
    finally:
        win._autosave.stop()


def test_notes_appear_in_the_sidebar_and_open(app, tmp_path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        assert (NOTE, "values") in [d for d, _ in _sidebar_entries(win)]
        win.open_note("values")
        assert win.mode == NOTE
        assert win.editor.toPlainText() == "Curiosity."
        # Notes are reference documents, so the Ask button is not offered.
        assert win.ask_button.isHidden()
    finally:
        win._autosave.stop()


def test_editing_a_note_saves_it_as_plain_text(app, tmp_path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.open_note("values")
        win.editor.setPlainText("Curiosity. Honesty.")
        win.save_now()
        assert load_note(tmp_path, "values").text == "Curiosity. Honesty."
    finally:
        win._autosave.stop()


def test_asking_is_refused_while_editing_a_note(app, tmp_path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.open_note("values")
        win.request_question()  # must not crash or write into the note
        assert load_note(tmp_path, "values").text == "Curiosity."
    finally:
        win._autosave.stop()


def test_standing_context_gathers_every_note(app, tmp_path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    save_note(tmp_path, Note("goal", "Goal", "Ship it."))
    save_note(tmp_path, Note("empty", "Empty", "   "))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        ctx = win.standing_context()
        assert "Core values: Curiosity." in ctx
        assert "Goal: Ship it." in ctx
        assert "Empty" not in ctx  # blank notes contribute nothing
    finally:
        win._autosave.stop()


def test_search_filters_the_sidebar(app, tmp_path):
    from journal.store import WRITING as W

    save(Page(day=_date(2026, 9, 1), model="m", prompt_version="v1",
              blocks=[Block(W, "the deadline slipped")]), tmp_path)
    save_note(tmp_path, Note("values", "Core values", "nothing relevant"))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.search_box.setText("deadline")
        keys = [d for d, _ in _sidebar_entries(win)]
        assert (PAGE, "2026-09-01") in keys
        assert (NOTE, "values") not in keys
    finally:
        win._autosave.stop()


def test_clearing_search_restores_the_full_sidebar(app, tmp_path):
    save_note(tmp_path, Note("values", "Core values", "Curiosity."))
    win = Window(model_path="model://none", journal_dir=tmp_path, day=DAY)
    try:
        win.search_box.setText("zzzz")
        assert (NOTE, "values") not in [d for d, _ in _sidebar_entries(win)]
        win.search_box.setText("")
        assert (NOTE, "values") in [d for d, _ in _sidebar_entries(win)]
    finally:
        win._autosave.stop()
