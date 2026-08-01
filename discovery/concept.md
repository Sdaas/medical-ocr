# Concept — medical-ocr (extraction technique evaluation harness)

> Produced by `/discovery`. Curated, not exhaustive. Keep it to one page.
> `In your words:` blocks are the human's verbatim ground truth — never
> overwrite them. Everything else is AI distillation, subject to approval.

## One-sentence what

A set of quick, command-line evaluation tools that extract structured data from
images of hand-written medical notes/prescriptions using different backends (VLM
models, Claude, and OCR libraries like Surya), so we can quantitatively compare
and iterate on extraction quality.

## Problem

**In your words:**
> This is open R&D to learn which techniques work.

**Distilled:** There is no established answer for which extraction technique
(named VLMs, Claude, or traditional OCR like Surya) best reads hand-written
medical notes and prescriptions. The goal of this phase is **knowledge** — a
fast way to try a technique on an image, score it against a known-correct
answer, and compare techniques — not to solve a specific production workload.
Iteration velocity and comparability matter more than production quality.

## Actors

| Actor | Role / why they touch the system |
|---|---|
| Researcher (you) | Runs the scripts, supplies input images, inspects and judges results, drives iteration. |
| Human ground-truth provider | Supplies the correct/expected extraction for an image so scoring is possible. May in practice be the researcher, but is a distinct role. |
| VLM backend | A pluggable, named vision-language model invoked via `vlm-read file.jpg model-name`; one of the techniques under evaluation. |
| OCR library (Surya) | Traditional OCR engine invoked via `surya-ocr`; another technique under evaluation. |
| Claude (AI) | A distinct extraction backend that also attempts the image and is compared alongside the others. |

## Value proposition

**In your words:**
> Quantitative scoring against ground truth. Ground truth is provided by human.

**Distilled:** Each backend's extraction is scored quantitatively against a
human-provided ground truth, so technique comparisons are measurable rather than
eyeballed. This lets the researcher rank techniques and see where each one
fails, informing which approach to harden later.

## Scope boundary

**In scope (now):**
- Single-image input (one file at a time).
- Three CLI scripts:
  - **(a) `vlm-read`** — extract from an image using a specified VLM model.
  - **(b) `surya-ocr`** — extract from an image using the Surya OCR library.
  - **(c) `compare`** — score/compare backend outputs against ground truth.
- All output written to files.
- A **simple shared JSON envelope** for each extraction *(AI distillation —
  approve at architecture)*: `filename`, `duration` (processing time),
  `model`/`technique` used, and a reasonable structure for the extracted output.
  `compare` consumes these JSON files plus the ground-truth file.

**Non-goals (explicitly NOT building):**
- No web UI.
- No batch processing (single image at a time).
- Not production-hardened code (velocity over polish at this stage).
- Not HIPAA/PII-compliant handling of real patient data (yet).
- Not a training / fine-tuning pipeline.
- Not real-time or API-served extraction.

## Open questions

- Exact JSON schema / field structure for the shared envelope — deferred to
  `/architecture`.
- Precisely which scoring metric(s) `compare` uses against ground truth (exact
  match, field-level accuracy, edit distance, etc.) — deferred to use-case
  interview / architecture.
- How Claude is invoked as a backend (interactive vs. scripted API call) — TBD.
