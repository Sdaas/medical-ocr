# ADR-0003 — Ground-truth file convention

- **Status:** proposed
- **Date:** 2026-08-01
- **Serves:** UC-004, UC-005

## Context

The human hand-authors the correct extraction for an image, and `compare` must
locate it reliably. We need a convention for where the truth file lives and what
shape it has.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **A — Sidecar `<image>.truth.json` next to the image** | Zero config; obvious pairing; easy to eyeball | Clutters the image dir |
| **B — Central `ground-truth/<image>.json` dir** | Keeps truth separate/organized | Indirection; must keep names in sync |
| **C — Path passed explicitly to `compare --truth`** | No convention needed; fully flexible | Manual every run; no automatic pairing for `run-all` |

**Comparison metric:** **least friction to pair truth with an image at compare
time** (velocity), while staying scriptable for `run-all`.

## Decision

**Chosen: Option A — sidecar `<image>.truth.json`**, with Option C's explicit
`--truth <path>` supported as an override.

**Why (one line):** Automatic image↔truth pairing with no bookkeeping is the
lowest-friction path, and the explicit flag covers the exceptions.

## Consequences

- `compare` defaults to looking for `<image>.truth.json`; `--truth` overrides.
- Truth file uses the ADR-0002 `fields` shape (metadata optional).
- Revisit a central dir if the image directory becomes unwieldy.
