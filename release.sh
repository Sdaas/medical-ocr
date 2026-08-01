#!/usr/bin/env bash
#
# release.sh — bump version, tag, and push for medical-ocr.
#
# Usage:
#   ./release.sh patch|minor|major
#   ./release.sh --version X.Y.Z
#
# Refuses to run on a dirty tree, off main, or with a failing test suite.
# Keeps VERSION and pyproject.toml version in sync.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT" || exit 1

die() {
	printf 'release.sh: error: %s\n' "$1" >&2
	exit 1
}

[[ $# -ge 1 ]] || die "usage: release.sh patch|minor|major | --version X.Y.Z"

CURRENT="$(head -n1 VERSION)"
IFS='.' read -r MAJOR MINOR PATCH <<<"$CURRENT"

case "$1" in
patch) NEW="$MAJOR.$MINOR.$((PATCH + 1))" ;;
minor) NEW="$MAJOR.$((MINOR + 1)).0" ;;
major) NEW="$((MAJOR + 1)).0.0" ;;
--version)
	NEW="${2:-}"
	[[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "invalid version: $NEW"
	;;
*) die "unknown argument: $1" ;;
esac

[[ "$(git branch --show-current)" == "main" ]] || die "must be on main to release"
[[ -z "$(git status --porcelain)" ]] || die "working tree is dirty — commit first"
if git rev-parse "v$NEW" >/dev/null 2>&1; then
	die "tag v$NEW already exists"
fi

echo "==> running test suite"
./test.sh || die "tests must pass before release"

echo "==> bumping $CURRENT -> $NEW"
printf '%s\n' "$NEW" >VERSION
sed -i.bak "s/^version = \".*\"/version = \"$NEW\"/" pyproject.toml && rm -f pyproject.toml.bak
git add VERSION pyproject.toml
git commit -m "Release v$NEW"
git tag -a "v$NEW" -m "Release v$NEW"

echo "==> pushing"
git push origin main
git push origin "v$NEW"

echo "Released v$NEW"
