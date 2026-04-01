#!/usr/bin/env bash
# Clean all Python bytecode caches from the repository and collections.
# Run after pulling code changes to avoid stale .pyc files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Cleaning Python bytecode caches..."
find "$REPO_ROOT" \
    -path '*/.*' -prune -o \
    -path '*/.venv*' -prune -o \
    \( -name '__pycache__' -type d -exec rm -rf {} + \) -o \
    \( -name '*.pyc' -delete \) 2>/dev/null || true

# Also clean the symlinked collections path
if [ -d "$REPO_ROOT/collections/ansible_collections/internal" ]; then
    find "$REPO_ROOT/collections/ansible_collections/internal" \
        \( -name '__pycache__' -type d -exec rm -rf {} + \) -o \
        \( -name '*.pyc' -delete \) 2>/dev/null || true
fi

echo "Done."
