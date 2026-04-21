#!/usr/bin/env python3
"""Rewrite .vscode/settings.json absolute paths to match this checkout.

Idempotent: both the literal placeholder `{{NCS_REPO_ROOT}}` and a prior
absolute path (from a previous run or a different machine) are reset to
the current checkout's absolute path. Flag prefixes like `--config-file`
are preserved.

Used by the `just configure-vscode` and `just setup-all` recipes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDER = "{{NCS_REPO_ROOT}}"

# Keys whose values embed an absolute repo path that must track the checkout.
# Each regex matches a single JSON string value and captures the flag prefix
# (if any), the absolute path body, and the suffix segment (.venv/... or
# .ansible-lint) so we can drop in the new root without clobbering the prefix.
_PATH_RE = re.compile(
    r'("ansible\.(?:python\.interpreterPath|validation\.lint\.(?:path|arguments))"\s*:\s*")'
    r"(?P<body>[^\"]*)"
    r'(")'
)

# Anything ending in /.venv/... or /.ansible-lint is a path we manage.
_PATH_SEGMENT_RE = re.compile(r"(?P<prefix>.*?)(?P<root>[^ ]*)(?P<suffix>/\.venv/\S+|/\.ansible-lint)")


def rewrite(value: str, root: str) -> str:
    """Rewrite a single JSON string value so any absolute repo path becomes *root*."""
    # Simple placeholder substitution handles first-run and any comment copies.
    value = value.replace(PLACEHOLDER, root)

    def _patch(m: re.Match[str]) -> str:
        return f"{m.group('prefix')}{root}{m.group('suffix')}"

    return _PATH_SEGMENT_RE.sub(_patch, value)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(f"usage: {argv[0]} <settings.json> <repo-root>\n")
        return 2
    settings_path = Path(argv[1])
    root = argv[2].rstrip("/")
    raw = settings_path.read_text()

    # First, run the placeholder substitution across the whole file (covers
    # comments and any other occurrence).
    raw = raw.replace(PLACEHOLDER, root)

    def _rewrite_match(m: re.Match[str]) -> str:
        lhs, body, rhs = m.group(1), m.group("body"), m.group(3)
        return f"{lhs}{rewrite(body, root)}{rhs}"

    patched = _PATH_RE.sub(_rewrite_match, raw)
    settings_path.write_text(patched)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
