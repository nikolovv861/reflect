# Edge Capture Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A thin always-on-top panel at the screen edge that slides out on hover, captures a timestamped thought into today's journal page, and opens the full journal window on click.

**Architecture:** One process. `reflect-panel` becomes the entry point and creates the panel; the journal `Window` is constructed lazily on click and destroyed on close, which releases the model. Captures are appended to today's page as `[HH:MM] ` prefixed lines — a boundary that survives `parse()`, which merges consecutive writing lines into one block.

**Tech Stack:** Python 3.10+, PySide6 (Qt), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-edge-panel-design.md`

## Global Constraints

- Windows only. Do not add Linux/macOS branches.
- Python 3.10+ syntax. `from __future__ import annotations` at the top of every module.
- No new runtime dependencies. `nobodywho` and `PySide6` only.
- The journal file format must not change. `render()` and `parse()` in `journal/store.py` are not to be modified.
- Pages written before this change must load without migration.
- Never enable autostart by default.
- Tests that need Qt start with `pytest.importorskip("PySide6")` and use the module-scoped `app` fixture pattern from `tests/test_ui_page.py`.
- Run the full suite with `pytest -q` from the repo root. It must stay green.

**Deliberate narrowing from the spec:** the spec says geometry is computed for "each of the four edges". This plan implements **left and right only**. A 320px-tall band across the top or bottom of the screen is a different widget, and nothing in the design needs it. Task 2 covers left/right; the spec line should be corrected to match.

---

### Task 1: Capture storage

**Files:**
- Modify: `journal/store.py` (append after `open_day`, before `practice_day`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Page`, `Block`, `WRITING`, `open_day`, `save`, `path_for` from `journal.store`
- Produces:
  - `Entry(at: time | None, text: str)` dataclass
  - `entries(page: Page) -> list[Entry]`
  - `append_capture(directory: Path, text: str, at: time | None = None, day: Date | None = None, model: str = "unknown", prompt_version: str = "unknown") -> Page`

`model` and `prompt_version` default to `"unknown"` because the panel does not know them and does not load a model. `open_day()` overwrites both fields when the journal window later opens the page, so the placeholder never survives a real session.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py`:

```python
from datetime import time

from journal.store import Entry, append_capture, entries


def test_capture_writes_a_prefixed_line(tmp_path):
    page = append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    assert page.blocks == [Block(WRITING, "[09:14] call the bank")]
    assert "[09:14] call the bank" in path_for(tmp_path, date(2026, 9, 4)).read_text(encoding="utf-8")


def test_two_captures_share_one_block_but_stay_separate_entries(tmp_path):
    append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    page = append_capture(tmp_path, "annoyed at standup", at=time(11, 2), day=date(2026, 9, 4))
    assert len(page.blocks) == 1
    assert entries(page) == [
        Entry(time(9, 14), "call the bank"),
        Entry(time(11, 2), "annoyed at standup"),
    ]


def test_capture_survives_a_save_and_reload(tmp_path):
    append_capture(tmp_path, "call the bank", at=time(9, 14), day=date(2026, 9, 4))
    reloaded = load(path_for(tmp_path, date(2026, 9, 4)))
    assert entries(reloaded) == [Entry(time(9, 14), "call the bank")]


def test_a_multi_line_capture_stays_one_entry(tmp_path):
    page = append_capture(
        tmp_path, "annoyed at standup\nagain", at=time(11, 2), day=date(2026, 9, 4)
    )
    assert page.blocks[0].text == "[11:02] annoyed at standup\n        again"
    assert entries(page) == [Entry(time(11, 2), "annoyed at standup\nagain")]


def test_a_capture_after_a_question_starts_a_new_block(tmp_path):
    append_capture(tmp_path, "first", at=time(9, 0), day=date(2026, 9, 4))
    page = load(path_for(tmp_path, date(2026, 9, 4)))
    page.blocks.append(Block(QUESTION, "What happened?"))
    save(page, tmp_path)
    page = append_capture(tmp_path, "second", at=time(10, 0), day=date(2026, 9, 4))
    assert [b.kind for b in page.blocks] == [WRITING, QUESTION, WRITING]


