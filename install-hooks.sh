#!/usr/bin/env bash
#
# install-hooks.sh — symlink this repo's hooks/ into .git/hooks. Run once after cloning.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_SRC="$REPO_ROOT/hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

if [[ ! -d "$HOOKS_DST" ]]; then
	echo "install-hooks.sh: not a git repo (no .git/hooks)" >&2
	exit 1
fi

for hook in "$HOOKS_SRC"/*; do
	name="$(basename "$hook")"
	ln -sf "../../hooks/$name" "$HOOKS_DST/$name"
	chmod +x "$hook"
	echo "installed hook: $name"
done

echo "hooks installed."
