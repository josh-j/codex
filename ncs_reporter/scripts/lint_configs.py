#!/usr/bin/env python3
"""Lint ncs_reporter YAML configs for style conventions.

Checks:
  - when: and visible_if: values should not be double-quoted
  - style_rules when: values should not be double-quoted
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "src" / "ncs_reporter" / "configs"

EXPRESSION_KEYS = re.compile(r"^(\s+)(when|visible_if):\s*\"(.+)\"\s*$")


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        m = EXPRESSION_KEYS.match(line)
        if m:
            key, expr = m.group(2), m.group(3)
            # Allow "{{ }}" wrapped expressions (needed for YAML-unfriendly chars)
            if expr.startswith("{{") and expr.endswith("}}"):
                continue
            errors.append(f"{path.name}:{i}: {key}: should be unquoted — remove double quotes")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in sorted(CONFIGS_DIR.glob("*.yaml")):
        errors.extend(lint_file(path))

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n{len(errors)} style violation(s) found.", file=sys.stderr)
        return 1

    print("Config lint: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