def test_entries_reads_a_page_written_before_prefixes_existed():
    page = Page(day=date(2026, 9, 3), model="m", prompt_version="p")
    page.blocks = [Block(WRITING, "Long stretch of writing.")]
    assert entries(page) == [Entry(None, "Long stretch of writing.")]


def test_entries_ignores_questions():
    page = Page(day=date(2026, 9, 3), model="m", prompt_version="p")
    page.blocks = [Block(QUESTION, "What happened?")]
    assert entries(page) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_store.py -q -k "capture or entries"`
Expected: FAIL with `ImportError: cannot import name 'Entry' from 'journal.store'`

- [ ] **Step 3: Write the implementation**

Add `import re` and `from datetime import time as Time` to the imports at the top of `journal/store.py`, then insert after `open_day`:

```python
# --- captures --------------------------------------------------------------

CAPTURE = re.compile(r"^\[(\d{2}):(\d{2})\] ?(.*)$")
INDENT = " " * 8  # len("[HH:MM] "), so continuation lines align under the text


@dataclass
class Entry:
    """One thing you typed into the panel, as the panel shows it back."""

    at: Time | None
    text: str


def entries(page: Page) -> list[Entry]:
    """Split the page's writing back into the captures it was typed as.

    `parse()` merges consecutive writing lines into a single block, so the
    `[HH:MM]` prefix -- not the block boundary -- is what separates one
    capture from the next. Text with no prefix (any page written before
    captures existed) comes back as a single untimed entry per block.
    """
    found: list[Entry] = []
    for block in page.blocks:
        if block.kind != WRITING:
            continue
        current: Entry | None = None
        for line in block.text.splitlines():
            match = CAPTURE.match(line)
            if match:
                hour, minute, rest = match.groups()
                current = Entry(Time(int(hour), int(minute)), rest)
                found.append(current)
            elif current is not None and line.startswith(INDENT):
                current.text += "\n" + line[len(INDENT) :]
            elif current is not None:
                current.text += "\n" + line
            elif line.strip():
                current = Entry(None, line)
                found.append(current)
    return [Entry(e.at, e.text.strip()) for e in found if e.text.strip()]


def append_capture(
    directory: Path,
    text: str,
    at: Time | None = None,
    day: Date | None = None,
    model: str = "unknown",
    prompt_version: str = "unknown",
) -> Page:
    """Append one timestamped thought to the day's page and save it.

    `model` and `prompt_version` are placeholders: the panel never loads a
    model, and `open_day()` overwrites both when the journal opens the page.
    """
    day = day or datetime.now().date()
    at = at or datetime.now().time()
    page = open_day(directory, model, prompt_version, day)

    lines = text.strip().splitlines() or [""]
    rendered = f"[{at.hour:02d}:{at.minute:02d}] {lines[0]}"
    for line in lines[1:]:
        rendered += f"\n{INDENT}{line}"

    if page.blocks and page.blocks[-1].kind == WRITING:
        page.blocks[-1].text += "\n" + rendered
    else:
        page.blocks.append(Block(WRITING, rendered))

    save(page, directory)
    return page
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_store.py -q`
Expected: PASS, all pre-existing store tests still green.

- [ ] **Step 5: Commit**

```bash
git add journal/store.py tests/test_store.py
git commit -m "feat: timestamped captures that survive a reload"
```

---

### Task 2: Panel geometry

**Files:**
- Create: `journal/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `TAB = 6`, `WIDTH = 320`, `FRACTION = 0.6`
  - `collapsed_rect(screen: tuple[int, int, int, int], edge: str) -> tuple[int, int, int, int]`
  - `expanded_rect(screen: tuple[int, int, int, int], edge: str) -> tuple[int, int, int, int]`

Both take and return `(x, y, width, height)`. `screen` is the available geometry of the monitor, which may have a non-zero origin on a multi-monitor desktop — never assume `(0, 0)`. `edge` is `"left"` or `"right"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_geometry.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_geometry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'journal.geometry'`

