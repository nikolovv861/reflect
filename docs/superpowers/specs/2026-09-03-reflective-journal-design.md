# Reflective Journal ("reflect") — Design

**Date:** 2026-09-03
**Status:** Draft, awaiting review
**Scope:** v1, PC only

---

## 1. The idea

A journal that thinks with you.

The app opens with a starter question. You write freely. When you want a
response, you press a key. The model asks **one** open follow-up question about
something specific you wrote. You answer it or you don't, and keep writing.

Everything runs on the machine. No account, no network at runtime, no upload.
This is not a feature. A journal is the most private text a person owns, and an
app that uploads it has a trust problem it can never fully close. One that
physically cannot upload it does not have the problem at all. That property is
the reason the app exists.

### What the model has to do

Read 200–800 words and ask one good question. That is comfortably within a 4B
model's ability. It does not need to be smart. It needs to be curious.

### The hard part

Question quality. A generic follow-up — "How did that make you feel?" — kills
the app on first use. This is roughly 90% prompt design and 10% engineering,
which is good news: it can be iterated in an afternoon without writing much
code. The design below is arranged around that fact.

### The design decision that protects the idea

Questions stay **open**, never **evaluative**. The "become a better person"
framing quietly turns into an app that scores you on your own diary, and that
is the version people delete after a week. Curiosity beats assessment, and the
system prompt has to defend that boundary explicitly.

---

## 2. Goals

1. **Portfolio proof** — a real artifact demonstrating a local-AI app.
2. **Example project for NobodyWho** — idiomatic, readable use of the library.
3. **A thing actually used** — good enough to still be open in a month.

These reinforce rather than compete: (2) forces clean code, (1) forces it to run
on someone else's machine, (3) forces the questions to be genuinely good.

### Non-goals for v1

Embeddings and retrieval, streak tracking, pattern reports over time,
writing-quality feedback, mobile, iOS, any cloud component, multi-user, sync.

---

## 3. Environment constraint (discovered during design, load-bearing)

**The Python binding must run on Windows Python, not WSL.**

`nobodywho` 2.0.0's Linux wheel is tagged `manylinux_2_34` but its native
library actually requires **glibc 2.38+** (it imports `__isoc23_strtoll` and
four sibling symbols). The development machine is Ubuntu 22.04 under WSL2 with
**glibc 2.35**, so the wheel installs and then fails at import:

```
ImportError: nobodywho.abi3.so: undefined symbol: __isoc23_strtoll
```

The Godot GDExtension has the identical requirement (`objdump` shows
`GLIBC_2.38` on its Linux `.so`), so switching bindings does not avoid it. Every
published Linux wheel from 0.3.0 to 2.0.0 carries the same mislabeled tag.

**Resolution:** run on Windows. The `win_amd64` wheel has no glibc dependency.
Verified working: Windows Python 3.12 installs `nobodywho` 2.0.0 and imports it
cleanly. This is also the better target regardless — the app is a Windows
desktop journal, and the RTX 2070 is driven natively rather than through WSL
GPU passthrough.

**Consequences:**

- The repository lives on the Windows filesystem (`C:\Users\nikol\reflect`) so
  both Windows Python and WSL tooling can reach it.
- Development invokes `python.exe` from WSL. This works; it was used to verify
  the API.
- The README must state the glibc floor, because a Linux user on Ubuntu 22.04
  will otherwise hit the same wall and assume the project is broken.

**Follow-up worth doing:** the mislabeled wheel tag is an upstream packaging
bug. Reporting it to NobodyWho serves goal (2) and costs one issue.

---

## 4. Verified API surface

Confirmed by introspection against the installed package, not from docs:

```python
from nobodywho import Chat

chat = Chat("huggingface:NobodyWho/Qwen_Qwen3-4B-GGUF/Qwen_Qwen3-4B-Q4_K_M.gguf")
stream = chat.ask("...")        # returns TokenStream
for token in stream:            # streams token by token
    ...
text = stream.completed()       # or take the whole thing
```

Relevant methods on `Chat`:

