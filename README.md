# medical-ocr

R&D harness to extract structured data from hand-written medical images via multiple backends (VLM/Claude/Surya) and score against human ground truth

---

## Purpose

R&D harness to extract structured data from hand-written medical images via multiple backends (VLM/Claude/Surya) and score against human ground truth

This is a cli (python). It is developed using an agentic SDLC:
interview → design → test-first code → review → ship, with a human in the loop.

## Quick Start

```bash
git clone <repo-url>
cd medical-ocr
./setup.sh             # check / install developer dependencies
./install-hooks.sh     # install the pre-push test gate
./test.sh              # run the tests
```

## Setup

This is a **python** project. Developer dependencies:

- **git**, **gh** (GitHub CLI) — version control and the issue backlog.
- plus the toolchain your test suite needs (see the `Dev dependency:` note at
  the top of `test.sh`).

Run the checker to see what's missing and install it (macOS/Homebrew):

```bash
./setup.sh          # prompts before installing anything
./setup.sh --yes    # install without prompting (CI / non-interactive)
```

On other platforms `setup.sh` reports what to install by hand.

## User Guide

<!-- How an end user runs and uses medical-ocr. Filled in as features land. -->
Run `medical-ocr --help` for usage.

### Running the CLI commands

`medical-ocr`, `vlm-read`, `claude-envelope`, and `claude-extract` are console-script entry points installed into the
project's virtualenv (`.venv/`) by `setup.sh` — they are **not** standalone files
in the repo. They only appear on your `PATH` once that venv is active. Pick one:

```bash
source .venv/bin/activate    # activate the venv, then commands are on PATH
vlm-read --help

# or, without activating:
.venv/bin/vlm-read --help    # call the launcher directly
uv run vlm-read --help       # run through uv
```

(`./test.sh` works without activation because pytest imports from `src/`
directly — that path never creates the `vlm-read` launcher.)

### `vlm-read` — extract via a VLM

Send an image to a named vision model and write an extraction envelope JSON:

```bash
vlm-read sample-data/00.jpg ollama/llava
```

The envelope is written under a top-level `output/` tree mirroring the image's
location — e.g. `output/sample-data/00.vlm.ollama-llava.json`.

A default run makes **two focused VLM calls** into one envelope:

- **transcribe** → `raw_text`: a faithful plain-text read of *everything on the
  note* ("what the VLM sees").
- **extract** → `fields`: the ADR-0002 structured extraction ("what our schema
  captured").

Comparing the two makes a missing field diagnosable: text present in `raw_text`
but absent from `fields` is a *schema* gap; absent from both is a *perception*
gap. Each call is timed separately under `durations`; `duration_sec` is the
total. Pass `--no-transcribe` to make a single extraction call (then `raw_text`
is empty unless the extraction reply fails to parse, in which case the reply is
kept there so nothing is lost).

**Today only local [Ollama](https://ollama.com) models are supported**
(`ollama/<model>`); cloud providers are tracked in issue #5. Before running:

```bash
ollama serve            # start the local server (if not already running)
ollama pull llava       # pull the vision model you want to use
```

`vlm-read` preflights both — if the server is down or the model isn't pulled, it
tells you exactly what to run. Point at a non-default server with
`OLLAMA_API_BASE`. See `vlm-read --help` for all options.

#### Context window (`--num-ctx`) and reasoning models

A photo can cost thousands of input tokens, and Ollama's default context window
is small — so a large image can overflow it and the model gets cut off before it
answers, leaving an empty result. `vlm-read` therefore raises the window to a
generous default; override it with `--num-ctx` if you still see truncation
(`vlm-read` warns when a reply is cut off, naming which call). *Reasoning* models
(e.g. `qwen3-vl`) "think" before answering and need this headroom most — if a call
runs out of room before writing a final answer, its thinking is kept (as that
call's text) so nothing is lost. Notes on the models tested so far live in
[`docs/retrospectives/2026-08-02-vlm-read-bugs.md`](docs/retrospectives/2026-08-02-vlm-read-bugs.md).

### Claude — extract via `claude-extract` (one command)

If you have the [`claude` CLI](https://claude.com/claude-code) installed and signed
in, one command does the whole thing — read the image and write the envelope:

```bash
claude-extract sample-data/00.jpg
```

It runs headless `claude -p` with the canonical prompt, parses the
`{raw_text, fields}` reply, and writes
`output/sample-data/00.claude.claude-opus-4-8.json` — byte-compatible with a
`vlm-read` envelope, so `compare` treats it identically. Each run makes a
**billable** Claude call (see ADR-0005). `duration_sec` is the real wall-clock the
CLI reports.

**Which model, and can it be changed?** Because Claude interprets (it is not pure
OCR), the envelope records the model id. It defaults to **`claude-opus-4-8`**;
change it with `--model` (e.g. `--model claude-sonnet-5`) — the value is passed to
`claude --model` and recorded. The model id is part of the output filename (like
`vlm-read`), so runs from different Claude models never collide and can be compared
side by side. See `claude-extract --help` for all options.

#### Without the `claude` CLI — the manual convention

`claude-extract` is a convenience over a backend that also works **by hand**, with
no CLI dependency. You have Claude read the image in any session and then persist
the reply with `claude-envelope`. The full procedure — canonical prompt, envelope
convention, worked example — is in
[`docs/claude-extraction-prompt.md`](docs/claude-extraction-prompt.md):

```bash
# Claude returns {raw_text, fields} JSON in-session; save it, then:
claude-envelope sample-data/00.jpg --from answer.json
claude-envelope sample-data/00.jpg < answer.json     # or via stdin
```

Both paths write the same envelope shape to the same place.

## Developer Guide

<!-- Layout, how to add a feature, conventions. See design/overview.md. -->
The end-to-end design and key decisions live in [`design/overview.md`](design/overview.md).

## Automated Testing Guide

All tests run through a single entrypoint:

```bash
./test.sh
```

This is what the pre-push hook and CI both call — green locally means green on push.

## Release Process

Releases are automated through `release.sh` (bump version, tag, push).
Distribution: **none**.
