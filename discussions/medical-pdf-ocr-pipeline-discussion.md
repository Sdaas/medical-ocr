# Medical PDF/OCR Pipeline — Discovery & Architecture Conversation

*Exported: 1 August 2026*
*Purpose: Co-designing a local-first PDF/OCR pipeline that turns a patient's shoebox of historical medical records into structured, doctor-reviewable information. Discovery + architecture, not a coding session.*
*Companion file: `medical-pdf-ocr-pipeline-plan.md` (the living decision log, assumptions/constraints register, and topic agenda).*

---

## 1. Daas — Project setup

Goal: co-create a PDF/OCR pipeline for the medical domain — identify key use cases, inputs, outputs, components, end-to-end architecture and tradeoffs, and organize this so we can start building. This conversation is discovery and architecture, not code.

**Context:** A patient walks into a doctor's office with a sheaf of old medical records — handwritten prescriptions and doctor notes, more structured medical test reports, and possibly structured typewritten medical history (e.g. from a previous hospitalization).

**Goal:** Convert this shoebox of unstructured information into something structured the doctor can review and manage as "information" about the patient.

**First two slices:**
1. Handwritten doctor notes and prescriptions → structured schema.
2. Medical test reports → structured schema.

**Assumptions:** Documents available as PDF or images. Initial version assumes well-composed, high-quality scans; later we must handle poor-quality images (poor lighting, blur, shake, framing).

**Constraints:** Due to privacy and cost, prefer all conversion done locally. A cloud API may be OK, but no PII may be sent to the cloud.

**Unknowns / points to discuss:**
1. Output schema for the two document types (deep web search for prior art expected).
2. The OCR / data-extraction pipeline — likely two pipelines (handwritten notes vs typed test reports); what are the steps in each.
3. The pipeline should allow multiple strategies that can be configured and evolved over time (e.g. different image-cleaning tools; strategies that extract two or three ways and combine).
4. Front end, UX, security, access control — excluded for now to keep focus.

*"First make sure you understand all this. Then wait for my next instruction."*

---

## 2. Claude — Understanding confirmation

**Core goal.** Turn the shoebox into structured, doctor-reviewable information. First two slices: handwritten notes + prescriptions → schema; typed test reports → schema. Typed hospitalization summaries are a cousin of slice 2.

**Phasing.** v1 assumes clean scans; robustness to blur/lighting/shake/framing is later. Architecture should leave a seam for that stage to grow.

**The constraint that drives everything.** "Local preferred; cloud only if no PII." For medical records this is sharp: a record is essentially all-PII, and you can't reliably de-identify an image before you've read it. So the handwritten slice — where cloud vision models are strongest — is effectively forced fully local, the harder path. The typed-report slice is friendlier: many are native-text PDFs (skip OCR entirely), and scanned ones are more tractable locally.

**The four points, restated.** (1) Output schemas anchored on prior art — FHIR resources plus coding systems (LOINC/UCUM for labs, RxNorm-or-Indian-brand dictionaries for drugs, SNOMED/ICD for findings). (2) Two distinct pipelines. (3) A strategy/plugin architecture — swappable stages, N extractors reconciled. (4) Frontend/UX/security/access-control out of scope.

**Two data-model concerns carried in despite UX being excluded:**
- Every extracted fact needs provenance + confidence + review-status baked into the schema (handwritten drug/dose data without a human check is unsafe → "proposed, pending doctor confirmation").
- "Strategies that evolve" is meaningless without measurement → an eval harness with field-level metrics is part of the architecture.

**Forks flagged for later:** locale/language; schema convergence with the voice pipeline; full-FHIR vs pragmatic-internal; the 24 GB local-model ceiling; implementation stack (Python ML core vs JVM orchestrator).

---

## 3. Daas — Cloud upper-bound eval + deep-dive request

Even though we limit ourselves to local techniques, we should also explore cloud-based techniques on test data to establish an "upper bound" on quality — this is an eval.

Now deep-dive each of the seven topics interactively. For each: summarize your thoughts and the goal outcomes; then discuss; then summarize the conclusion. Move to the next topic only after I say so. I'm new to this, so keep doing deep research on best practices. Let's start.

