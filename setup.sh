#!/usr/bin/env bash
#
# setup.sh — check for (and optionally install) medical-ocr's developer dependencies.
#
# Checks each tool with `command -v`. If any are missing on macOS, it offers to
# install them with Homebrew (prompts unless --yes). Off macOS, or without brew,
# it prints what to install and exits non-zero so the gap is obvious to CI too.
#
# Usage:
#   ./setup.sh            check deps; prompt before installing anything missing
#   ./setup.sh --yes      install missing deps without prompting (non-interactive)
#   ./setup.sh --help     show this help
#
# Exit status: 0 when all deps are present (or were installed); non-zero otherwise.

set -uo pipefail

# Developer dependencies. One per line: "command|brew-formula|human name".
# The brew formula is only used on macOS; the command name is what we probe for.
DEPS=(
	"git|git|Git"
	"gh|gh|GitHub CLI"
	"uv|uv|uv (Python)"
)

# Optional runtime tools — NOT required to build or test, but some features need
# them. Reported as advisory only; a missing one never changes the exit status.
# One per line: "command|human name|used by".
OPTIONAL_TOOLS=(
	"claude|Claude Code CLI|claude-extract (Claude in-session extraction)"
)

ASSUME_YES=false

usage() { sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; }

# OS name — overridable via _SETUP_UNAME so the non-macOS path is testable.
os_name() { printf '%s' "${_SETUP_UNAME:-$(uname -s)}"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- args -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
	case "$1" in
	--yes | -y) ASSUME_YES=true ;;
	--help | -h) usage; exit 0 ;;
	*) printf 'setup.sh: unknown argument: %s (try --help)\n' "$1" >&2; exit 2 ;;
	esac
	shift
done

# --- check ------------------------------------------------------------------
echo "==> Checking developer dependencies"
missing=()
for entry in "${DEPS[@]}"; do
	IFS='|' read -r cmd formula name <<<"$entry"
	if have "$cmd"; then
		printf '    \xe2\x9c\x93 %s (%s)\n' "$name" "$cmd"
	else
		printf '    \xe2\x9c\x97 %s (%s) — missing\n' "$name" "$cmd"
		missing+=("$entry")
	fi
done

# --- advisory: optional runtime tools (never blocks setup) ------------------
echo "==> Checking optional runtime tools (advisory)"
for entry in "${OPTIONAL_TOOLS[@]}"; do
	IFS='|' read -r cmd name usedby <<<"$entry"
	if have "$cmd"; then
		printf '    \xe2\x9c\x93 %s (%s)\n' "$name" "$cmd"
	else
		printf '    \xe2\x97\x8b %s (%s) — not found; needed only for %s\n' "$name" "$cmd" "$usedby"
	fi
done

if [[ ${#missing[@]} -eq 0 ]]; then
	echo "All developer dependencies present."
	exit 0
fi

# --- report the gap ---------------------------------------------------------
formulae=()
for entry in "${missing[@]}"; do
	IFS='|' read -r cmd formula name <<<"$entry"
	formulae+=("$formula")
done

echo
echo "Missing: ${formulae[*]}"

if [[ "$(os_name)" != "Darwin" ]]; then
	echo "This installer automates macOS (Homebrew) only. Install the tools above"
	echo "with your system package manager, then re-run ./test.sh."
	exit 1
fi

if ! have brew; then
	echo "Homebrew not found. Install it from https://brew.sh then re-run ./setup.sh."
	exit 1
fi

# --- install (with consent) -------------------------------------------------
if ! $ASSUME_YES; then
	printf "Install with 'brew install %s'? [y/N] " "${formulae[*]}"
	read -r reply || reply=""
	case "$reply" in
	[yY] | [yY][eE][sS]) ;;
	*) echo "Skipped. Install the tools above, then re-run ./test.sh."; exit 1 ;;
	esac
fi

echo "==> brew install ${formulae[*]}"
if brew install "${formulae[@]}"; then
	echo "Done. Re-run ./test.sh to verify."
	exit 0
else
	echo "brew install failed — see output above." >&2
	exit 1
fi
