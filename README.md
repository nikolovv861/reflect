# reflect

A journal that thinks with you.

One page a day. You write down it, and when you want, you click **Ask me
something** and one open question appears in the margin, right where you
stopped. Not "how did that make you feel" — something you actually skipped over.

It is deliberately **not** a chat. There is no transcript, no input box, no
send. Your words stay exactly where you typed them and you keep writing past
the question. That one property is most of what separates a journal from a
chatbot.

It runs entirely on your machine. No account, no network, no upload. A journal
is the most private text you own, and an app that uploads it has a trust problem
it can never fully close. This one physically cannot.

## Install

```bash
git clone <repo> && cd reflect
python -m venv .venv
.venv\Scripts\activate
pip install -e .
reflect
```

First launch downloads the model (~2.5GB, once). After that it opens offline in
about two seconds, forever.

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

To stop it: right-click the panel and choose **Quit**, or press **Ctrl+Q**
while it has focus. It sits outside the taskbar and Alt-Tab, so this is the
way out.

The panel captures thoughts only. Core values and goals live in the journal
window, and there are deliberately no to-dos — a to-do has state and a thought
does not.

## Requirements

- **Windows.** See the Linux note below.
- Python 3.10+
- ~8GB free RAM
- A GPU is strongly recommended. On an RTX 2070, questions come back in
  **well under a second**. On CPU alone, expect 15–30s — usable, but it changes
  the feel.

**The very first question is slow (~25s) even on a GPU.** That is a one-time
Vulkan shader compile, not the model. Every question after it is sub-second.
Run `python download_model.py` after installing to get the download and that
first compile out of the way before you sit down to write.

## Linux note

`nobodywho` 2.0.0's Linux wheel is tagged `manylinux_2_34` but its native
library requires **glibc 2.38+** — it imports `__isoc23_strtoll`. On Ubuntu
22.04 (glibc 2.35) it installs cleanly and then fails at import:

```
ImportError: nobodywho.abi3.so: undefined symbol: __isoc23_strtoll
```

Ubuntu 24.04 or newer should work. This is an upstream packaging issue, not a
bug in this project. The Godot GDExtension has the same requirement.

## Practices

A blank page gives you nothing to write toward, and gives the model nothing
specific to work with — so the questions come back generic. Pick a practice on
the date line and the page opens with a real prompt already on it.

| Practice | What you're doing | Arc |
|---|---|---|
| Free writing | whatever you want | open |
| Attention inventory | where your attention went, whether you put it there or it was hijacked, and what you felt just before | 7 days |
| Life as a story | the title and theme of your story, the chapter you're in, the narrative you keep because it's familiar | 14 days |
| Core values | the three that matter most, where each came from, what each has cost | one-off |

Each practice also extends the system prompt, so a follow-up inside Attention
Inventory digs at the hijack rather than asking something generic.

**Practices have an arc, not a streak.** The header reads
`ATTENTION INVENTORY · DAY 3 OF 7` — a thing with an ending, which is a reason
to come back that cannot be broken. It counts days you *wrote*, never days you
missed. Skip Tuesday and Wednesday is still day 4. There is no calendar, no
score, and no notification, on purpose: an app that grades your diary is one
you delete after a week.

## Notes and your past

A sidebar holds two things beside the daily page:

**Your past days**, newest first, with word counts. Click any of them to reread
or keep writing. A journal you cannot reread is barely a journal, and this was
missing for far too long.

**Standing notes** — undated documents you keep editing rather than dated
records: *Core values* and *Goal* are created for you on first run, already
filled with the questions worth answering. Add your own with `Ctrl+N`.

Notes are also **context for the questions**. What you wrote about what matters
to you is given to the model as background, with an explicit instruction never
to quote it back or measure your day against it. It informs the question; it
does not become a scorecard.

`Ctrl+F` searches everything — every day and every note — with snippets around
the match.

## How it works

Four pieces, deliberately separable:

| File | Responsibility |
|---|---|
| `journal/store.py` | Sessions as Markdown on disk. Knows nothing about AI. |
| `journal/engine.py` | Wraps NobodyWho. Knows nothing about the UI or disk. |
| `journal/prompts/` | Question-style prompts, as versioned files. Not code. |
| `journal/practices/` | The reflective frames, as files. Not code. |

Pages live in `~/Documents/journal/`, notes in `~/Documents/journal/notes/`.
| `journal/ui.py` | The page. Knows nothing about the model. |

The unit is the **day**, not a session. Pages are saved to
`~/Documents/journal/2026-09-03.md`, one file per date — close the app and
reopen it after dinner and you are back on the same page, cursor at the end.
It autosaves every 20 seconds.

Your writing is stored as ordinary paragraphs. Questions are stored as Markdown
blockquotes, so the file reads correctly anywhere and your own words remain the
bulk of it:

```markdown
---
date: 2026-09-03
---

Rewrote the export pipeline today. Fine, I guess. Standup was the usual.
I mentioned the deadline slipping again but it got skipped over.

> Why did you mention the deadline slipping again but it got skipped over
> in standup?

Honestly I think nobody wants to own it.
```

Plain text on purpose — your journal outlives this app, and you can grep it.

Writing is never blocked by the AI. If the model is missing, downloading, or
broken, this is still a text editor that saves your work.

## Iterating on the questions

The question is the product, and the prompt is ~90% of the question. Prompts
live in `journal/prompts/` as files so they can be diffed and versioned. To
compare them:

```bash
# add real entries to fixtures/entries/ first
python evaluate.py
```

Every variant runs against every entry, side by side, so you judge them against
each other rather than one at a time:

```
entry: 01-work-week.md
  v1-plain      -> What made the deadline feel different this time?
  v2-specific   -> You called it "the usual chaos" — what's usual about it?
  v3-buried     -> You mentioned your manager once and moved on. What happened?
  v4-evaluative -> It sounds like you're avoiding conflict. Have you considered...
```

`v4-evaluative` is deliberately bad. It's kept so the failure mode can be read
rather than imagined — an app that scores you on your own diary is the version
people delete after a week.

## Tests

```bash
python -m pytest
```

66 tests, no model required — the engine is tested against a stub, so the suite
runs in well under a second. The UI tests cover the one genuinely fragile part:
whether a question stays marked as a question through editing, saving and
reopening, rather than bleeding into your own words.

## Not in v1

Retrieval across past entries ("you've circled back to this three times"),
streaks, pattern reports, writing-quality feedback, mobile. The storage format
is plain Markdown specifically so retrieval can be added later without a
migration.

## Built with

[NobodyWho](https://github.com/nobodywho-ooo/nobodywho) — local LLM inference on
llama.cpp.
