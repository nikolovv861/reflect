# reflect

A journal that thinks with you.

You write. When you want, you press `Ctrl+Enter` and it asks **one** open
question about something specific you wrote. Not "how did that make you feel" —
something you actually skipped over.

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

## Requirements

- **Windows.** See the Linux note below.
- Python 3.10+
- ~8GB free RAM
- A GPU is strongly recommended: with Vulkan, questions arrive in ~2s. On CPU
  alone, expect 15–30s — usable, but it changes the feel.

## Linux note

`nobodywho` 2.0.0's Linux wheel is tagged `manylinux_2_34` but its native
library requires **glibc 2.38+** — it imports `__isoc23_strtoll`. On Ubuntu
22.04 (glibc 2.35) it installs cleanly and then fails at import:

```
ImportError: nobodywho.abi3.so: undefined symbol: __isoc23_strtoll
```

Ubuntu 24.04 or newer should work. This is an upstream packaging issue, not a
bug in this project. The Godot GDExtension has the same requirement.

## How it works

Four pieces, deliberately separable:

| File | Responsibility |
|---|---|
| `journal/store.py` | Sessions as Markdown on disk. Knows nothing about AI. |
| `journal/engine.py` | Wraps NobodyWho. Knows nothing about the UI or disk. |
| `journal/prompts/` | The system prompts, as versioned files. Not code. |
| `journal/ui.py` | The writing surface. Knows nothing about the model. |

Entries are saved to `~/Documents/journal/` as plain Markdown with one file per
session. Plain text on purpose — your journal outlives this app, and you can
grep it.

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

21 tests, no model required — the engine is tested against a stub, so the suite
runs in well under a second.

## Not in v1

Retrieval across past entries ("you've circled back to this three times"),
streaks, pattern reports, writing-quality feedback, mobile. The storage format
is plain Markdown specifically so retrieval can be added later without a
migration.

## Built with

[NobodyWho](https://github.com/nobodywho-ooo/nobodywho) — local LLM inference on
llama.cpp.