- [ ] **Step 3: Write the implementation**

Create `journal/geometry.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_geometry.py -q`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add journal/geometry.py tests/test_geometry.py
git commit -m "feat: panel geometry for the left and right screen edges"
```

---

### Task 3: Panel settings

**Files:**
- Create: `journal/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `journal.geometry.EDGES`
- Produces:
  - `PanelSettings(edge: str = "right", screen: int = 0)` dataclass
  - `load_settings(directory: Path) -> PanelSettings`
  - `save_settings(directory: Path, settings: PanelSettings) -> Path`
  - `resolve_screen(settings: PanelSettings, screen_count: int) -> int`

`resolve_screen` is the undocking guard: a remembered screen index that no longer exists falls back to `0` rather than opening the panel off-screen.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_settings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'journal.settings'`

- [ ] **Step 3: Write the implementation**

Create `journal/settings.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_settings.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add journal/settings.py tests/test_settings.py
git commit -m "feat: remember the panel's edge and screen"
```

---

### Task 4: The panel widget and capture behaviour

**Files:**
- Create: `journal/panel.py`
- Test: `tests/test_panel.py`

**Interfaces:**
- Consumes: `append_capture`, `entries`, `open_day` from `journal.store`; `load_settings`, `resolve_screen` from `journal.settings`; `collapsed_rect`, `expanded_rect` from `journal.geometry`; `JOURNAL_DIR`, `PAPER`, `INK` from `journal.ui`
- Produces:
  - `Panel(journal_dir: Path | None = None, day: Date | None = None)` — a `QWidget`
  - `Panel.capture_box: QTextEdit`
  - `Panel.list: QListWidget`
  - `Panel.commit() -> None` — save whatever is in the box
  - `Panel.refresh() -> None` — reload the day's entries into the list

This task builds the widget and its capture behaviour only. Window flags, sliding and hover come in Task 5, so everything here is testable with the offscreen Qt platform.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_panel.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_panel.py -q`
(On Windows PowerShell: `$env:QT_QPA_PLATFORM="offscreen"; pytest tests/test_panel.py -q`)
Expected: FAIL with `ModuleNotFoundError: No module named 'journal.panel'`

- [ ] **Step 3: Write the implementation**

Create `journal/panel.py`:

```python
"""The edge panel: a place to put a thought without opening anything.

The panel deliberately does one thing. It does not show your standing notes,
it has no to-dos, and it never loads a model -- it reads and appends plain
text. Everything else lives in the journal window.
"""
from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.store import append_capture, entries, open_day
from journal.ui import INK, JOURNAL_DIR, PAPER


class CaptureBox(QTextEdit):
    """Enter saves, Shift+Enter makes a new line."""

    def __init__(self, on_commit):
        super().__init__()
        self._on_commit = on_commit
        self.setPlaceholderText("a thought…")
        self.setFixedHeight(64)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if enter and not (event.modifiers() & Qt.ShiftModifier):
            self._on_commit()
            return
        super().keyPressEvent(event)


class Panel(QWidget):
    def __init__(self, journal_dir: Path | None = None, day: Date | None = None):
        super().__init__()
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.day = day or datetime.now().date()

        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)

        self.capture_box = CaptureBox(self.commit)
        self.open_button = QPushButton("open journal  ›")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.capture_box)
        layout.addWidget(self.open_button)

        self.setStyleSheet(
            f"QWidget {{ background:{PAPER}; color:{INK}; font-size:12px; }}"
            f"QListWidget {{ border:none; }}"
            f"QTextEdit {{ border:1px solid #e0dbd0; border-radius:5px; padding:5px; }}"
            f"QPushButton {{ border:none; padding:6px; text-align:left; }}"
        )

        self.refresh()

    def commit(self) -> None:
        text = self.capture_box.toPlainText().strip()
        if not text:
            return
        append_capture(self.journal_dir, text, day=self.day)
        self.capture_box.clear()
        self.refresh()

    def refresh(self) -> None:
        page = open_day(self.journal_dir, "unknown", "unknown", self.day)
        self.list.clear()
        for entry in entries(page):
            stamp = f"{entry.at.hour:02d}:{entry.at.minute:02d}  " if entry.at else ""
            self.list.addItem(QListWidgetItem(f"{stamp}{entry.text}"))
        self.list.scrollToBottom()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_panel.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add journal/panel.py tests/test_panel.py
git commit -m "feat: the capture panel widget"
```

