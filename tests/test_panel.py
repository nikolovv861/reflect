"""The panel's one job: what you type ends up in today's page, and what is
already in today's page is visible when you look at it.
"""
from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from journal.panel import Panel  # noqa: E402
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
