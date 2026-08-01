# ADR-0001 — VLM invocation approach

- **Status:** proposed
- **Date:** 2026-08-01
- **Serves:** UC-001, UC-006

## Context

`vlm-read file.jpg model-name` must let the researcher name *any* of several
VLMs and get an extraction back, and adding a new model to try should be cheap
(velocity is the whole point). How `model-name` maps to an actual backend call
is the decision.

Note there are **two separate axes** here, and this ADR only decides the first:

1. **Abstraction** — one uniform call vs. a hand-written adapter per provider.
   *(This ADR.)*
2. **Where the model runs** — a locally/remotely hosted open-weight model (e.g.
   via an Ollama server) vs. a cloud API. This is a *downstream* choice about
   which `model-name` to point at, **not** decided here.

The right invocation layer should sit *above* axis 2 so the same `vlm-read`
command can target a local Ollama model today and a cloud API tomorrow, with the
only difference being the model string and whatever keys/endpoint that model
needs.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Direct per-provider SDKs + dispatch map** | Full control per model; no extra abstraction | Must hand-write an adapter per provider; more code to add a model |
| **B — Unified LLM gateway (e.g. LiteLLM)** | One call signature for 100+ models; adding a model = change a string; vision supported | Extra dependency; leaky abstraction for exotic params |
| **C — Local models via Ollama** | No API cost/keys; fully local/private | Limited vision-model quality; heavier setup; slower iteration on frontier models |
| **D — Single provider only** | Simplest | Defeats the compare-many-techniques goal |

**Comparison metric:** **effort to add and try a new VLM** (lines changed / new
dependencies) — because iteration velocity across techniques is the stated goal.

## Decision

**Chosen: Option B — unified LLM gateway (LiteLLM).**

**Why (one line):** Adding a model to evaluate becomes a one-string change, which
directly maximizes the iteration-velocity metric.

**Key rationale — one interface, both worlds.** LiteLLM is a *gateway that sits
above where the model runs* (axis 2 in Context). The same `vlm-read` command can
route to:

- a **local Ollama server** (e.g. `ollama/llava`) — no API cost, stays on the
  machine — for open-weight VLM evaluation and private runs, **and**
- a **remote Ollama server** on another host, **and**
- **cloud APIs** (OpenAI, Anthropic, Google, …) in the future — just provision
  the right API keys / endpoint and name the model.

The only thing that changes between these is the `model-name` string plus the
credentials/endpoint that model requires. This gives us local-first flexibility
now without foreclosing cloud baselines later — a superset of what an
Ollama-only or single-cloud choice would allow.

## Consequences

- `model-name` is passed straight through to LiteLLM's model identifier (e.g.
  `ollama/llava`, `gpt-4o`, `gemini/…`); credentials/endpoints come from env vars.
- **Local (Ollama) and cloud are the same code path** — switching is a config/
  string change, not a code change. Start local; add cloud keys when wanted.
- If a model needs params the gateway can't express, we drop to a direct SDK for
  that one model only.
