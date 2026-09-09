# reflect

*A journal that thinks with you, and a finished example of what
[**NobodyWho**](https://github.com/nobodywho-ooo/nobodywho) lets you build.*

> **Building apps with local AI?** [**NobodyWho**](https://github.com/nobodywho-ooo/nobodywho)
> is a young, genuinely promising engine for running language models on your
> users' own hardware: no API, no key, no server, no per-call cost. reflect is a
> complete app built entirely on it, running offline with the model loaded once
> and answering in under a second. If that is what you came for,
> **[go star NobodyWho ⭐](https://github.com/nobodywho-ooo/nobodywho)**.

One page a day. You write, and when you want, you click **Ask me something** and
one open question appears in the margin, right where you stopped. Not "how did
that make you feel," but something you actually skipped over.

It is deliberately **not** a chat. No transcript, no input box, no send. Your
words stay where you typed them and you keep writing past the question. That one
property is most of what separates a journal from a chatbot.

## Demo

[![reflect demo](docs/reflect-demo.gif)](docs/reflect-demo.mp4)

*A 20-second walkthrough: one margin question a day, then your whole year read
back. The preview is silent; [watch with sound](docs/reflect-demo.mp4).*

## Powered by NobodyWho

Every question is generated locally by
[**NobodyWho**](https://github.com/nobodywho-ooo/nobodywho), an inference engine
built on llama.cpp that runs the model on your own hardware (Metal on Apple
Silicon, Vulkan on a GPU, CPU as a fallback).

It is the single choice that makes the rest possible: no server to trust means
privacy is structural, not a policy. `journal/engine.py` is the only file that
talks to it, so if you are building something with local AI, that one file is
the whole integration. **[Star NobodyWho ⭐](https://github.com/nobodywho-ooo/nobodywho)**
and see how little it takes.

## Privacy

The app runs entirely on your machine and has no way to send your writing
anywhere. That is a property of how it is built, not a promise in a policy:

- **No account, no cloud, no network calls, ever.** Your words never leave the device.
- **Your files stay yours,** as plain Markdown in `~/Documents/journal/`. Read,
  back up, grep, or delete them without this app.
- **Proven, not claimed.** `test_no_network.py` blocks every socket, then
  exercises storage, the model, and a headless window, so the no-upload promise
  fails loudly if any code ever reaches for the network.

## Install

```bash
git clone https://github.com/nikolovv861/reflect && cd reflect
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
reflect
```

First launch downloads the model (~2.5GB, once). After that it opens offline in
about two seconds. Run `python download_model.py` first to get the download and
the one-time shader compile out of the way.

## Requirements

- **Windows**, or **macOS on Apple Silicon** (Metal accelerated). Linux needs
  glibc 2.38+ (Ubuntu 24.04 or newer); the `nobodywho` 2.0.0 wheel fails to
  import on older versions.
- Python 3.10+, ~8GB RAM.
- A GPU is strongly recommended: sub-second questions on an RTX 2070, 15 to 30s
  on CPU alone.

## What's inside

- **Practices.** Pick a frame (morning pages, what I'm avoiding, attention
  inventory, a decision you're sitting on) and the page opens with a real
  prompt. Each has an arc, not a streak. They are just Markdown files in
  `journal/practices/`, so adding your own takes no code.
- **Review your year.** Fourteen questions that shape a year, then *Where you
  stand*: a genuine reading drawn on the local model, not a mirror.
- **Suggest a line** (`Ctrl+Space`) offers one continuation in your own voice.
  Nothing is saved until you accept it.
- **Your past, searchable.** A sidebar of past days and standing notes;
  `Ctrl+F` searches everything.

Plain Markdown on disk, one file per day. Writing is never blocked by the AI:
if the model is missing or busy, this is still a text editor that saves your work.

## Tests

```bash
python -m pytest
```

140 tests, no model required: the engine runs against a stub, so the suite
finishes in well under a second.
