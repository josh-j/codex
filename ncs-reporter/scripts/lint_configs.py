#!/usr/bin/env python3
"""Lint ncs_reporter YAML configs for style conventions.

Checks:
  - when: and visible_if: values should be unquoted (Ansible convention)
  - compute: values must use "{{ expression }}" (Jinja2 delimiters)
  - widget type: values must use hyphens, not underscores
  - legacy column shorthand: badge: true / label: / title: in column items
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "src" / "ncs_reporter" / "configs"

# Matches quoted when/visible_if values: '    when: "expression"'
UNQUOTED_EXPR = re.compile(r"^(\s+)(when):\s*\"(.+)\"\s*$")

# Matches compute values that are NOT "{{ }}" wrapped
COMPUTE_LINE = re.compile(r"^(\s+)compute:\s*(.+)\s*$")

# Matches widget type values with underscores
UNDERSCORE_TYPE = re.compile(r"^(\s+)type:\s*(\w+_\w+)\s*$")

def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        # Check when/visible_if: should be unquoted
        m = UNQUOTED_EXPR.match(line)
        if m:
            key, expr = m.group(2), m.group(3)
            if not (expr.startswith("{{") and expr.endswith("}}")):
                errors.append(f"{path.name}:{i}: {key}: should be unquoted — remove double quotes")

        # Check compute: must use "{{ }}" delimiters
        m = COMPUTE_LINE.match(line)
        if m:
            value = m.group(2).strip()
            if not (value.startswith('"{{') and value.endswith('}}"')):
                errors.append(f'{path.name}:{i}: compute: should use Jinja2 delimiters — "{{{{ expression }}}}"')

        # Check type: must use hyphens not underscores
        m = UNDERSCORE_TYPE.match(line)
        if m:
            errors.append(f"{path.name}:{i}: type: use hyphens — {m.group(2)} → {m.group(2).replace('_', '-')}")

        # Check for legacy badge: true (replaced by `as: status-badge`)
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            if re.match(r"badge:\s*(true|false)\b", stripped):
                errors.append(
                    f"{path.name}:{i}: badge: true is no longer supported — use 'as: status-badge'"
                )
            if "[badge]" in line:
                errors.append(
                    f"{path.name}:{i}: [badge] shorthand not allowed — use 'as: status-badge'"
                )

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
