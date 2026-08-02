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

`medical-ocr` and `vlm-read` are console-script entry points installed into the
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
(`vlm-read` warns when a reply is cut off). *Reasoning* models (e.g. `qwen3-vl`)
"think" before answering and need this headroom most — their thinking is kept in
`raw_text` if they run out of room before writing a final answer, so nothing is
lost. Notes on the models tested so far live in
[`docs/retrospectives/2026-08-02-vlm-read-bugs.md`](docs/retrospectives/2026-08-02-vlm-read-bugs.md).

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
