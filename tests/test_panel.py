"""The panel's one job: what you type ends up in today's page, and what is
already in today's page is visible when you look at it.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

pytest.importorskip("PySide6")

import shiboken6  # noqa: E402
from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from journal.geometry import collapsed_rect  # noqa: E402
from journal.settings import resolve_screen  # noqa: E402

from journal import panel as panel_module  # noqa: E402
from journal.panel import Panel, PanelWindow  # noqa: E402
from journal.store import append_capture, entries, load, path_for  # noqa: E402

DAY = date(2026, 9, 4)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app, tmp_path):
    return Panel(journal_dir=tmp_path, day=DAY)


def test_a_fresh_panel_shows_nothing(panel):
    assert panel.list.count() == 0


def test_committing_writes_to_todays_page(panel, tmp_path):
    panel.capture_box.setPlainText("annoyed at the standup")
    panel.commit()
    page = load(path_for(tmp_path, DAY))
    assert [e.text for e in entries(page)] == ["annoyed at the standup"]


def test_committing_clears_the_box(panel):
    panel.capture_box.setPlainText("something")
    panel.commit()
    assert panel.capture_box.toPlainText() == ""


def test_committing_shows_the_entry_in_the_list(panel):
    panel.capture_box.setPlainText("something")
    panel.commit()
    assert panel.list.count() == 1
    assert "something" in panel.list.item(0).text()


def test_an_empty_box_is_not_committed(panel, tmp_path):
    panel.capture_box.setPlainText("   ")
    panel.commit()
    assert not path_for(tmp_path, DAY).exists()


def test_the_panel_shows_what_was_already_written_today(app, tmp_path):
    append_capture(tmp_path, "written earlier", day=DAY)
    panel = Panel(journal_dir=tmp_path, day=DAY)
    assert panel.list.count() == 1
    assert "written earlier" in panel.list.item(0).text()


def test_refresh_picks_up_a_change_made_elsewhere(panel, tmp_path):
    append_capture(tmp_path, "from the journal window", day=DAY)
    panel.refresh()
    assert panel.list.count() == 1


@pytest.fixture
def panel_window(app, tmp_path):
    win = PanelWindow(journal_dir=tmp_path, day=DAY)
    yield win
    if win.journal is not None:
        win.journal._autosave.stop()


def test_no_journal_window_until_asked(panel_window):
    assert panel_window.journal is None


def test_opening_the_journal_builds_it_once(panel_window):
    panel_window.open_journal()
    first = panel_window.journal
    assert first is not None
    panel_window.open_journal()
    assert panel_window.journal is first


def test_the_journal_opens_on_the_day_the_panel_is_showing(panel_window):
    panel_window.open_journal()
    assert panel_window.journal.page.day == DAY


def test_captures_are_already_on_the_page_the_journal_opens(panel_window, tmp_path):
    panel_window.panel.capture_box.setPlainText("annoyed at the standup")
    panel_window.panel.commit()
    panel_window.open_journal()
    text = "\n".join(b.text for b in panel_window.journal.page.blocks)
    assert "annoyed at the standup" in text


# The destroyed signal is connected through a weakref, not a plain bound
# method (`self.journal.destroyed.connect(self._journal_closed)`). A plain
# bound method makes the Window hold an indirect strong reference back to
# the PanelWindow (via the Qt connection), forming a PanelWindow<->Window
# reference cycle. With no event loop running and the journal never closed,
# earlier test runs hit this cycle and crashed with a Windows access
# violation during garbage collection. This test drives the real close path
# (WA_DeleteOnClose + a pumped event loop) so it fails if that weakref
# indirection is ever "simplified" away.
def test_the_journal_can_be_closed_and_reopened(panel_window):
    panel_window.open_journal()
    assert panel_window.journal is not None
    panel_window.journal._autosave.stop()
    panel_window.journal.close()
    QApplication.processEvents()
    QApplication.processEvents()
    assert panel_window.journal is None

    panel_window.open_journal()
    assert panel_window.journal is not None
    assert panel_window.journal.page.day == DAY


# --- the journal must not overwrite what the panel appended ---------------
#
# `Window.save_now()` writes the WHOLE page from the editor's in-memory
# blocks. Any capture the panel appended while that window was open is not in
# those blocks, so the next autosave (or closeEvent) silently destroys it.
def test_a_capture_survives_the_open_journals_next_save(app, tmp_path):
    win = PanelWindow(journal_dir=tmp_path, day=DAY)
    win.open_journal()
    win.journal._autosave.stop()
    try:
        win.panel.capture_box.setPlainText("annoyed at the standup")
        win.panel.commit()
        win.journal.save_now()

        on_disk = "\n".join(b.text for b in load(path_for(tmp_path, DAY)).blocks)
        assert "annoyed at the standup" in on_disk

        in_window = "\n".join(b.text for b in win.journal.page.blocks)
        assert "annoyed at the standup" in in_window
    finally:
        win.journal._autosave.stop()


def test_the_journal_keeps_its_own_writing_when_a_capture_arrives(app, tmp_path):
    win = PanelWindow(journal_dir=tmp_path, day=DAY)
    win.open_journal()
    win.journal._autosave.stop()
    try:
        win.journal.editor.setPlainText("typed in the journal window")
        win.panel.capture_box.setPlainText("typed in the panel")
        win.panel.commit()

        on_disk = "\n".join(b.text for b in load(path_for(tmp_path, DAY)).blocks)
        assert "typed in the journal window" in on_disk
        assert "typed in the panel" in on_disk
    finally:
        win.journal._autosave.stop()


# --- the panel must follow the clock, not its construction date -----------


class _Clock:
    """Stands in for `datetime` so a test can move the day forward."""

    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


def test_the_panel_follows_the_clock_past_midnight(app, tmp_path, monkeypatch):
    clock = _Clock(datetime(2026, 9, 4, 23, 59))
    monkeypatch.setattr(panel_module, "datetime", clock)

    p = Panel(journal_dir=tmp_path)
    p.capture_box.setPlainText("before midnight")
    p.commit()

    clock.value = datetime(2026, 9, 5, 0, 1)
    p.capture_box.setPlainText("after midnight")
    p.commit()

    yesterday = load(path_for(tmp_path, date(2026, 9, 4)))
    assert [e.text for e in entries(yesterday)] == ["before midnight"]
    today = load(path_for(tmp_path, date(2026, 9, 5)))
    assert [e.text for e in entries(today)] == ["after midnight"]


def test_the_panel_lists_the_new_days_captures_after_midnight(
    app, tmp_path, monkeypatch
):
    clock = _Clock(datetime(2026, 9, 4, 23, 59))
    monkeypatch.setattr(panel_module, "datetime", clock)

    p = Panel(journal_dir=tmp_path)
    p.capture_box.setPlainText("before midnight")
    p.commit()
    assert p.list.count() == 1

    clock.value = datetime(2026, 9, 5, 0, 1)
    p.refresh()
    assert p.list.count() == 0


def test_with_no_explicit_day_the_journal_opens_the_day_the_panel_writes_to(
    app, tmp_path, monkeypatch
):
    # A date that is deliberately not the real today, so this cannot pass by
    # both sides independently calling the same clock.
    clock = _Clock(datetime(2019, 3, 7, 10, 0))
    monkeypatch.setattr(panel_module, "datetime", clock)

    win = PanelWindow(journal_dir=tmp_path)
    win.panel.capture_box.setPlainText("a thought")
    win.panel.commit()
    win.open_journal()
    try:
        assert win.panel.day == date(2019, 3, 7)
        assert win.journal.page.day == date(2019, 3, 7)
        text = "\n".join(b.text for b in win.journal.page.blocks)
        assert "a thought" in text
    finally:
        win.journal._autosave.stop()


# --- teardown order: the journal outliving the panel's C++ side -----------
#
# The weakref in open_journal() proves the PANEL OBJECT is still alive in
# Python. It says nothing about whether Qt has already deleted the widgets
# underneath it, which is exactly what happens when the app quits with the
# journal still open: the panel's C++ side goes first, the journal's
# `destroyed` fires afterwards, and refreshing the list raises.
def test_the_journal_closing_after_the_panel_is_deleted_does_not_raise(app, tmp_path):
    win = PanelWindow(journal_dir=tmp_path, day=DAY)
    win.open_journal()
    win.journal._autosave.stop()
    shiboken6.delete(win.panel)

    win._journal_closed()  # must not raise RuntimeError

    assert win.journal is None


def test_a_capture_committed_after_the_journals_c_side_is_gone_does_not_raise(
    app, tmp_path
):
    win = PanelWindow(journal_dir=tmp_path, day=DAY)
    win.open_journal()
    win.journal._autosave.stop()
    shiboken6.delete(win.journal)

    win.panel.capture_box.setPlainText("still worth keeping")
    win.panel.commit()  # must not raise

    page = load(path_for(tmp_path, DAY))
    assert "still worth keeping" in "\n".join(b.text for b in page.blocks)


# --- there has to be a way out --------------------------------------------


def test_the_panel_offers_a_quit_action(panel_window):
    assert panel_window.quit_action in panel_window.actions()
    assert panel_window.quit_action.text() == "Quit"
    assert panel_window.contextMenuPolicy() == Qt.ActionsContextMenu


def test_quit_is_bound_to_ctrl_q(panel_window):
    assert panel_window.quit_action.shortcut() == QKeySequence("Ctrl+Q")


def test_triggering_quit_asks_the_application_to_quit(panel_window, monkeypatch):
    called = []

    class _App:
        @staticmethod
        def quit():
            called.append(True)

    monkeypatch.setattr(panel_module, "QApplication", _App)
    panel_window.quit_action.trigger()
    assert called == [True]


# --- the collapse guard ----------------------------------------------------
#
# collapse() declines while you are still typing or still pointing at the
# panel, and re-arms its own timer so it retries. Nothing else re-arms that
# single-shot timer, so a decline that did not re-arm would leave the panel
# stuck open forever.


def _expected_collapsed(win):
    screens = QGuiApplication.screens()
    available = screens[resolve_screen(win.settings, len(screens))].availableGeometry()
    screen = (
        available.x(),
        available.y(),
        available.width(),
        available.height(),
    )
    return QRect(*collapsed_rect(screen, win.settings.edge))


def test_collapse_declines_while_the_capture_box_has_focus(panel_window):
    panel_window._expanded = True
    panel_window.panel.capture_box.hasFocus = lambda: True
    panel_window.underMouse = lambda: False

    panel_window.collapse()

    assert panel_window._expanded is True
    assert panel_window._retract.isActive()


def test_collapse_declines_while_the_pointer_is_over_the_panel(panel_window):
    panel_window._expanded = True
    panel_window.panel.capture_box.hasFocus = lambda: False
    panel_window.underMouse = lambda: True

    panel_window.collapse()

    assert panel_window._expanded is True
    assert panel_window._retract.isActive()


def test_collapse_retracts_to_the_resting_strip_when_nothing_blocks_it(panel_window):
    panel_window._expanded = True
    panel_window.panel.capture_box.hasFocus = lambda: False
    panel_window.underMouse = lambda: False

    panel_window.collapse()

    assert panel_window._expanded is False
    assert panel_window._animation.endValue() == _expected_collapsed(panel_window)
