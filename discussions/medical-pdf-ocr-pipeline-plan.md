# Medical PDF/OCR Pipeline — Working Plan

*Last updated: 1 August 2026*
*Status: Discovery & architecture. Topics 1, 1b, 2, 3, 4, and 5 concluded; Topic 6 next.*

## Context

Convert a patient's shoebox of historical medical records — handwritten doctor notes + prescriptions, typed lab/test reports, and typed hospitalization summaries — into structured, doctor-reviewable "information about the patient." Local-first for privacy and cost. Frontend, UX, security, and access control are out of scope for this discussion.

## Locked cross-cutting decisions

- **Locale is India.** All documents are written in English, so the document OCR pipeline is English-only. Multilingual doctor–patient conversation belongs to the separate voice project.
- **Canonical output is HL7 FHIR R4, conforming to the shape of India's ABDM / NRCeS FHIR profiles** — the profile shapes, not the ABDM network machinery (ABHA/consent/HIP-HIU gateways).
- **Cloud is eval-only** — a quality upper-bound benchmark on non-PII / synthetic data, never in the production path.

## Assumptions & constraints driving the design

*Key assumptions — revisit if any becomes false:*

- **A1** — Inputs arrive as PDF or image files.
- **A2** — v1 assumes well-composed, high-quality scans; poor-quality input (blur, lighting, shake, framing, phone-photos of printouts) is a later robustness phase.
- **A3** — All documents are in English. (Strong driver: the OCR pipeline is English-only.)
- **A4** — Documents are one of: handwritten consult notes / prescriptions, typed lab-test reports, typed hospitalization / discharge summaries.
- **A5** — A ".pdf" file does not imply extractable text. Typed reports arrive as born-digital PDFs (trustworthy text layer), image-only PDFs (a scan/photo wrapped as .pdf), searchable PDFs (a lossy embedded OCR overlay), or mixed. Route on whether a *trustworthy born-digital text layer* exists, not on the file extension.
- **A6** — A doctor reviews extracted output before it is trusted; no unsupervised clinical use.

*Key constraints — hard boundaries:*

- **C1** — No PII may leave the device; production conversion is local-first.
- **C2** — Cloud is permitted only as an eval-only upper-bound benchmark on non-PII / synthetic data.
- **C3** — Cost pressure reinforces local-first.
- **C4** — Local compute ceiling: Mac Mini M4 Pro, 24 GB unified memory (caps local model / VLM size).
- **C5** — Locale is India → ABDM/NRCeS FHIR R4 shapes and SNOMED/LOINC/ICD coding; no national drug-code standard (drug coding is the weak spot).
- **C6** — Clinical safety: every extracted fact carries provenance + confidence + review status; coded values never replace the preserved verbatim source.
- **C7** — Out of scope here: frontend, UX, security, access control, and ABDM network integration.

## Topic 1 — Output Schema (CONCLUDED)

- **Two-layer schema.** Pipelines emit a loose internal extraction schema; a final mapping stage converts it to the canonical FHIR R4 (ABDM/NRCeS-profiled) model.
- **Per-field provenance:** value, verbatim text, source-region pointer (page + bbox), confidence, producing strategy, review status.
- **Verbatim-first.** Coding to LOINC / UCUM / SNOMED CT / ICD / RxNorm is a separate, later enrichment stage with its own confidence.
- **Prescriptions → MedicationStatement; test reports → DiagnosticReport** + one Observation per analyte; scanned original linked as Binary / DocumentReference.
- **Drugs:** name verbatim; ingredient mapped later via an India brand→generic→ingredient formulary.
- **Pipelines independent but converge on FHIR** (and with the voice project).
- **Legacy-record relaxation:** relaxed local profile (data-absent reasons) for missing ABHA/HPR/HFR; tighten only at an export boundary.

## Topic 1b — FHIR & ABDM/NRCeS (CONCLUDED)

