"""Where the panel sits on screen.

Kept free of Qt so it can be tested against a made-up monitor. Screen
rectangles carry their origin: on a multi-monitor desktop the second screen
starts at x=1920, not x=0, and a panel that assumes otherwise opens on the
wrong display.
"""
from __future__ import annotations

TAB = 6  # visible width when resting
WIDTH = 320  # visible width when slid out
FRACTION = 0.6  # share of the screen's height the panel occupies

EDGES = ("left", "right")


def _vertical(screen: tuple[int, int, int, int]) -> tuple[int, int]:
    _, top, _, height = screen
    tall = int(height * FRACTION)
    return top + (height - tall) // 2, tall


def _rect(
    screen: tuple[int, int, int, int], edge: str, width: int
) -> tuple[int, int, int, int]:
    if edge not in EDGES:
        raise ValueError(f"edge must be one of {EDGES}, got {edge!r}")
    left, _, screen_width, _ = screen
    top, height = _vertical(screen)
    x = left if edge == "left" else left + screen_width - width
    return x, top, width, height


def collapsed_rect(
    screen: tuple[int, int, int, int], edge: str
) -> tuple[int, int, int, int]:
    """The resting strip: a sliver at the edge, same height as expanded."""
    return _rect(screen, edge, TAB)


def expanded_rect(
    screen: tuple[int, int, int, int], edge: str
) -> tuple[int, int, int, int]:
    """The slid-out panel."""
    return _rect(screen, edge, WIDTH)
