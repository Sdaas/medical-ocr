# CLAUDE.md — medical-ocr

This project is developed with the global **agentic SDLC** (installed via
`~/.claude`). Follow that process: interview → design → test-first code →
review → ship, human-in-the-loop, effort scaled by tier.

## Project marker

- **Name:** medical-ocr
- **Archetype:** cli
- **Profile (stack):** python
- **Distribution:** none

Use this marker to select the right stack profile without re-asking.

## Ground rules

- Backlog lives in GitHub Issues. Trivial changes go on `main`; everything else
  gets its own branch.
- All testing and release run through `./test.sh` and `./release.sh`.
- Tests must be green before push (pre-push hook) and before merge (CI).
- The curated end-to-end design lives in `design/overview.md` — keep it current;
  record only the **key** decisions, not every one.
