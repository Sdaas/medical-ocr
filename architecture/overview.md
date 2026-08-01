# Architecture Overview — medical-ocr

> Produced by `/architecture`. Curated, not exhaustive. Traces to the capability
> map (Gate 1) and the use cases in `../discovery/use-cases.md`. This is an R&D
> evaluation harness — velocity and comparability over production polish.

## Capability → component map

| Capability | Serves (UC) | Component |
|---|---|---|
| C1 VLM extraction | UC-001 | `vlm-read` CLI |
| C2 Surya OCR extraction | UC-002 | `surya-ocr` CLI |
| C3 Claude extraction | UC-003 | Claude convention (prompt + envelope, no script) |
| C4 Shared extraction envelope | UC-001/002/003/006 | `common` (shared lib) |
| C5 Ground-truth association | UC-004/005 | `common` (shared lib) + filesystem |
| C6 Scoring / comparison | UC-005 | `compare` CLI |
| C7 Duration measurement | UC-001/002/006 | `common` (shared lib) |
| C8 Output file writing | UC-001/002/003/005/006 | `common` (shared lib) |
| C9 Multi-backend orchestration | UC-006 | `run-all` orchestrator |

**Coverage:** every use case is served by ≥1 capability/component; nothing floats.

## Components

- **`common`** — shared Python module: the extraction-envelope schema (C4),
  duration timing helper (C7), output-file writer + path convention (C8), and
  ground-truth locate/validate helpers (C5). Every other component depends on it.
  This is the contract that makes backends comparable.
- **`vlm-read` CLI** — `vlm-read file.jpg model-name` (C1). Sends the image to a
  named VLM, times it, writes an envelope JSON.
- **`surya-ocr` CLI** — `surya-ocr file.jpg` (C2). Runs Surya, times it, writes
  an envelope JSON.
- **Claude convention** — not a script (C3). A documented prompt + the envelope
  shape; Claude reads the image in-session and saves an envelope JSON to the same
  output location the CLIs use.
- **`compare` CLI** — `compare <backend.json…> --truth <truth.json>` (C6). Loads
  backend envelope(s) + ground truth, computes field-level accuracy with
  exact-match per field, writes a score file.
- **`run-all` orchestrator** — one command over one image that invokes the
  available backends (C9). Deferred (P2).
- **Filesystem (data store)** — images, output envelope JSONs, hand-authored
  ground-truth JSONs, and score files all live as plain files.

## Container diagram (C4-ish)

```mermaid
flowchart TB
    Researcher([Researcher])
    Truth([Ground-truth provider])

    subgraph CLI["medical-ocr CLIs"]
        VLM["vlm-read (C1)"]
        SURYA["surya-ocr (C2)"]
        COMPARE["compare (C6)"]
        RUNALL["run-all (C9, P2)"]
    end

    COMMON["common lib<br/>envelope C4 · timing C7<br/>output C8 · truth-lookup C5"]
    CLAUDE["Claude extraction (C3)<br/>in-session, convention"]

    subgraph FS["Filesystem"]
        IMG[("images")]
        OUT[("envelope JSONs")]
        GT[("ground-truth JSONs")]
        SCORE[("score files")]
    end

    Researcher --> VLM & SURYA & COMPARE & RUNALL
    Researcher --> CLAUDE
    Truth --> GT

    VLM --> COMMON
    SURYA --> COMMON
    RUNALL --> VLM & SURYA
    CLAUDE --> COMMON

    IMG --> VLM & SURYA & CLAUDE
    COMMON --> OUT
    VLM & SURYA & CLAUDE --> OUT

    OUT --> COMPARE
    GT --> COMPARE
    COMPARE --> COMMON
    COMPARE --> SCORE

    VLM -.->|API| ExtVLM["External VLM provider"]
    SURYA -.->|local| SuryaLib["Surya library"]
```

## Boundaries & notes

- **Everything is file-in / file-out.** No web UI, no DB, no batch, no service
  (per concept non-goals). The filesystem is the only store.
- **`common` is the seam.** The envelope schema is the single contract; adding a
  new backend later means "produce an envelope JSON," nothing more.
- **Claude is a backend without a script** — it participates by writing the same
  envelope shape to the same output location, so `compare` treats it identically.
- **External dependencies:** `vlm-read` calls an external VLM provider (API);
  `surya-ocr` uses the local Surya library. These are the two contested-stack
  points handled in the ADRs.

## Open questions (resolved in ADRs / backlog)

- Envelope JSON schema specifics → ADR-0002.
- VLM invocation approach (which provider/SDK, config) → ADR-0001.
- Ground-truth file naming convention → ADR-0003.
- Scoring definition for nested/text fields → ADR-0004.
