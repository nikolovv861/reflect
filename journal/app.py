"""Entry point: the journey once, the journal after.

    reflect                     # first launch: the journey; later: the journal
    REFLECT_JOURNEY=1 reflect   # the journey again (a demo, or a new year)
    REFLECT_JOURNEY=0 reflect   # straight to the journal
    REFLECT_JOURNAL_DIR=~/Documents/journal-demo reflect   # another journal
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from journal.journey import Journey, journey_done
from journal.ui import JOURNAL_DIR, Window


def journal_dir_from_env() -> Path:
    override = os.environ.get("REFLECT_JOURNAL_DIR", "").strip()
    return Path(override).expanduser() if override else JOURNAL_DIR


def wants_journey(journal_dir: Path) -> bool:
    flag = os.environ.get("REFLECT_JOURNEY", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return not journey_done(journal_dir)


def main() -> int:
    app = QApplication(sys.argv)
    journal_dir = journal_dir_from_env()
    holder: dict[str, object] = {}

    def open_journal() -> None:
        window = Window(journal_dir=journal_dir)
        holder["window"] = window
        window.show()
        journey = holder.get("journey")
        if journey is not None:
            journey.close()

    if wants_journey(journal_dir):
        journey = Journey(journal_dir)
        holder["journey"] = journey
        journey.open_journal.connect(open_journal)
        journey.show()
        # REFLECT_FASTFORWARD=1: a demo of the ending -- linger on the threshold
        # for a moment, then read a finished session from disk into the report.
        if os.environ.get("REFLECT_FASTFORWARD", "").strip() in ("1", "true", "yes"):
            from PySide6.QtCore import QTimer

            QTimer.singleShot(2500, journey.fast_forward)
    else:
        open_journal()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