---

### Task 5: Sliding, hover and always-on-top

**Files:**
- Modify: `journal/panel.py`

**Interfaces:**
- Consumes: `Panel` from Task 4, `collapsed_rect`/`expanded_rect` from Task 2, `load_settings`/`resolve_screen` from Task 3
- Produces:
  - `PanelWindow(journal_dir: Path | None = None, day: Date | None = None)` — the frameless always-on-top window that contains a `Panel`
  - `PanelWindow.panel: Panel`
  - `PanelWindow.expand() -> None` / `PanelWindow.collapse() -> None`

There are no automated tests for this task. Hover events, animation timing and always-on-top behaviour can only be mocked, and a mocked hover event tests the mock. The verification is the manual checklist in Step 3.

- [ ] **Step 1: Write the implementation**

Add to the imports at the top of `journal/panel.py`:

```python
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QTimer
from PySide6.QtGui import QGuiApplication

from journal.geometry import collapsed_rect, expanded_rect
from journal.settings import load_settings, resolve_screen
```

Then append to the end of the file:

```python
SLIDE_MS = 150
RETRACT_DELAY_MS = 400


class PanelWindow(QWidget):
    """The panel's home: frameless, always on top, resting at a screen edge."""

    def __init__(self, journal_dir: Path | None = None, day: Date | None = None):
        super().__init__()
        self.journal_dir = journal_dir or JOURNAL_DIR
        self.settings = load_settings(self.journal_dir)

        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        # Sliding out must never steal focus from whatever is being typed in.
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.panel = Panel(journal_dir=self.journal_dir, day=day)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.panel)

        self.setMouseTracking(True)
        self._expanded = False
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(SLIDE_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        # A pointer crossing the edge on its way elsewhere should not make the
        # panel flap open and shut.
        self._retract = QTimer(self)
        self._retract.setSingleShot(True)
        self._retract.setInterval(RETRACT_DELAY_MS)
        self._retract.timeout.connect(self.collapse)

        self.setGeometry(QRect(*self._rect(expanded=False)))

    # --- placement ------------------------------------------------------

    def _screen_rect(self) -> tuple[int, int, int, int]:
        screens = QGuiApplication.screens()
        index = resolve_screen(self.settings, len(screens))
        available = screens[index].availableGeometry()
        return (
            available.x(),
            available.y(),
            available.width(),
            available.height(),
        )

    def _rect(self, expanded: bool) -> tuple[int, int, int, int]:
        screen = self._screen_rect()
        edge = self.settings.edge
        return expanded_rect(screen, edge) if expanded else collapsed_rect(screen, edge)

    def _slide_to(self, expanded: bool) -> None:
        self._expanded = expanded
        self._animation.stop()
        self._animation.setStartValue(self.geometry())
        self._animation.setEndValue(QRect(*self._rect(expanded)))
        self._animation.start()

    def expand(self) -> None:
        self._retract.stop()
        if not self._expanded:
            self._slide_to(True)

    def collapse(self) -> None:
        if self._expanded and not self.panel.capture_box.hasFocus():
            self._slide_to(False)

    # --- hover ----------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._retract.start()
        super().leaveEvent(event)
```

- [ ] **Step 2: Add a temporary launcher to try it**

Append to `journal/panel.py`:

