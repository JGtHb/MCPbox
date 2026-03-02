#!/bin/bash
# Bump MCPbox version across all components.
#
# The VERSION file at repo root is the single source of truth.
# This script updates VERSION plus the 4 secondary locations
# (2 pyproject.toml + 2 package.json) and regenerates lock files.
#
# Usage:
#   ./scripts/bump-version.sh <version>              # bump + commit + tag
#   ./scripts/bump-version.sh <version> --no-commit  # bump only
#
# Examples:
#   ./scripts/bump-version.sh 0.3.0
#   ./scripts/bump-version.sh 1.0.0-rc1 --no-commit

set -euo pipefail

VERSION="${1:?Usage: $0 <version> [--no-commit]}"
NO_COMMIT=false

for arg in "${@:2}"; do
    case "$arg" in
        --no-commit) NO_COMMIT=true ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

# Validate semver (X.Y.Z with optional pre-release suffix)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
    echo "ERROR: Invalid version '$VERSION'. Expected format: X.Y.Z or X.Y.Z-tag"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Bumping version to $VERSION..."
echo ""

# 1. VERSION file (source of truth)
printf '%s' "$VERSION" > "$REPO_ROOT/VERSION"
echo "  Updated VERSION"

# 2. Python pyproject.toml files
sed -i.bak "s/^version = \".*\"/version = \"$VERSION\"/" "$REPO_ROOT/backend/pyproject.toml"
rm -f "$REPO_ROOT/backend/pyproject.toml.bak"
echo "  Updated backend/pyproject.toml"

sed -i.bak "s/^version = \".*\"/version = \"$VERSION\"/" "$REPO_ROOT/sandbox/pyproject.toml"
rm -f "$REPO_ROOT/sandbox/pyproject.toml.bak"
echo "  Updated sandbox/pyproject.toml"

# 3. JS package.json files (npm version handles JSON formatting)
(cd "$REPO_ROOT/frontend" && npm version "$VERSION" --no-git-tag-version --allow-same-version > /dev/null)
echo "  Updated frontend/package.json"

(cd "$REPO_ROOT/worker" && npm version "$VERSION" --no-git-tag-version --allow-same-version > /dev/null)
echo "  Updated worker/package.json"

# 4. Regenerate lock files
(cd "$REPO_ROOT/frontend" && npm install --package-lock-only > /dev/null 2>&1)
echo "  Regenerated frontend/package-lock.json"

(cd "$REPO_ROOT/worker" && npm install --package-lock-only > /dev/null 2>&1)
echo "  Regenerated worker/package-lock.json"

echo ""
echo "Version bumped to $VERSION in all locations."

if [ "$NO_COMMIT" = false ]; then
    echo ""
    echo "Creating commit and tag..."
    cd "$REPO_ROOT"
    git add VERSION \
        backend/pyproject.toml \
        sandbox/pyproject.toml \
        frontend/package.json frontend/package-lock.json \
        worker/package.json worker/package-lock.json
    git commit -m "chore: bump version to $VERSION"
    git tag "v$VERSION"
    echo "  Created commit and tag v$VERSION"
    echo "  Push with: git push && git push --tags"
fi
