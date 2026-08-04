# ADR-0005 — `claude-extract`: make the Claude backend a script (reverses C3)

- **Status:** proposed
- **Date:** 2026-08-04
- **Serves:** UC-003, UC-006
- **Supersedes:** the "convention, not a script" stance for **C3** (see
  `architecture/overview.md`); builds on **F5** (#16 — canonical prompt +
  `claude-envelope` writer).

## Context

F5 (#16) delivered the Claude backend as a **convention, not a script** (C3): a
canonical prompt plus the `claude-envelope` helper that persists an answer the
researcher obtains by hand — open a Claude session, paste the prompt, attach the
image, copy the JSON reply to a file, run `claude-envelope`. That deliberately
avoided depending on any particular Claude CLI.

In practice the hand flow is clumsy and hard to reproduce (five manual steps, easy
to vary the prompt). Meanwhile the `claude` CLI (Claude Code) offers a headless
mode (`claude -p … --output-format json`) that can drive the whole thing. The
question: keep C3 a pure convention, or take the CLI dependency to get a
one-command, reproducible backend?

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Keep C3 as-is (convention only)** | No new dependency; no per-run cost baked into a tool | Clumsy 5-step manual flow; poor reproducibility; README stays awkward |
| **B — `claude-extract` script over headless `claude -p`** | One command; reproducible; reuses the F5 prompt + `claude-envelope` writer unchanged | Hard dependency on the `claude` CLI + auth; each run is a billable model call; a new external boundary to test |
| **C — Call the Anthropic API directly (SDK)** | No Claude-CLI dependency; more control over params | New API-key management + HTTP code; duplicates what the CLI already does; diverges from "use the tool the researcher already has" |

**Comparison metric:** **effort for a researcher to get a reproducible Claude
envelope** (steps per run, drift risk) — the same velocity lens as ADR-0001.

## Decision

**Chosen: Option B — `claude-extract`, a thin script over headless `claude -p`.**

`claude-extract <image>` assembles the canonical prompt + a "Read the image at
`<abs path>`" directive, runs
`claude -p … --model <m> --output-format json --allowedTools Read --add-dir <dir>`,
best-effort-parses the `{raw_text, fields}` reply, and hands it to
`claude_envelope.write_from_payload` — so the output is byte-identical to a
`claude-envelope` run and `compare` needs no Claude-specific handling.

**Why (one line):** it collapses the five-step hand flow to one reproducible
command while reusing the F5 prompt and writer wholesale — the manual convention
still stands underneath for anyone without the CLI.

**This reverses C3.** C3 previously read "Claude convention (prompt + envelope, no
script)". It now reads "Claude convention **or** the `claude-extract` script". The
convention is **not** removed — it is the fallback when the `claude` CLI is
unavailable, and it remains the single source of the prompt/envelope shape.

## Consequences

- **New hard dependency + cost:** `claude-extract` requires the `claude` CLI
  installed and authenticated, and **each run makes a billable model call.** This
  is opt-in — the F5 convention needs neither.
- **Model recorded verbatim:** `--model` (default `claude-opus-4-8`) is passed to
  `claude --model` *and* recorded in the envelope. The CLI's top-level output has
  no model id, so we record what we asked for (accepting it may drift from the
  exact model that ran). Real `duration_sec` comes from the CLI's `duration_ms`.
- **New external boundary:** the `claude` subprocess. Hermetic tests stub a fake
  `claude` on `PATH`; a VERIFY run exercises the real CLI un-mocked.
- **Environment isolation:** `claude-extract` scrubs its own venv (`VIRTUAL_ENV`,
  the `.venv/bin` PATH entry) from the spawned `claude`'s environment, so the
  nested session's hooks run in the interpreter they'd use interactively rather
  than our venv. (Found at VERIFY: a `uv run` venv leaking into the child broke a
  user `python3`-based hook.)
- **Layering, not replacement:** the canonical prompt and `claude_envelope` writer
  remain the single sources of truth; `claude-extract` orchestrates, it does not
  reimplement envelope writing.