```python
def main() -> int:
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = PanelWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Verify by hand**

Run: `python -m journal.panel`

Check each of these and note anything that fails:

1. A thin strip appears at the right edge. It is not in the taskbar and not in Alt-Tab.
2. Moving the mouse onto the strip slides the panel out.
3. Moving the mouse away retracts it after a short pause, not instantly.
4. Moving the mouse quickly past the edge does **not** make it flap.
5. While typing in another app, the panel sliding out does **not** take your keystrokes.
6. Clicking into the capture box gives it focus; typing works; Enter saves and the entry appears in the list; Shift+Enter makes a new line.
7. While the capture box has focus, moving the mouse away does not retract the panel mid-sentence.
8. The panel stays above a maximised window.

- [ ] **Step 4: Commit**

```bash
git add journal/panel.py
git commit -m "feat: slide the panel out on hover"
```

---

### Task 6: Journal handoff

**Files:**
- Modify: `journal/panel.py`
- Test: `tests/test_panel.py`

`journal/ui.py` is **not** modified. The spec's file table anticipated a change
there to make `Window` closable without ending the process; it turns out not to
be needed, because `app.setQuitOnLastWindowClosed(False)` in the panel's `main`
(Task 7) achieves it from the outside. `reflect` keeps working unchanged.

**Interfaces:**
- Consumes: `Window` from `journal.ui`
- Produces: `PanelWindow.open_journal() -> None`, `PanelWindow.journal: Window | None`

The journal window is built on first click and destroyed on close, which drops the `Engine` it owns and releases the model. `app.setQuitOnLastWindowClosed(False)` is what keeps the process alive when the journal closes but the panel is still resting.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_panel.py`:

```python
from journal.panel import PanelWindow  # noqa: E402


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_panel.py -q -k journal`
Expected: FAIL with `AttributeError: 'PanelWindow' object has no attribute 'journal'`

- [ ] **Step 3: Write the implementation**

In `journal/panel.py`, add to the imports:

```python
from journal.ui import INK, JOURNAL_DIR, PAPER, Window
```

(replacing the existing `from journal.ui import INK, JOURNAL_DIR, PAPER`)

In `PanelWindow.__init__`, after `self.panel = Panel(...)`, add:

```python
        self.day = day
        self.journal: Window | None = None
        self.panel.open_button.clicked.connect(self.open_journal)
```

Then add these methods to `PanelWindow`:

```python
    def open_journal(self) -> None:
        """Build the journal window, or raise the one already open.

        The model is not loaded here -- `Window.ensure_engine()` still defers
        that to the first question, so opening the journal stays cheap.
        """
        if self.journal is None:
            self.journal = Window(journal_dir=self.journal_dir, day=self.day)
            self.journal.setAttribute(Qt.WA_DeleteOnClose)
            self.journal.destroyed.connect(self._journal_closed)
        self.journal.show()
        self.journal.raise_()
        self.journal.activateWindow()
        self.collapse()

    def _journal_closed(self) -> None:
        """Forget the window, so its Engine -- and the model -- can be freed."""
        self.journal = None
        self.panel.refresh()
```

In `PanelWindow.collapse`, the `self.panel.capture_box.hasFocus()` guard already prevents retracting mid-sentence; no change needed.

Read `Window.closeEvent` (`journal/ui.py`, around line 713) and confirm it only
saves. If it calls `QApplication.quit()`, `sys.exit()`, or similar, remove that
call — the process must outlive the journal window. If it only saves, change
nothing in `ui.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest -q`
Expected: PASS, whole suite green.

- [ ] **Step 5: Verify by hand**

Run: `python -m journal.panel`

1. Type a capture, press Enter, then click *open journal*.
2. The journal opens on today with the capture already on the page.
3. Click *Ask me something* — the model loads and a question appears.
4. Close the journal window. The panel is still at the edge and the process is still running.
5. Click *open journal* again. It reopens.

- [ ] **Step 6: Commit**

```bash
git add journal/panel.py tests/test_panel.py
git commit -m "feat: open the journal from the panel"
```

---

### Task 7: Autostart, entry point, and docs

**Files:**
- Create: `journal/autostart.py`
- Modify: `journal/panel.py` (`main`)
- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/test_autostart.py`

**Interfaces:**
- Produces:
  - `RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"`, `VALUE_NAME = "reflect-panel"`
  - `command() -> str` — the command Windows should run at login
  - `enable() -> None`, `disable() -> None`, `is_enabled() -> bool`

