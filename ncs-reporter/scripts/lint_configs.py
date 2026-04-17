#!/usr/bin/env python3
"""Lint ncs_reporter YAML configs for style conventions.

Checks:
  - when: and visible_if: values should be unquoted (Ansible convention)
  - compute: values must use "{{ expression }}" (Jinja2 delimiters)
  - widget type: values must use hyphens, not underscores
  - value: references must use Jinja2 delimiters ("{{ var }}")
  - human-readable keys (name:, display_name:, category:) with whitespace
    or punctuation must be double-quoted
  - legacy keys (field:, header:, label:, title:, id:, warn_at:, crit_at:, [badge])
    are rejected — migrate to the renamed forms
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

# Matches value: references — must be Jinja2 expressions ("{{ ... }}")
VALUE_LINE = re.compile(r'^\s+value:\s+(.+?)\s*$')

# Matches any human-readable key that should be quoted when the text contains
# whitespace or non-identifier punctuation.
QUOTED_KEY_LINE = re.compile(r'^\s+(name|display_name|category):\s+(.+?)\s*$')

# Legacy keys rejected post-refactor. Maps each key → the new key authors should use.
LEGACY_KEY_HINTS = {
    "field": "value",
    "header": "name",
    "label": "name (use quoted string)",
    "title": "name",
    "id": "slug",
    "warn_at": "warn_if_above",
    "crit_at": "crit_if_above",
}
LEGACY_KEY_LINE = re.compile(
    r'^\s+(' + "|".join(LEGACY_KEY_HINTS) + r'):\s+'
)

# Keys whose `field:` / `label:` / etc. usage is unrelated to widget schema and
# should be allowed to pass the legacy-key check.
LEGACY_EXEMPT_KEYS = {
    "link_field",
    "rows_field",
    "label_field",
    "value_field",
    "sum_field",
    "split_field",
    "split_name_key",
    "path_prefix",
    "value_label",
    "display_name",
}


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.lstrip()
        is_comment = stripped.startswith("#")

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

        if is_comment:
            continue

        # Check value: must be a Jinja2 expression
        m = VALUE_LINE.match(line)
        if m:
            raw = m.group(1).strip()
            unquoted = raw.strip('"').strip("'")
            if "{{" not in unquoted or "}}" not in unquoted:
                errors.append(
                    f"{path.name}:{i}: value: must use Jinja2 delimiters — "
                    f"'value: {raw}' → 'value: \"{{{{ {unquoted} }}}}\"'"
                )

        # Check for legacy keys (field, header, label, title, id, warn_at, crit_at)
        m = LEGACY_KEY_LINE.match(line)
        if m:
            key = m.group(1)
            if key not in LEGACY_EXEMPT_KEYS:
                # Exclude when the key is a suffix of an exempt key on this line.
                if not any(line.lstrip().startswith(f"{exempt}:") for exempt in LEGACY_EXEMPT_KEYS):
                    errors.append(
                        f"{path.name}:{i}: '{key}:' is no longer supported — "
                        f"rename to '{LEGACY_KEY_HINTS[key]}:'"
                    )

        # Check human-readable keys are quoted when they contain whitespace or punctuation
        m = QUOTED_KEY_LINE.match(line)
        if m:
            key, raw = m.group(1), m.group(2).strip()
            if raw and not (raw.startswith('"') or raw.startswith("'")):
                # Allow bare tokens with no whitespace or punctuation (single identifiers).
                if re.search(r"[\s\-:/&%(),]", raw):
                    errors.append(
                        f"{path.name}:{i}: {key}: string values with whitespace or punctuation must be double-quoted — "
                        f"'{key}: {raw}' → '{key}: \"{raw}\"'"
                    )

        # Legacy badge: true (replaced by `as: status-badge`)
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