---

## 4. Claude — Agenda + Topic 1 (Output Schema)

Cloud stays out of the production path but earns its keep as an eval-only "upper bound" on a non-PII/synthetic test set.

**Agenda (deep-dived one at a time):**
1. Output schema
2. Handwritten notes + prescriptions pipeline
3. Typed test-reports pipeline
4. Strategy/plugin architecture
5. Provenance, confidence & human-in-the-loop review
6. Evaluation harness (incl. cloud upper-bound benchmark)
7. Implementation stack & end-to-end architecture

Cross-cutting (woven through, not standalone): locale/language, convergence with the voice pipeline, the 24 GB ceiling.

### Topic 1 — Output Schema

**Two schemas, don't conflate them:** a loose *extraction schema* the pipeline populates (messy-tolerant, carries confidence + original text), and a clean standards-based *canonical schema*. Map extraction → canonical as a final step.

**Prior art.** FHIR is the de facto standard. Prescriptions: MedicationRequest (an order) vs MedicationStatement (a report of medication use, captured during history-taking, sourced e.g. from a prescription the patient brings in) — brought-in records lean toward MedicationStatement. Test reports: DiagnosticReport groups/summarizes results and references one Observation per test (value, unit, reference range, interpretation flag, date, specimen). Coding systems: LOINC (labs), UCUM (units), SNOMED CT (findings/diagnoses), ICD-10/11 (diagnoses), RxNorm (drugs — free, preferred, but US-scoped; India has no national equivalent).

**India angle — ABDM.** India's national digital health program mandates FHIR R4 plus SNOMED CT, LOINC and ICD via the NRCeS Implementation Guide. It ships ready-made document types (Prescription, DiagnosticReport, etc.), and recognizes a maturity ladder — unstructured (scanned), structured (FHIR + narrative), fully structured (FHIR + coding). Documents wrap as a Composition inside a Bundle.

**Recommendation.** Canonical target = FHIR R4 aligned to ABDM/NRCeS; separate loose extraction schema with per-field verbatim/provenance/confidence; coding as a deferred stage (verbatim first); Indian drugs stored verbatim + ingredient mapping later; converge both slices (and the voice pipeline) into one patient model.

**Discussion points A–E:** (A) FHIR canonical fed by a loose internal schema? (B) verbatim-only vs verbatim+coding in v1? (C) converge with the voice pipeline now? (D) MedicationStatement for brought-in prescriptions? (E) Indian drugs as verbatim + ingredient mapping?

---

## 5. Daas — Export request

Asked to export the conversation so far as a markdown file. *(Claude produced the first transcript export.)*

---

## 6. Daas — "Continue"

---

## 7. Claude — Recommendations on A–E

- **A** — Yes to two layers. Commit to FHIR R4 as canonical, but separate that from the profile choice (ABDM vs US Core vs none) and keep the profile a thin swappable layer.
- **B** — Verbatim-first, coding deferred to its own enrichment stage with confidence.
- **D** — MedicationStatement as default for a brought-in shoebox (history, not a live order).
- **E** — Drug name as written, ingredient mapping later via a formulary.
- **C** — (needs your call) lean: shared canonical FHIR target, pipelines independent.
- **Locale** — (needs your call) India, US, or neutral? Drives whether we target ABDM/NRCeS.

---

## 8. Daas — Decisions

- **A.** Agree. Also lock India as the locale — unless converting generic → India is straightforward.
- **B.** Yes.
- **D.** Yes.
- **E.** Yes. Remember an action item to find India's sources of brand-name / generics and their ingredient lists (needs research).
- **C.** Agree — keep pipelines different, both converge at FHIR. Also: we should do a deep dive on FHIR, especially the India variants.
- **Locale.** All India, not US — lock it. In India all medical records, prescriptions, and test reports are in English. The doctor–patient conversation may be in local languages / English / a mix, but we'll deal with that later.

---

## 9. Claude — Locks + Topic 1 conclusion + 1b proposal