- **Canonical anchor:** the NRCeS FHIR IG for ABDM (R4). Each source document → one FHIR *document* Bundle (Composition + referenced resources).
- **Classify → route → always-preserve-scan.** Route to the matching ABDM HI-type bundle; attach the scan as a DocumentReference; unclassifiable/too-degraded → HealthDocumentRecord (also the Tier-1 form for every doc).
- **Routing:** consult sheet (note + Rx) → OPConsultation; meds-only → MedicationStatement; lab report → DiagnosticReport (Lab); hospitalization summary → DischargeSummary (later); unknown → HealthDocumentRecord.
- **Three-tier maturity backbone:** Tier 1 preserved scan → Tier 2 structured typed bundle → Tier 3 coded. Promote later without reshaping.

## Topic 2 — Handwritten notes + prescriptions pipeline (CONCLUDED)

- **v1 = lean two-pass path, one reader, no routing:** ingest/normalize → light preprocess → one local VLM (Qwen2.5-VL 7B / Qwen3-VL 8B via MLX) transcribes the whole sheet verbatim (grounding boxes where possible) → local LLM structures into OPConsultation fields → validate + assemble confidence (formulary match, LASA flags, dose sanity) → map to FHIR Tier-2 OPConsultation (meds as MedicationStatement) → human review.
- **No separate layout/region stage in v1.** Region detection is a deferred optimization (VLM grounding first, then detector + small printed/handwritten classifier).
- **Confidence assembled** (agreement + dictionary + self-consistency), since VLMs can't self-report it.
- **Posture:** assistive, mandatory doctor review.
- **Deferred to Topic 4:** region detection + routing, classical-OCR-for-printed, single-pass image→schema reader, multi-reader ensembles.

## Topic 3 — Typed test-reports pipeline (CONCLUDED)

- **The hard part flips** to table structure + format heterogeneity.
- **Step 0 — text-layer detector. Branch on whether a *trustworthy born-digital text layer* exists — not on file extension.** Traps: image-only PDFs, searchable/OCR'd PDFs, mixed PDFs.
  - **Strategy A — born-digital:** deterministic text + table-coordinate extraction (pdfplumber / PyMuPDF / camelot). No OCR, confidence ≈ 1.0, CPU-cheap.
  - **Strategy B — round-tripped / scanned:** full perception pipeline (geometric correction + OCR/VLM + table-structure recovery); confidence from OCR scores + cross-field consistency.
- **Both converge** into: structure → normalize → validate → map-to-FHIR → review.
- **Target per row = one Observation** {test name, value, unit, reference range, flag} + method + specimen; grouped under panels → DiagnosticReport(s); plus report metadata.
- Capture the report's **printed reference ranges verbatim** (not canonical).
- **Validation superpower = cross-field consistency** (value/range/flag agree; unit fits analyte; value parses) + **critical-value flagging**.
- **v1 scope:** born-digital + clean flatbed scans; phone-photos/degraded round-trips deferred to the robustness phase (A2).
- **Searchable-PDF layers: don't trust blindly** — re-OCR / verify ourselves.
- **Deferred to Topic 4:** rules-per-lab-template extractor, VLM fallback, ensembles, confidence routing.

## Topic 4 — Strategy / plugin architecture (CONCLUDED)

