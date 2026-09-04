"""Where the panel was last put.

Small and forgiving on purpose: a settings file is not worth an error dialog,
so anything unreadable falls back to the default rather than failing to start.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from journal.geometry import EDGES

FILENAME = "panel.json"


@dataclass
class PanelSettings:
    edge: str = "right"
    screen: int = 0


def _path(directory: Path) -> Path:
    return directory / FILENAME


def load_settings(directory: Path) -> PanelSettings:
    path = _path(directory)
    if not path.exists():
        return PanelSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return PanelSettings()
    if not isinstance(raw, dict):
        return PanelSettings()
    edge = raw.get("edge")
    screen = raw.get("screen")
    return PanelSettings(
        edge=edge if edge in EDGES else "right",
        screen=screen if isinstance(screen, int) and screen >= 0 else 0,
    )


def save_settings(directory: Path, settings: PanelSettings) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = _path(directory)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return path


def resolve_screen(settings: PanelSettings, screen_count: int) -> int:
    """The screen to actually use -- primary if the remembered one is gone."""
    if settings.screen < screen_count:
        return settings.screen
    return 0
