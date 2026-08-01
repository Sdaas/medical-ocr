# Use-Case Catalog — medical-ocr

> Produced by `/discovery`. Each use case is something an actor must be able to
> *do*. Gate: every use case has a priority and a testable "done when"; each
> traces to an actor; no orphans. Architecture will trace components back to
> these IDs — keep the IDs stable.

## Priority legend

- **P0** — core; the product is pointless without it.
- **P1** — important; shipped soon after core.
- **P2** — later / deferred (deferral discipline: peripheral after core).

## Shared conventions (AI distillation — approve at architecture)

- **Extraction envelope:** every backend writes a JSON file containing at least
  `filename`, `duration` (processing time), `model`/`technique`, and a reasonable
  structure for the extracted fields.
- **Ground truth:** a hand-authored JSON file matching the extraction output
  structure, associated with the image (naming convention e.g.
  `file.jpg` → `file.truth.json` — exact convention TBD at architecture).

---

## UC-001 — Extract from an image via a VLM

- **Actor:** Researcher (invokes) + VLM backend (performs)
- **Priority:** P0
- **Trigger:** Researcher runs `vlm-read file.jpg model-name`.

**Main flow (distilled):**
1. Researcher points the script at an image and names a VLM model.
2. Script sends the image to the named VLM and requests structured extraction.
3. Script measures processing duration.
4. Script writes the extraction envelope JSON to a file.

- **Pre-conditions:** Image file exists; the named VLM model is reachable/configured.
- **Post-conditions:** A JSON file exists with extracted fields, `duration`,
  `filename`, and `model`.
- **Done when:** Running `vlm-read file.jpg model-name` produces a JSON file
  containing the extracted fields plus `filename`, `duration`, and `model`.

---

## UC-002 — Extract from an image via Surya OCR

- **Actor:** Researcher (invokes) + OCR library / Surya (performs)
- **Priority:** P1
- **Trigger:** Researcher runs `surya-ocr file.jpg`.

**Main flow (distilled):**
1. Researcher points the script at an image.
2. Script runs Surya OCR over the image.
3. Script measures processing duration.
4. Script writes the extraction envelope JSON to a file.

- **Pre-conditions:** Image file exists; Surya is installed/available.
- **Post-conditions:** A JSON file exists with Surya's extracted text/fields,
  `duration`, `filename`, and `technique`.
- **Done when:** Running `surya-ocr file.jpg` produces a JSON file containing
  Surya's output plus `filename`, `duration`, and `technique`.

---

## UC-003 — Extract from an image via Claude

- **Actor:** Researcher (invokes) + Claude / AI (performs)
- **Priority:** P1
- **Trigger:** Researcher points Claude at an image file in-session.

**Main flow (distilled):**
1. Researcher points Claude at the image file.
2. Claude extracts the structured data from the image.
3. Claude saves the result to a JSON file in a reasonable structure matching the
   shared envelope.

- **Pre-conditions:** Image file exists and is readable by Claude.
- **Post-conditions:** A JSON file exists with Claude's extracted fields in the
  shared envelope structure.
- **Done when:** After pointing Claude at an image, a JSON file exists with the
  extracted fields plus `filename` and `technique` (= Claude).

---

## UC-004 — Provide ground truth for an image

- **Actor:** Human ground-truth provider
- **Priority:** P0
- **Trigger:** A new image needs a known-correct answer for scoring.

**Main flow (distilled):**
1. Human inspects the image.
2. Human hand-authors a JSON file with the correct extraction, matching the
   shared output structure.
3. The ground-truth file is associated with the image.

- **Pre-conditions:** Image file exists; the expected field structure is agreed.
- **Post-conditions:** A hand-authored ground-truth JSON file exists for the image.
- **Done when:** A ground-truth JSON file exists for the image and can be located
  by `compare`.

---

## UC-005 — Compare and score backend outputs against ground truth

- **Actor:** Researcher
- **Priority:** P0
- **Trigger:** Researcher runs `compare` on one or more backend output files plus
  the ground-truth file.

**Main flow (distilled):**
1. Researcher runs `compare` pointing at backend output JSON(s) and the
   ground-truth JSON.
2. Script computes field-level accuracy with exact-match inside each field.
3. Script writes a comparison/score result to a file.

- **Pre-conditions:** At least one backend output JSON and a ground-truth JSON
  exist for the same image.
- **Post-conditions:** A comparison result file exists reporting per-field
  correctness and an overall field-level accuracy score per backend.
- **Done when:** Running `compare` on backend output(s) + ground truth produces a
  file reporting field-level accuracy (exact-match per field) for each backend.

---

## UC-006 — Run all backends on one image at once

- **Actor:** Researcher
- **Priority:** P2
- **Trigger:** Researcher wants every available backend's output for one image in
  a single command.

**Main flow (distilled):**
1. Researcher issues one command naming an image.
2. The tool invokes each available backend (VLM, Surya, and where applicable
   Claude) on the image.
3. Each backend's envelope JSON is written to a file.

- **Pre-conditions:** Image exists; the relevant backends are configured/available.
- **Post-conditions:** One envelope JSON file per backend exists for the image.
- **Done when:** A single command over one image yields one output JSON per
  available backend.
