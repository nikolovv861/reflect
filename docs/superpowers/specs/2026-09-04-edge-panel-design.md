# Edge panel — design

**Date:** 2026-09-04
**Status:** approved, not yet implemented

## The problem

reflect is a window you open. That makes it a place you go, and a place you go
is a place you stop going. The writing that matters most is the fragment you
have at 11:02 in the middle of something else — and by the time you have opened
an app, chosen a practice, and faced a blank page, the fragment is gone.

## What we are building

A narrow panel that lives on the edge of the screen all day. It rests as a
thin tab. Touch it with the mouse and it slides out; move away and it retracts.
You type a thought, press Enter, and it is saved into today's page. That is the
whole panel.

**Enter saves and clears; Shift+Enter inserts a newline.** A capture may be
several lines long — only the first carries the `[HH:MM]` prefix, and the
continuation lines are indented so the boundary still reads correctly on
reload.

The panel is the front door. Clicking through opens the journal window you
already have, with the day's captures already on the page, ready for
*Ask me something*.

## Scope

**In:**

- Edge panel: rest / slide out / retract, position remembered
- Capture: one line of thought, timestamped, appended to today's page
- Handoff: open the journal window on today, panel retracts
- Opt-in Windows autostart

**Out, deliberately:**

- **To-dos.** A to-do has state and a thought does not. Ticking, striking
  through, and rolling unfinished items to tomorrow is a second product. The
  panel captures thoughts only.
- **Standing notes on the panel.** `core-values` and `goal` stay in the journal
  window. The panel does one job so there is never a mode to be in the wrong
  one of.
- **Wikilinks, backlinks, embeddings.** Parked, with notes in the survey below.

## Architecture

One process. `reflect-panel` becomes the entry point; it creates the panel and
nothing else. The journal `Window` is constructed lazily the first time you
click through, and closing it drops the reference and sets `engine = None`,
which releases the model.

`reflect` stays as an entry point that opens the journal directly, so nothing
that works today stops working.

This was chosen over two separate processes. The motivating worry — that a
panel up all day would hold 2.5GB of model in RAM — does not apply, because
`ensure_engine()` already loads the model lazily on the first *Ask*, not at
startup. Two processes would have cost a second PyQt runtime in memory whenever
both were open, a `QFileSystemWatcher` to notice each other's writes, a
single-instance guard, and cross-process window raising on Windows — all to buy
isolation against a leak that would be a bug worth fixing rather than
designing around.

### Files

| File | Responsibility |
|---|---|
| `journal/panel.py` (new) | The edge window: geometry, slide, capture box, handoff |
| `journal/store.py` | Gains `append_capture()` and `entries()` |
| `journal/ui.py` | `Window` becomes closable without ending the process |
| `journal/autostart.py` (new) | Read/write the `HKCU` Run value |
| `pyproject.toml` | `reflect-panel` script |

## Capture and storage

Each capture is appended to today's page as a line prefixed `[HH:MM] `:

```markdown
---
date: 2026-09-04
...
---

[09:14] call the bank
[11:02] annoyed at the standup again
```

**Why a prefix rather than a new block type.** `parse()` merges consecutive
writing lines into a single block — blank lines do not separate them, because
a blank line is still not a blockquote. So two captures an hour apart come back
as one block on reload. The timestamp prefix is the boundary that survives the
round trip: the file format and `parse()` are untouched, and the panel splits a
writing block on the prefix to render its list.

**Backward compatibility.** Pages written before this change have no prefixes.
They load fine and render as a single entry. No migration.

**The model sees the timestamps.** This is intended. "You came back to this
three times between 9 and 11" is exactly the kind of pattern the app exists to
notice, and it cannot notice it if the times are stripped.

### New store functions

- `append_capture(directory, day, text, at) -> Page` — append one timestamped
  line to the day's page and save. Creates the page if today has none.
- `entries(page) -> list[Entry]` — split writing blocks on the `[HH:MM]`
  prefix into `Entry(at: time | None, text: str)`. Unprefixed text yields one
  entry with `at=None`.

## Panel mechanics

- **Window flags:** `Qt.Tool | Qt.FramelessWindowHint |
  Qt.WindowStaysOnTopHint`. `Tool` keeps it off the taskbar and out of Alt-Tab.
- **Two geometries:** a ~6px tab and a ~320px panel, both computed by a pure
  function of `(screen_geometry, edge)`. This is the testable part.
- **Slide:** `QPropertyAnimation` on `geometry`, ~150ms.
- **Retract delay:** ~400ms after the mouse leaves, so a pointer crossing the
  edge on its way somewhere else does not make the panel flicker.
- **Focus:** `WA_ShowWithoutActivating`, so sliding out never steals focus from
  whatever you are typing in. The panel takes focus only when you click into
  the capture box.
- **Persistence:** chosen screen and edge saved to `panel.json` in the journal
  directory, alongside `notes/`. On first run the default is the right edge of
  the primary screen. If a remembered screen is gone (laptop undocked), fall
  back to the primary screen rather than opening off-screen.
- **Known limitation:** full-screen applications and games will cover it. Not
  worth fighting.

## Handoff

Clicking *open journal* builds the `Window` (or raises it if already open),
opens today, and retracts the panel. Because captures are already in the page,
the journal opens with them present and *Ask me something* works on them
immediately — no import step, no inbox to process.

## Autostart

Opt-in only, never on by default:

```
reflect-panel --autostart on
reflect-panel --autostart off
```

Writes or removes a value under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Windows only, matching
the rest of the app.

## Testing

**Tested:**

- `append_capture` on a fresh day, on an existing page, twice in a row
- `[HH:MM]` prefix survives render → parse → render
- `entries()` splits a merged writing block back into separate entries
- `entries()` on a pre-change page with no prefixes
- Collapsed and expanded rects for each of the four edges on a fake screen

**Not tested, verified by hand:** the slide animation, hover enter/leave
timing, always-on-top behaviour, the registry write. Mocking Qt hover events
tests the mock, not the panel.

## Survey of prior art

Ten open-source journals and note apps were reviewed for what could be reused.
Findings that outlive this document:

| Repo | License | Verdict |
|---|---|---|
| `team-reflect/reflect-open` | MIT | The only one whose code is safely reusable. `resolve-wikilink.ts` and the NFC-fold match-key rule in `keys.rs` are worth porting if links are ever built. |
| `UdaraJay/Pile` | **none** | All rights reserved — cannot copy a line. Its `pileEmbeddings.js` (embed entries, cosine similarity, surface related past entries) is the one good idea, and it requires an API key in Pile. `nobodywho` ships `Encoder` and `CrossEncoder`, so the same feature is possible fully offline. Parked. |
| `memex-lab/memex`, `theachoem/storypad` | GPL | Ideas only; copying would infect this MIT codebase. |
| `davidglassman/journaler` | MIT | `metrics.ts` (streaks, words per week) is tempting and rejected — this app does not score you. |
| `makalin/Daily-Markdown-Journal` | MIT | A fixed template with a mood tracker and "what are you grateful for". Useful as a negative example of the generic-prompt failure mode. |
| `shovanch/journal-prompts`, `superS007/localllmjournal`, `bgallois/OpenJournal`, `sangddn/prompt_builder` | — | Nothing to take. |