| Method | Use here |
|---|---|
| `set_system_prompt()` | Hot-swap prompt variants — the evaluation harness depends on this |
| `get_chat_history()` / `set_chat_history()` | Session persistence and resume |
| `set_allow_thinking()` | Qwen3 has a thinking mode; must be **off** so raw reasoning never reaches the transcript |
| `set_sampler_config()` | Question variety tuning |
| `reset()` / `reset_history()` | Start a new session on a warm model |
| `stop_generation()` | Cancel a slow response from the UI |

Module-level: `download_model(path, headers, on_download_progress)` — the
progress callback gives `(downloaded_bytes, total_bytes)`, which drives the
first-run progress bar. `get_cached_models()` reports what is already local.
`Model` is reference-counted and shareable across `Chat` / `Encoder` /
`CrossEncoder`, which is how phase 2 avoids loading a second copy.

**Model:** `NobodyWho/Qwen_Qwen3-4B-GGUF` → `Qwen_Qwen3-4B-Q4_K_M.gguf`
(~2.5GB). `NobodyWho/Qwen_Qwen3.5-4B-GGUF` also exists and should be tried in
the harness as a comparison, not assumed better.

---

## 5. Architecture

Four units, each with one purpose and no knowledge of the others' internals.

```
journal/
  store.py        entries on disk           knows nothing about AI
  engine.py       wraps nobodywho           knows nothing about UI or disk
  prompts/        system prompts as files   not code
  ui.py           PySide6 window            knows nothing about the model
evaluate.py       prompt comparison harness
```

The split exists so prompts can be iterated and the harness run with the UI
never imported. The UI is the part that does not matter; the prompt is the part
that does, and the structure should make that ordering obvious to anyone reading
the repo.

| Unit | Does | Used via | Depends on |
|---|---|---|---|
| `store` | Read/write/list sessions | `save(session)`, `load(path)`, `list_sessions()` | stdlib only |
| `engine` | Turn a conversation into one question | `ask(history, entry) -> Iterator[str]` | `nobodywho` |
| `prompts` | Hold prompt text, versioned | file read | nothing |
| `ui` | Writing surface, key handling, streaming display | — | `store`, `engine` |

`engine` yields tokens rather than returning a string, so the UI streams and the
harness simply joins. One interface, both consumers.

---

## 6. Interaction loop

1. App launches. Model loads (warm: ~2s; first run: model download first).
2. A starter is chosen from `prompts/starters.txt` — "How was your day?" and
   siblings. Shown as the AI's first turn.
3. The writer types into a plain text area. No formatting, no toolbar, no
   distraction.
4. **`Ctrl+Enter`** requests a question. Nothing is automatic: the app never
   interrupts. An AI that interrupts your thinking commits the same sin as one
   that scores your diary, and pausing to think is exactly when the best work
   happens.
5. The entry so far plus prior turns go to the model. One question streams back
   and is appended to the transcript as an AI turn.
6. Writing continues below it. Repeat as long as wanted.
7. `Ctrl+S` saves; closing saves. Sessions are resumable via `set_chat_history`.

---

## 7. Storage

One Markdown file per session: `~/Documents/journal/2026-09-03-1432.md`.

```markdown
---
started: 2026-09-03T14:32:11
model: Qwen_Qwen3-4B-Q4_K_M
prompt_version: v3
---

## ai
How was your day?

## me
Long stretch of writing...

## ai
You mentioned the review twice and moved past it both times — what happened there?

## me
...
```

Plain text on purpose. The journal outlives the app, it can be grepped, it can
be opened in any editor, and phase-2 embeddings can read it without a migration.
YAML frontmatter records which prompt version produced the session, which is
what makes prompt iteration measurable after the fact.

---

## 8. The system prompt — the actual deliverable

Prompts live in `journal/prompts/`, one file per variant, each with a version
header. They are treated as the primary artifact of the project, not as a string
constant buried in `engine.py`.

Rules encoded in the prompt:

