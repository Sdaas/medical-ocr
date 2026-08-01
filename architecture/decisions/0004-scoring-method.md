# ADR-0004 — Scoring method

- **Status:** proposed
- **Date:** 2026-08-01
- **Serves:** UC-005

## Context

`compare` must produce a quantitative score of a backend's `fields` against
ground truth. The researcher specified **field-level accuracy with exact-match
inside each field**, "revisit as needed." Handwriting means real outputs will
have near-misses, so how strict "exact" is matters.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Strict exact string match per field** | Simplest; unambiguous; matches the stated ask | Punishes trivial differences (case, whitespace, "5mg" vs "5 mg") |
| **B — Normalized exact match (trim + lowercase + collapse whitespace), then equal** | Still exact-match semantics; avoids spurious misses; cheap | Normalization rules are a small judgment call |
| **C — Fuzzy / edit-distance similarity per field** | Tolerant of handwriting near-misses; graded score | More than asked for now; threshold tuning; less interpretable |

**Comparison metric:** **fidelity to the stated requirement (exact-match,
field-level accuracy) while not miscounting trivially-equal values.**

## Decision

**Chosen: Option B — normalized exact match per field**; overall score =
correct fields / total ground-truth fields. Keep Option C (fuzzy) as a
flagged/future mode.

**Why (one line):** It honors the "exact-match, field-level accuracy" requirement
while removing false negatives from formatting noise — and stays easy to revisit.

## Consequences

- `compare` reports per-field correct/incorrect + an overall accuracy per backend.
- Normalization = strip, lowercase, collapse internal whitespace (documented and
  easy to change).
- List/nested fields (e.g. `medications`) scored element-/leaf-wise; exact rule
  for nesting to be finalized during the `compare` feature build.
- Fuzzy scoring is a later opt-in, not built now (deferral discipline).
