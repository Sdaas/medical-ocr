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
