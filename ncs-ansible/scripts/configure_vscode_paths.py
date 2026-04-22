#!/usr/bin/env python3
"""Rewrite .vscode/settings.json absolute paths to match this checkout.

Idempotent — both `{{NCS_REPO_ROOT}}` placeholders and a prior absolute
path (from an earlier run or a different machine) are reset to the
current checkout's absolute path, preserving flag prefixes like
``--config-file``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDER = "{{NCS_REPO_ROOT}}"

_PATH_RE = re.compile(
    r'("ansible\.(?:python\.interpreterPath|validation\.lint\.(?:path|arguments))"\s*:\s*")'
    r"(?P<body>[^\"]*)"
    r'(")'
)

_PATH_SEGMENT_RE = re.compile(r"(?P<prefix>.*?)(?P<root>\S*)(?P<suffix>/\.venv/\S+|/\.ansible-lint)")


def _rewrite_body(body: str, root: str) -> str:
    return _PATH_SEGMENT_RE.sub(
        lambda m: f"{m.group('prefix')}{root}{m.group('suffix')}",
        body,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(f"usage: {argv[0]} <settings.json> <repo-root>\n")
        return 2
    settings_path = Path(argv[1])
    root = argv[2].rstrip("/")
    raw = settings_path.read_text().replace(PLACEHOLDER, root)
    patched = _PATH_RE.sub(
        lambda m: f"{m.group(1)}{_rewrite_body(m.group('body'), root)}{m.group(3)}",
        raw,
    )
    settings_path.write_text(patched)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
