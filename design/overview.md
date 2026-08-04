# medical-ocr — Design Overview

> The curated, end-to-end design and **key** decisions for medical-ocr.
> Keep this current. Record only decisions that shape the architecture.

## Purpose

R&D harness to extract structured data from hand-written medical images via multiple backends (VLM/Claude/Surya) and score against human ground truth

## Architecture

Fully specified upstream — see the source of truth:
- **Concept:** [`discovery/concept.md`](../discovery/concept.md)
- **Use cases (UC-001…006):** [`discovery/use-cases.md`](../discovery/use-cases.md)
- **Architecture overview + component/capability map:** [`architecture/overview.md`](../architecture/overview.md)
- **Feature backlog (F1…F6):** [`architecture/components.md`](../architecture/components.md)
- **ADRs:** [`architecture/decisions/`](../architecture/decisions/)

**Shape:** file-in / file-out CLIs over a shared `common` lib (the seam). Backends
(`vlm-read`, `surya-ocr`, Claude convention) each emit the same envelope JSON;
`compare` scores any envelope against a hand-authored ground-truth sidecar.

## Key Decisions

<!-- One bullet per KEY decision, with a one-line rationale. Not every decision. -->
- Stack profile: python (cli); distribution: none.
- **VLM invocation via LiteLLM gateway** (ADR-0001) — adding a model to evaluate is a one-string change; same code path for local Ollama and cloud APIs.
- **Hybrid extraction envelope** (ADR-0002) — fixed metadata + `raw_text` + open `fields` dict; all three backends can fill it without locking a medical taxonomy.
- **VLM = two calls, one envelope** (ADR-0002 / #13) — `vlm-read` *transcribes* (plain-text "what the VLM sees" → `raw_text`) then *extracts* (structured → `fields`), so a missing field is diagnosable as a schema vs. perception gap; `--no-transcribe` reverts to extract-only. Per-call times in `durations`, total in `duration_sec`.
- **Ground-truth sidecar `<image>.truth.json`** (ADR-0003) — automatic image↔truth pairing; `--truth` override for exceptions.
- **Normalized exact-match, field-level scoring** (ADR-0004) — honors the stated requirement while removing false negatives from formatting noise; fuzzy is a future opt-in.
- **Claude backend = convention, not a script** (C3 / ADR-0002 / #16) — Claude extracts *in-session* from a documented canonical prompt (`docs/claude-extraction-prompt.md`) that returns one JSON `{raw_text, fields}` (faithful transcription **and** structured extraction, kept distinct per ADR-0002). A thin `claude-envelope` CLI *persists only* — it reads that payload from stdin/`--from` and writes the standard envelope via `common.write_envelope` (`technique="claude"`, `model`=the Claude id, no LLM call), so `compare` treats it identically to `vlm-read`/`surya-ocr`.
- **`common` is the contract** — new backends only need to "produce an envelope JSON."
- **Output-path convention (C8)** — machine outputs go to a top-level, gitignored `output/` tree that mirrors the image's location: `output/<image_parent>/<stem>.<technique>[.<model>].json` (model omitted for pure OCR, filesystem-unsafe chars sanitized). One disposable, never-committed root cleanly separates generated files from the **committed** curated inputs; multiple backends/models never collide. Ground-truth sidecars (`<image>.truth.json`) stay next to the image per ADR-0003 and **are** committed. The `output/` dir is kept in the repo (via a self-ignoring `output/.gitignore`) so users never create it by hand.

## Constraints

<!-- Security / performance / scale constraints captured at project start. -->
- **R&D velocity over production polish** — not production-hardened code at this stage.
- **Not HIPAA/PII-compliant** — real patient data is not handled compliantly yet.
- **Single-image only** — one file per invocation; no batch processing.
- **No web UI, no DB, no service** — the filesystem is the only store.

## Design & Usability Considerations

<!-- Anything shaping design or UX captured at project start. -->
- **Comparability is the point** — every backend must be scored the same way, so the shared envelope + normalized scoring matter more than any single backend's polish.
- **Cheap to add a technique** — the primary usability metric is effort to try a new VLM/backend (drives the LiteLLM and envelope-seam choices).
- **Local-first, cloud-optional** — start on local Ollama with no keys; add cloud baselines later by changing only the model string + credentials.