`command()` is pure and therefore testable. The three registry functions are not tested — mocking `winreg` tests the mock. They are verified by hand in Step 5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_autostart.py`:

```python
"""Only the part that does not touch the registry. Mocking winreg would test
the mock, so enable/disable are verified by hand.
"""
from __future__ import annotations

import sys

from journal.autostart import command


def test_the_command_runs_this_interpreter():
    assert sys.executable in command()


def test_the_command_launches_the_panel_module():
    assert "journal.panel" in command()


def test_the_command_is_quoted_against_spaces_in_the_path():
    assert command().startswith('"')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_autostart.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'journal.autostart'`

- [ ] **Step 3: Write the implementation**

Create `journal/autostart.py`:

```python
"""Start the panel with Windows. Opt-in, never on by default.

Writes one value under the current user's Run key. Nothing is installed
system-wide and nothing needs administrator rights.
"""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "reflect-panel"


def command() -> str:
    """The command Windows runs at login.

    Quoted because `sys.executable` routinely lives under a path with a space
    in it, and an unquoted Run value silently does nothing.
    """
    return f'"{sys.executable}" -m journal.panel'


def _key(access):  # noqa: ANN001
    import winreg

    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def enable() -> None:
    import winreg

    with _key(winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())


def disable() -> None:
    import winreg

    try:
        with _key(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    import winreg

    try:
        with _key(winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True
```

- [ ] **Step 4: Wire up the CLI and the entry point**

Replace `main()` at the end of `journal/panel.py` with:

```python
def main() -> int:
    import argparse
    import sys

    from PySide6.QtWidgets import QApplication

    from journal import autostart

    parser = argparse.ArgumentParser(prog="reflect-panel")
    parser.add_argument(
        "--autostart",
        choices=("on", "off", "status"),
        help="start the panel when Windows starts",
    )
    args = parser.parse_args()

    if args.autostart:
        if args.autostart == "on":
            autostart.enable()
        elif args.autostart == "off":
            autostart.disable()
        print("autostart:", "on" if autostart.is_enabled() else "off")
        return 0

    app = QApplication(sys.argv)
    # The journal window closing must not end the process -- the panel is
    # still resting at the edge.
    app.setQuitOnLastWindowClosed(False)
    window = PanelWindow()
    window.show()
    return app.exec()
```

Add to `pyproject.toml` under `[project.scripts]`:

```toml
[project.scripts]
reflect = "journal.ui:main"
reflect-panel = "journal.panel:main"
```

- [ ] **Step 5: Run the tests and verify by hand**

Run: `pip install -e . && pytest -q`
Expected: PASS, whole suite green.

Then:

1. `reflect-panel --autostart status` → prints `autostart: off`
2. `reflect-panel --autostart on` → prints `autostart: on`
3. Check `regedit` under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` for a `reflect-panel` value containing a quoted interpreter path.
4. `reflect-panel --autostart off` → prints `autostart: off`, value gone.
5. `reflect-panel` with no arguments → the panel appears at the edge.

- [ ] **Step 6: Document it**

Add to `README.md` after the Install section (the block below is the literal
markdown to paste, fences and all):

~~~~markdown
## The edge panel

`reflect-panel` puts a thin strip at the right edge of the screen. Touch it
with the mouse and it slides out; type a thought and press Enter and it is
saved into today's page with the time. Shift+Enter makes a new line.

It never loads the model, so it costs almost nothing to leave running. Click
*open journal* and the full window opens on today with your captures already
on the page, ready for a question.

To start it with Windows:

```bash
reflect-panel --autostart on    # and --autostart off to undo
```

The panel captures thoughts only. Core values and goals live in the journal
window, and there are deliberately no to-dos — a to-do has state and a thought
does not.
~~~~

- [ ] **Step 7: Commit**

```bash
git add journal/autostart.py journal/panel.py tests/test_autostart.py pyproject.toml README.md
git commit -m "feat: reflect-panel entry point with opt-in autostart"
```
