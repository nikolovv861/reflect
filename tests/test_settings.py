"""The panel remembers where it lives. Getting this wrong opens it off-screen
on a laptop that was undocked since last run, which looks exactly like a crash.
"""
from __future__ import annotations

from journal.settings import PanelSettings, load_settings, resolve_screen, save_settings


def test_defaults_to_the_right_edge_of_the_primary_screen(tmp_path):
    assert load_settings(tmp_path) == PanelSettings(edge="right", screen=0)


def test_settings_round_trip(tmp_path):
    save_settings(tmp_path, PanelSettings(edge="left", screen=1))
    assert load_settings(tmp_path) == PanelSettings(edge="left", screen=1)


def test_a_corrupt_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "panel.json").write_text("{not json", encoding="utf-8")
    assert load_settings(tmp_path) == PanelSettings()


def test_an_unknown_edge_falls_back_to_the_default(tmp_path):
    (tmp_path / "panel.json").write_text('{"edge": "top", "screen": 0}', encoding="utf-8")
    assert load_settings(tmp_path).edge == "right"


def test_a_missing_screen_falls_back_to_primary():
    assert resolve_screen(PanelSettings(edge="right", screen=2), screen_count=1) == 0


def test_a_present_screen_is_kept():
    assert resolve_screen(PanelSettings(edge="right", screen=1), screen_count=2) == 1