- **Thin custom orchestration skeleton.** Typed stages with input/output contracts; strategy pattern per stage; a strategy registry (name → implementation); config-driven pipeline assembly. Both pipelines are **configs of one framework** sharing the tail (structure → normalize → validate → map-to-FHIR → review). Third-party tools (Docling, pdfplumber, PaddleOCR, LiteLLM, VLMs) are **plugins, not the spine**.
- **Two config-selected composition modes:** **cascade / fallback** (cost-aware, cheap-first then escalate — the production default given C4) and **ensemble / parallel + reconcile** (for safety-critical fields + eval).
- **Reconciliation:** derive **confidence from agreement, not model self-report** (LLMs are overconfident). Match the method to the output type — **confidence-weighted voting for discrete/numeric** (lab values, doses), **alignment / consensus-entropy for free-text** (handwriting, prose); **LLM-as-Fuser** as an optional cautious plugin. Diversity from multi-model *and* test-time augmentation (same model, augmented image variants). The reconciler is itself a pluggable strategy.
- **Privacy as architecture:** every strategy carries **policy tags** (`local-only` / `cloud-eval-only` / `pii-safe` / `cost`). Pipeline assembly **enforces C1/C2 by construction** — production (PII) pipelines can only select `local-only` strategies; cloud strategies are usable solely in eval pipelines on synthetic data. A LiteLLM-style backend router makes local-vs-cloud a swap behind one interface; the tag gates whether it's allowed.
- **Provenance / trace plumbing:** every stage output carries strategy + confidence + source region; reconciliation records the agreement rationale; intermediate artifacts are captured per stage per strategy (feeds Topics 5 & 6).
- **Evolution loop:** registry + config + eval harness → drop in a new strategy, evaluate against the test set, promote it in config if it wins.
- **v1 posture: build the seams, not the machinery.** Ship the interfaces (typed stages, registry, config assembly, policy tags, provenance plumbing) with **one default strategy per stage** (the Topic 2/3 defaults). Defer the ensemble/reconciliation machinery until the eval shows where it pays.

## Topic 5 — Provenance, confidence & human-in-the-loop review (CONCLUDED)

- **Provenance — two layers.** Internal extraction schema per field (source-doc id, page, bounding box, verbatim text, producing strategy + model name/version, pipeline run/config id, timestamp, and the reconciliation rationale for ensembled fields); a canonical **FHIR Provenance resource** linked to each generated Observation / MedicationStatement (machine-derived from doc X by agent Y at time Z; later, clinician amendment). Mark machine origin with a **machine-derived modifier extension (algorithm + version)** and a **confidence extension** per element (the SMART Text2FHIR-proven pattern). **Immutable append** — keep both the machine proposal and the human amendment; the delta is the error signal.
- **Confidence — per-field, agreement-based, calibrated.** Assembled from agreement + validation signals + OCR/native scores, not the model's self-report. Field-type-aware (voting for numeric, consensus for free-text). Calibrated and measured (reliability / ECE against review-confirmed truth). Accept-vs-review **thresholds tuned empirically** on labeled data (a Topic 6 dependency). **Abstention ("unsure / illegible") is a first-class output** that routes to review, never a silent guess.
- **Review — the workflow contract.** Per-field lifecycle: proposed → (auto-accepted | queued-for-review) → confirmed | corrected | rejected, mapped to FHIR status; the reviewer becomes an author on the Provenance. **Triage:** safety-critical fields (drug, dose, critical-value labs) **always reviewed regardless of confidence**; others routed by tuned threshold + validation failure + ensemble disagreement + abstention; everything else auto-accepts with provenance recorded. **Field-level granularity**, each flagged field shown with its source region + verbatim. **Human-in-the-loop for v1**, with a tunable path to **human-on-the-loop** as calibration proves out.
- **Feedback loop:** every correction is captured as labeled ground truth → feeds Topic 6 (accuracy, calibration, threshold tuning, drift monitoring) and the Topic 4 evolution loop (few-shot exemplars, fine-tuning data, rule fixes).

## Open questions

- Which relaxed-profile rules we accept for records missing ABHA / HPR / HFR context (settle at mapping/implementation).

## Action items / TODO

- **Research India drug references** for brand↔generic mappings and ingredient lists (candidates: CDSCO, NLEM, Jan Aushadhi, CIMS / MIMS India, Tata 1mg). Feeds the deferred drug-coding / formulary stage.
- Proceed through the remaining topics one at a time; conclude each before advancing.

## Topic agenda and status

1. Output schema — **CONCLUDED**
   - 1b: FHIR & ABDM/NRCeS profile deep dive — **CONCLUDED**
2. Handwritten notes + prescriptions pipeline — **CONCLUDED**
3. Typed test-reports pipeline — **CONCLUDED**
4. Strategy / plugin architecture — **CONCLUDED**
5. Provenance, confidence & human-in-the-loop review — **CONCLUDED**
6. Evaluation harness (metrics, test sets, cloud upper-bound benchmark) — **NEXT**
7. Implementation stack & end-to-end architecture
