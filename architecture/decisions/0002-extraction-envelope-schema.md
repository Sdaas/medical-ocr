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
  "duration_sec": 3.2,
  "timestamp": "2026-08-01T...",
  "raw_text": "…",                // best-effort full text (esp. Surya)
  "fields": {                      // best-effort structured extraction
    "patient_name": "…",
    "medications": [ { "name": "…", "dose": "…", "frequency": "…" } ]
  }
}
```

**Why (one line):** It's the only option all three backends can fill now while
leaving the medical field taxonomy free to evolve.

## Consequences

- `compare` scores over `fields` (and can fall back to `raw_text`); the `fields`
  keys are a convention to converge, not a hard schema — revisit as we learn.
- Ground-truth files (ADR-0003) use the same `fields` shape.
