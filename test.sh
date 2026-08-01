#!/usr/bin/env bash
#
# test.sh — single test entrypoint for medical-ocr.
# Runs ruff (lint + format check) then pytest. Non-zero on any failure.
# This is what the pre-push hook and CI both call.
#
# Dev dependency: uv (https://docs.astral.sh/uv/).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT" || exit 1

if ! command -v uv >/dev/null 2>&1; then
	echo "ERROR: uv not found (dev dependency). Install it:" >&2
	echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
	echo "  brew install uv        # macOS" >&2
	exit 1
fi

FAILED=0

echo "==> uv sync"
if ! uv sync --quiet --extra dev; then
	echo "    uv sync FAILED"
	exit 1
fi

echo "==> ruff (lint)"
if uv run ruff check .; then
	echo "    clean"
else
	echo "    ruff FAILED"
	FAILED=1
fi

echo "==> ruff (format check)"
if uv run ruff format --check .; then
	echo "    clean"
else
	echo "    format FAILED (run: uv run ruff format .)"
	FAILED=1
fi

echo "==> pytest"
if uv run pytest -q; then
	echo "    tests passed"
else
	echo "    tests FAILED"
	FAILED=1
fi

echo
if [[ "$FAILED" -eq 0 ]]; then
	echo "ALL TESTS PASSED"
else
	echo "TESTS FAILED"
fi
exit "$FAILED"
