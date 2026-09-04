"""Where the panel sits. Pure arithmetic, so it is the part worth testing --
the slide animation and hover timing are verified by hand.
"""
from __future__ import annotations

import pytest

from journal.geometry import TAB, WIDTH, collapsed_rect, expanded_rect

SCREEN = (0, 0, 1920, 1080)
SECOND = (1920, 0, 2560, 1440)  # a monitor to the right of the primary


def test_collapsed_on_the_right_is_a_thin_strip_at_the_edge():
    x, y, w, h = collapsed_rect(SCREEN, "right")
    assert w == TAB
    assert x + w == 1920


def test_expanded_on_the_right_reaches_the_same_edge():
    x, y, w, h = expanded_rect(SCREEN, "right")
    assert w == WIDTH
    assert x + w == 1920


def test_collapsed_on_the_left_sits_at_x_zero():
    x, _, w, _ = collapsed_rect(SCREEN, "left")
    assert (x, w) == (0, TAB)


def test_expanded_on_the_left_sits_at_x_zero():
    assert expanded_rect(SCREEN, "left")[0] == 0


def test_collapsing_does_not_move_the_panel_vertically():
    assert collapsed_rect(SCREEN, "right")[1] == expanded_rect(SCREEN, "right")[1]
    assert collapsed_rect(SCREEN, "right")[3] == expanded_rect(SCREEN, "right")[3]


def test_the_panel_is_vertically_centred():
    _, y, _, h = expanded_rect(SCREEN, "right")
    assert y == (1080 - h) // 2


def test_a_second_monitor_origin_is_respected():
    x, y, w, _ = expanded_rect(SECOND, "right")
    assert x + w == 1920 + 2560
    assert y > 0


def test_an_unknown_edge_is_rejected():
    with pytest.raises(ValueError):
        expanded_rect(SCREEN, "top")
