# ADR-0002 — Shared extraction envelope schema

- **Status:** proposed
- **Date:** 2026-08-01
- **Serves:** UC-001, UC-002, UC-003, UC-005, UC-006

## Context

Every backend (VLM, Surya, Claude) writes JSON, and `compare` must read them
uniformly — but the backends produce different things: Surya yields raw text
regions, VLMs/Claude can yield structured fields. We need one envelope that all
three can fill and that scoring can consume, without yet knowing the "right"
medical field set.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Flat raw text only** | Trivial; every backend can produce it | No structured fields to score; loses the point of VLM extraction |
| **B — Fixed medical schema (patient, drug, dose…)** | Directly scoreable fields | We don't yet know the right fields; premature; brittle |
| **C — Hybrid: fixed metadata + `raw_text` + open `fields` dict** | Backends fill what they can; metadata always present; extensible | `fields` shape is loose until we converge |

**Comparison metric:** **works for all three backends today without locking a
field taxonomy we haven't validated** (R&D flexibility).

## Decision

**Chosen: Option C — hybrid envelope.**

```jsonc
{
  "filename": "rx_001.jpg",       // metadata (always)
  "technique": "vlm",             // vlm | surya | claude
  "model": "gpt-4o",              // model/engine id (null for pure OCR)
  "duration_sec": 3.3,            // total wall-clock for the run
  "durations": {                   // optional per-call breakdown; {} if single-call
    "transcribe": 1.2,
    "extract": 2.1
  },
  "timestamp": "2026-08-01T...",
  "raw_text": "…",                // best-effort full text (VLM transcription / Surya OCR)
  "fields": {                      // best-effort structured extraction
    "patient_name": "…",
    "medications": [ { "name": "…", "dose": "…", "frequency": "…" } ]
  }
}
```

**Why (one line):** It's the only option all three backends can fill now while
leaving the medical field taxonomy free to evolve.

### `raw_text` vs `fields`, and per-call durations (issue #13)

`raw_text` and `fields` capture two *different* things, filled by two *different*
model calls in the VLM backend:

- **`raw_text` — "what the VLM sees":** a faithful plain-text transcription of the
  whole note (a dedicated transcribe call), independent of any schema. For pure
  OCR (Surya) this is simply the recognized text.
- **`fields` — "what our schema captured":** the structured extraction. The
  extraction reply is parsed into real JSON here, so it is **never stored as an
  escaped fenced blob** in `raw_text`.

Splitting these makes a missing field diagnosable: present in `raw_text` but
absent from `fields` → a **schema** gap; absent from both → a **perception** gap.

`duration_sec` is always the total wall-clock. `durations` is an optional per-call
breakdown for backends that make more than one call (VLM: `transcribe` +
`extract`); it is an empty object for single-call/pure-OCR backends, so every
envelope keeps the same shape.

## Consequences

- `compare` scores over `fields` (and can fall back to `raw_text`); the `fields`
  keys are a convention to converge, not a hard schema — revisit as we learn.
- Ground-truth files (ADR-0003) use the same `fields` shape.
- There is **no `raw_json` field**: the extraction reply lands directly in `fields`
  as parsed JSON, not as text.
- `compare` (#3) is unaffected — the `fields` / ground-truth shape is unchanged;
  `durations` is additive and optional.
