# Feature Backlog — medical-ocr

> Produced by `/architecture` — its terminal artifact. Each row is a **feature**
> sized for one `/feature` run, **traced** to the use cases it satisfies and
> **sequenced** by dependency + deferral discipline. Becomes GitHub Issues.

## Components (from architecture/overview.md)

- **`common`** — shared lib: envelope schema, timing, output writer, ground-truth
  locate/validate. The seam everything depends on.
- **`vlm-read` CLI** — extract via a named VLM through LiteLLM (ADR-0001).
- **`surya-ocr` CLI** — extract via Surya.
- **Claude convention** — in-session extraction that writes the same envelope.
- **`compare` CLI** — field-level, normalized exact-match scoring (ADR-0004).
- **`run-all` orchestrator** — every backend on one image (deferred).

## Backlog

Ordered by build sequence.

| # | Feature | Serves (UC) | Component | Priority | Depends on |
|---|---|---|---|---|---|
| F1 | **`common` foundation** — envelope schema (ADR-0002), duration timer, output-file writer + path convention, ground-truth sidecar convention + locate/validate helper (ADR-0003) | UC-004 (+ enabler for all) | `common` | P0 | — |
| F2 | **`vlm-read` CLI** — `vlm-read file.jpg model-name` via LiteLLM (ADR-0001); times + writes envelope | UC-001 | `vlm-read` | P0 | F1 |
| F3 | **`compare` CLI** — score backend envelope(s) vs. ground truth; normalized exact-match, field-level accuracy (ADR-0004); writes score file | UC-005 | `compare` | P0 | F1, F2 |
| F4 | **`surya-ocr` CLI** — `surya-ocr file.jpg`; runs Surya, times, writes envelope | UC-002 | `surya-ocr` | P1 | F1 |
| F5 | **Claude extraction convention** — documented prompt + envelope; Claude reads image in-session, saves envelope JSON to the standard path | UC-003 | Claude convention | P1 | F1 |
| F6 | **`run-all` orchestrator** — one command runs available backends on one image, one envelope each | UC-006 | `run-all` | P2 | F2, F4, F5 |
| F7 | **`claude-extract` CLI** — one-command Claude backend over headless `claude -p` (ADR-0005, reverses C3's "no script"); reuses the F5 prompt + `claude-envelope` writer | UC-003 | `claude-extract` | P1 | F5 |

## Sequencing rationale

- **F1 first** because it is the seam — every backend and `compare` depend on the
  envelope schema, output-path convention, and ground-truth locator. Building any
  backend before F1 would duplicate the contract we'd then have to unify.
- **F2 before F3** because `compare` (F3) needs real envelope files to score, and
  `vlm-read` is the primary backend that produces them. F1→F2→F3 closes the core
  loop end-to-end: *extract → author truth → score*. All three P0.
- **F4, F5 are P1** — they broaden the set of techniques being compared but the
  core extract-and-score loop already works without them. They only depend on F1
  (the envelope), so they can be built in either order once the loop exists.
- **F6 is P2 (deferral discipline)** — orchestration is pure convenience over the
  single-backend commands; it depends on the backends it composes (F2, F4, F5),
  so it comes last.
- **UC-004 (ground truth)** is satisfied by F1 (convention + template + locate/
  validate helper) plus human authoring — no separate build feature needed.

## Handoff

- [ ] Issues created for P0 features (F1–F3) with `Depends on` lines
- [ ] `PROGRESS.md` / board updated with the new backlog
- Next: `/feature` picks the earliest unblocked P0 (**F1**).