- Ask **exactly one** question. Never two, never a list.
- Open, never evaluative. No scoring, no praise, no advice, no summarizing back.
- Reference something **specific** the writer actually wrote. Quote or name it.
- Prefer what was skimmed, hedged, or buried over what was stated plainly.
- Banned: "How did that make you feel?" and its paraphrases.
- No preamble. Output is the question and nothing else.

Four variants ship in v1, deliberately including one that breaks the rules:

| Variant | Purpose |
|---|---|
| `v1-plain` | Minimal instruction. Baseline — proves whether elaboration is even needed. |
| `v2-specific` | Heavy emphasis on quoting the writer's own words. |
| `v3-buried` | Targets what was skipped, hedged, or understated. |
| `v4-evaluative` | **Deliberately evaluative.** The version people delete after a week. |

`v4` exists so the failure mode is felt rather than taken on faith. Knowing what
the bad one reads like is worth one slot.

---

## 9. Evaluation harness

`evaluate.py` is the most important file in the project.

Question quality cannot be unit-tested, so the harness makes it **comparable**
instead. Fixture entries in `fixtures/entries/` (real writing, not synthetic —
synthetic entries produce synthetic questions and the test goes hollow), every
prompt variant run against each, results written side by side to
`fixtures/results/<timestamp>.md` for human judgement.

```
$ python evaluate.py
entry: 01-work-week.md
  v1-plain      → "What made the deadline feel different this time?"
  v2-specific   → "You called it 'the usual chaos' — what's usual about it?"
  v3-buried     → "You mentioned your manager once and moved on. What happened?"
  v4-evaluative → "It sounds like you're avoiding conflict. Have you considered..."
```

This is the loop that makes an afternoon of prompt iteration possible. It runs
without the UI and without PySide6 installed.

---

## 10. Error handling

| Case | Behaviour |
|---|---|
| Model not cached on first run | Progress bar via `on_download_progress`; app usable for writing while it downloads |
| Download fails | Error with the URL and a retry button. Writing still works; questions disabled |
| No GPU / Vulkan missing | Falls back to CPU. Warn once that responses take 15–30s instead of ~2s |
| Generation slow or stuck | `stop_generation()` wired to Escape |
| Model returns multiple questions | Truncate to the first question mark; log it as a prompt-quality signal |
| Corrupt or hand-edited session file | Load what parses, warn, never overwrite the original |
| Disk write fails | Keep text in memory, surface the error loudly. Losing an entry is the worst possible failure |

Writing must never be blocked by the AI. If the model is broken, missing, or
downloading, the app is still a text editor that saves files. This follows from
goal (3): a journal that refuses to open because inference failed is not a
journal.

---

## 11. Testing

- **`store.py`** — real unit tests. Round-trip, malformed frontmatter, unicode,
  missing directories, concurrent sessions.
- **`engine.py`** — tested against a stub token source so the suite runs in
  seconds with no 2.5GB model present.
- **`ui.py`** — no automated tests in v1. Manual.
- **Question quality** — no assertions. That is the harness's job, and a human's.

CI is not in v1 scope; the test suite is run locally.

---

## 12. Phase 2 (designed for, not built)

The pitch line — *"You've mentioned being annoyed at work three times this week,
what's going on there?"* — requires retrieval across past entries, not a single
entry read. It is the strongest version of the idea and it is deliberately
deferred, because the conversational loop makes the app useful on day one with
zero history, which removes the cold-start problem entirely.

When it lands: `Encoder` embeds each saved session, similar past entries are
retrieved for the current one, `CrossEncoder` reranks them, and the top few are
injected into the prompt as context. `Model` is shared, so no second copy of
weights is loaded. Nothing in the v1 storage format needs to change — which is
the point of choosing plain Markdown now.

---

## 13. Open questions

1. **Is a 4B curious enough?** The load-bearing unknown. The harness answers it
   before any UI work, and if the answer is no, the stack choice was irrelevant.
   Fallback is a larger model on desktop, accepting a higher RAM floor.
2. **Qwen3 vs Qwen3.5 4B** — compare in the harness; do not assume.
3. **Starter quality.** Starters may matter as much as follow-ups. Unknown until
   used for real.
4. **Session length.** Whether questions degrade as context grows is untested.