**On A (generic → India):** mostly mechanical but not free. Base R4 → ABDM/NRCeS doesn't auto-carry India-specific mandatory identifiers (ABHA/HPR/HFR), stricter required value-set bindings, and the specific document packaging. Since India is locked, design to ABDM/NRCeS now. Caveat: conforming to the *profiles* is not joining the *ABDM network*; and a shoebox record can't supply ABHA/HPR/HFR context, so extract against a relaxed local profile and tighten only at an export boundary.

**On E:** logged as a research action item (candidates: CDSCO, NLEM, Jan Aushadhi, CIMS/MIMS, Tata 1mg).

**English-only is a big simplification:** it pulls all Hindi/Hinglish complexity out of this pipeline (that's the voice project) — English handwriting and English medical vocabulary only.

**Topic 1 conclusion.** Two-layer schema (loose internal → canonical FHIR R4, ABDM/NRCeS-profiled). Verbatim-first, coding deferred. Prescriptions → MedicationStatement; test reports → DiagnosticReport + one Observation per analyte. Drugs verbatim, ingredient-mapped later. Two pipelines converging at FHIR (and with the voice work). Per-field provenance/confidence/review-status throughout.

**Next:** slot the FHIR/India deep dive as Topic 1b.

---

## 10. Daas — "Ok let's continue. Also keep track of key assumptions and constraints that are driving the design."

---

## 11. Claude — Topic 1b (FHIR & the India ABDM/NRCeS variants)

**Canonical anchor:** the NRCeS FHIR IG for ABDM (v6.5.0, FHIR R4). Each source document becomes one FHIR document Bundle — a Composition (cover page + narrative sections) plus the resources it references.

**ABDM's eight HI Types:** OPConsultation, Prescription, DiagnosticReport, DischargeSummary, ImmunizationRecord, WellnessRecord, HealthDocumentRecord, Invoice. Where our docs land:
- Handwritten consult sheet (note + Rx) → **OPConsultation** (sections: Chief Complaints, Diagnosis, Vitals, Medications, Document). Its Medications section absorbs the prescription, so slice 1 collapses to a single target.
- Standalone prescription (meds only) → **Prescription** (Composition + Patient + Practitioner + MedicationRequest per drug).
- Typed lab report → **DiagnosticReport (Lab)** (+ one Observation per analyte + Specimen; LOINC/UCUM).
- Typed hospitalization summary → **DischargeSummary** (seven sections; later slice).
- Catch-all → **HealthDocumentRecord** — minimal (Composition + Patient + Practitioner + Organization + a DocumentReference holding the base64 scan). Literally the shoebox scenario (PHR-style upload of past scanned records).

**Pattern: classify → route → always preserve the scan.** Classify each source doc, route to the matching bundle, always attach the original scan as a DocumentReference; unclassifiable/too-degraded → HealthDocumentRecord.

**This doubles as the maturity spine:** Tier 1 preserved scan → Tier 2 structured typed bundle with narrative → Tier 3 coded (LOINC/UCUM/SNOMED/RxNorm). A doc rests at whatever tier current strategies reach and is promoted later without reshaping.

**MedicationStatement vs Prescription:** both exist as ABDM profiles, but a shoebox Rx is history, not a live order — keep MedicationStatement, don't force the Prescription document type; reserve strict Prescription/MedicationRequest for issuing new prescriptions (out of scope).

**Discussion points 1–4:** classify-route-preserve pattern; fold notes+Rx into OPConsultation; MedicationStatement over Prescription; three-tier maturity backbone.

---

## 12. Daas — "1. Agree  2. Yes  3. Yes  4. Yes."

---

## 13. Claude — Topic 1b conclusion

Each source document → one FHIR document Bundle. Pipeline job = classify → route → always preserve the scan. Consult sheet → OPConsultation (Medications section absorbs the Rx); meds-only → MedicationStatement; lab report → DiagnosticReport (Lab) + Observation-per-analyte + Specimen; hospitalization summary → DischargeSummary (later); unclassifiable → HealthDocumentRecord. Three-tier maturity model (preserved scan → structured typed bundle → coded) is the design backbone the strategy architecture (Topic 4) hooks into. Closes the schema block (Topics 1 + 1b).

**Next:** Topic 2 — the handwritten notes + prescriptions pipeline.

---

## 14. Daas — "Continue"

---

## 15. Claude — Topic 2 (Handwritten notes + prescriptions pipeline)

**Core reality (research).** Handwritten prescription recognition is still an open problem — poor legibility, inconsistent formats, non-standard abbreviations; misreads cause wrong doses and adverse reactions. Two consequences: (1) this pipeline is **assistive, not autonomous** — a doctor reviews the output; (2) the reading tech has shifted from CNN-LSTM/CTC to **vision-language models**. The 2026 caveat: the best OCR models are VLMs — they read layout and handwriting far better than legacy tools, but they **hallucinate and can't report calibrated confidence**, so a validation layer is mandatory for high-stakes documents.

**Recommended pipeline (Pipeline A):**
1. Ingest & page-normalize (decode, split pages, fix orientation, deskew).
2. Preprocess (reader-dependent, swappable) — light for VLMs; binarize/denoise/line-segment for classical OCR on printed regions.
3. Layout / region segmentation — separate printed vs handwritten; tag zones (header, note body, Rx block, signature); yields bounding boxes for provenance.
4. Read / transcribe (per region) — printed → classical OCR (reliable, real confidence); handwritten → local VLM, verbatim.
5. Structure (interpretation) — a local LLM maps verbatim regions to OPConsultation fields; per medication {drug, strength, form, route, frequency, duration, instructions}; normalize sig abbreviations (BD/TDS/OD/HS/SOS, "1-0-1"), keep verbatim alongside.
6. Validate & assemble confidence — fuzzy-match drugs against a formulary (flag unknowns + look-alike/sound-alike), sanity-check dose/frequency; combine signals; safety-critical fields never auto-accept below threshold.
7. Map to FHIR — Tier-2 OPConsultation bundle, meds as MedicationStatement, scan attached, data-absent for missing ABHA/HPR/HFR.
8. Human review — doctor confirms/edits; corrections become ground truth for eval.

**Three design choices:** two passes (transcribe → structure), separating perception from interpretation and preserving verbatim; **confidence assembled** from ensemble agreement + dictionary + printed-OCR scores + self-consistency (VLMs can't self-report it); explicit hallucination guarding via the validation layer.

**Local model choices (24 GB ceiling):** handwriting reader = local VLM (Qwen2.5-VL 7B [Apache-2.0] or Qwen3-VL 8B via MLX on Apple Silicon; olmOCR as an alternative). Printed regions = Tesseract / PaddleOCR / Surya. Structuring = a local instruct LLM. Cloud upper-bound (eval only) = a frontier vision model on synthetic prescriptions.

**Discussion forks:** (1) two-pass default vs single VLM pass; (2) explicit layout stage in v1 or let the VLM read the whole sheet; (3) reader split (VLM for handwriting + classical OCR for printed). Plus recommend ratifying: confidence-by-assembly, and the assistive-with-mandatory-review posture.

---

## 16. Daas — "In the local model choices, what's the difference between handwriting reader and printed regions?"

---

## 17. Claude — The difference

Two different recognition problems.

**Printed regions** = the machine-printed parts (letterhead, doctor name/registration, pre-printed labels like "Name:"/"Age:"/"Date:"/the ℞ symbol, footer, table grids). Regular glyphs → essentially a solved problem; classical OCR (Tesseract) reads clean printed text well, runs light, is deterministic, and gives real per-word confidence.

**Handwriting reader** = the doctor's handwriting (filled-in details, complaints, diagnosis, and crucially drug names/doses/frequencies). Irregular and writer-specific → classical OCR does badly. A VLM does far better (uses context to infer structure and interpret handwriting) at the cost of more compute and careful prompting to avoid hallucination; it's heavier, slower, and gives no calibrated confidence.

**Split = classical OCR for the easy solved part; VLM for the hard unsolved part.** Why separate them even though a VLM can read printed text too: budget (VLM is the bottleneck on 24 GB — let Tesseract harvest the printed scaffolding cheaply); real confidence + determinism on printed content; hallucination containment (classical OCR never invents words). Caveat: the split is an optimization, not a requirement — it needs the layout stage first, and mixed regions (handwriting over printed lines) are messy. On a typical Indian consult sheet almost all clinical value is handwritten; printed labels are mainly anchors for the structuring step.

---

## 18. Daas — "Given an image, do we need to split the image into handwritten and printed parts before giving it to the VLM / OCR? Or will the VLM / OCR handle it automatically?"

---

## 19. Claude — On splitting

Short answer: **no — you don't physically cut the image.** A modern VLM reads a mixed page (printed + handwriting) natively in one shot; layout-aware engines (PaddleOCR, Surya) detect regions internally and read the whole page.

Three different things get lumped under "splitting":
- **Physical cropping** — not required.
- **Region detection / labeling** (where printed vs handwritten bits are, as boxes + labels) — optional; the VLM can do it implicitly, or an explicit layout model can.
- **Engine routing** (printed → Tesseract, handwriting → VLM) — the only thing that actually forces region isolation, and it's optional.

So the decision collapses to: (1) single VLM, whole page (no split) — simplest, right v1 default; or (2) two-engine routing — the cost/reliability optimization needing region isolation first.

Two reasons to want a region/layout step even with one VLM: **provenance** (our schema wants a source box per field; some VLMs — Qwen-VL — can emit boxes, else a layout/OCR pass provides them) and **focus/resolution** (VLMs have a max effective resolution; cropping a dense Rx block can raise accuracy). Recommendation: v1 = one VLM reads the whole sheet; add region detection later for hard confidence on printed parts, reliable provenance boxes, or a resolution boost. Splitting buys routing, provenance, and focus — it does not fix handwriting difficulty.

---

## 20. Daas — "How do you do the region-detection step that routing requires?"

---

## 21. Claude — How to do region detection

Region detection = two jobs: **localize** (find where text is, as boxes) and **type** (label each box printed vs handwritten). Localization is solved; the printed-vs-handwritten typing is what enables routing.

- **Option 1 — Ask the VLM itself (grounding).** Prompt a VLM (Qwen-VL family) to return each region with its box and printed/handwritten label. One call, no extra models, no training — and it also yields the provenance boxes. Downside: spends expensive VLM compute on detection, so no cost saving.
- **Option 2 — Layout engine + a small classifier (the proper routing build).** Run a detector/layout engine (Surya/PaddleOCR) for line/block boxes (these give boxes but don't tell printed from handwritten), then a tiny binary CNN on each crop → printed/handwritten. Lightweight, deterministic, trainable on a few hundred crops. Then route printed → Tesseract, handwritten → VLM. Buys the cost savings and hard confidence on printed parts.
- **Option 3 — Template anchoring.** For a known pre-printed form, register to the template and read fixed coordinate zones. Very reliable but only for fixed layouts (rarely applies to free-form Indian sheets).

**Mixed regions (handwriting over a printed line)** break per-region typing. Rule: route only where a region is cleanly one type; when mixed/ambiguous, send the whole thing to the VLM. Routing is best-effort; the VLM is always the safety net — you never lose by failing to route, you just miss an optimization.

**Recommendation:** for v1, if we route at all, use **Option 1** (VLM grounding) — zero extra models, and it hands us provenance boxes. Graduate to **Option 2** only if the eval (Topic 6) shows routing is worth the moving parts. Skip a dedicated functional zoner (header/note/Rx) for v1 — let the structuring LLM infer each region's role from its content. All one swappable strategy, which is what Topic 4 is built to hold.

---

## Status at export

- **Concluded:** Topic 1 (Output Schema) and Topic 1b (FHIR & ABDM/NRCeS).
- **In progress:** Topic 2 (Handwritten notes + prescriptions pipeline) — discussion forks 1–3 still open; a sub-thread on region detection / image splitting has been worked through (v1 = one VLM reads the whole sheet; routing is a later optimization via VLM grounding, then a detector + small classifier).
- **Pending:** Topics 3–7.
- See `medical-pdf-ocr-pipeline-plan.md` for the decision log, the A1–A6 / C1–C7 assumptions-and-constraints register, and the topic agenda.

*End of exported conversation.*
