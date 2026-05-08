#!/usr/bin/env python3
"""Lint ncs_reporter YAML configs for style + field-reference conventions.

Style checks:
  - when: and visible_if: values should be unquoted (Ansible convention)
  - compute: values must use "{{ expression }}" (Jinja2 delimiters)
  - widget type: values must use hyphens, not underscores
  - value: references must use Jinja2 delimiters ("{{ var }}")
  - human-readable keys (name:, display_name:, category:) with whitespace
    or punctuation must be double-quoted
  - retired keys (field:, header:, label:, title:, id:, warn_at:, crit_at:, [badge])
    are rejected — migrate to the renamed forms

Field-reference check:
  - Jinja identifiers used in alerts/widgets/config that look like 1-char
    typos of declared fields (singular/plural mismatches, etc.) are flagged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, meta

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIRS = sorted(REPO_ROOT.glob("ncs-ansible-*/ncs_configs"))
assert CONFIG_DIRS, (
    f"lint_configs expected at least one ncs-ansible-*/ncs_configs dir under {REPO_ROOT!r}; "
    "the scan would silently no-op if the layout changes."
)

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

# Retired keys rejected post-refactor. Maps each key to the supported key authors should use.
RETIRED_KEY_HINTS = {
    "field": "value",
    "header": "name",
    "label": "name (use quoted string)",
    "title": "name",
    "id": "slug",
    "warn_at": "warn_if_above",
    "crit_at": "crit_if_above",
}
RETIRED_KEY_LINE = re.compile(
    r'^\s+(' + "|".join(RETIRED_KEY_HINTS) + r'):\s+'
)

# Keys whose `field:` / `label:` / etc. usage is unrelated to widget schema and
# should be allowed to pass the retired-key check.
RETIRED_EXEMPT_KEYS = {
    "link_field",
    "rows_field",
    "label_field",
    "value_field",
    "split_field",
    "split_name_key",
    "path_prefix",
    "value_label",
    "display_name",
}


_NORMALIZE_LINE = re.compile(r"^(\s*)normalize:\s*(.*)$")


def lint_file(path: Path) -> list[str]:
    errors: list[str] = []
    # Track indentation depth of any open `normalize:` block so style
    # checks targeted at widget/alert keys (value:, name:, field:) skip
    # lines nested inside it — `value:` is also a DSL operator key in
    # `normalize:` (regex_replace, index, lookup, …) and should not be
    # flagged by the Jinja-delimiter check.
    normalize_indent: int | None = None

    for i, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        is_comment = stripped.startswith("#")

        m = _NORMALIZE_LINE.match(line)
        if m and not is_comment:
            normalize_indent = indent
        elif normalize_indent is not None and stripped and not is_comment and indent <= normalize_indent:
            normalize_indent = None
        in_normalize = normalize_indent is not None and indent > (normalize_indent or 0)

        # Check when/visible_if: should be unquoted
        m = UNQUOTED_EXPR.match(line)
        if m:
            key, expr = m.group(2), m.group(3)
            if not (expr.startswith("{{") and expr.endswith("}}")):
                errors.append(f"{path.name}:{i}: {key}: should be unquoted — remove double quotes")

        # Check compute: must use "{{ }}" delimiters. Skip lines whose
        # value is a YAML block-scalar indicator (`|` / `>-` / `>+`) —
        # the actual Jinja expression lives on the following lines and
        # the regex linter can't follow it.
        m = COMPUTE_LINE.match(line)
        if m:
            value = m.group(2).strip()
            is_block_scalar = value in ("", "|", ">", "|-", "|+", ">-", ">+")
            looks_like_continuation = value.startswith('"{{') and not value.endswith('}}"')
            if not is_block_scalar and not looks_like_continuation and not (value.startswith('"{{') and value.endswith('}}"')):
                errors.append(f'{path.name}:{i}: compute: should use Jinja2 delimiters — "{{{{ expression }}}}"')

        # Check type: must use hyphens not underscores
        m = UNDERSCORE_TYPE.match(line)
        if m:
            errors.append(f"{path.name}:{i}: type: use hyphens — {m.group(2)} → {m.group(2).replace('_', '-')}")

        if is_comment:
            continue

        # Check value: must be a Jinja2 expression (skip DSL operator
        # keys inside `normalize:` blocks; skip YAML block-scalar values
        # whose content lives on following lines).
        m = VALUE_LINE.match(line)
        if m and not in_normalize:
            raw = m.group(1).strip()
            if raw not in ("|", ">", "|-", "|+", ">-", ">+"):
                unquoted = raw.strip('"').strip("'")
                if "{{" not in unquoted or "}}" not in unquoted:
                    errors.append(
                        f"{path.name}:{i}: value: must use Jinja2 delimiters — "
                        f"'value: {raw}' → 'value: \"{{{{ {unquoted} }}}}\"'"
                    )

        # Check for retired keys (skip inside `normalize:` — `field:` is
        # a DSL predicate operator key there).
        m = RETIRED_KEY_LINE.match(line)
        if m and not in_normalize:
            key = m.group(1)
            if key not in RETIRED_EXEMPT_KEYS:
                # Exclude when the key is a suffix of an exempt key on this line.
                if not any(line.lstrip().startswith(f"{exempt}:") for exempt in RETIRED_EXEMPT_KEYS):
                    errors.append(
                        f"{path.name}:{i}: '{key}:' is no longer supported — "
                        f"rename to '{RETIRED_KEY_HINTS[key]}:'"
                    )

        # Check human-readable keys are quoted when they contain whitespace
        # or punctuation (skip DSL `name:` mapping keys inside normalize:).
        m = QUOTED_KEY_LINE.match(line)
        if m and not in_normalize:
            key, raw = m.group(1), m.group(2).strip()
            if raw and not (raw.startswith('"') or raw.startswith("'")):
                # Allow bare tokens with no whitespace or punctuation (single identifiers).
                if re.search(r"[\s\-:/&%(),]", raw):
                    errors.append(
                        f"{path.name}:{i}: {key}: string values with whitespace or punctuation must be double-quoted — "
                        f"'{key}: {raw}' → '{key}: \"{raw}\"'"
                    )

        # badge: true was replaced by `as: status-badge`
        if re.match(r"badge:\s*(true|false)\b", stripped):
            errors.append(
                f"{path.name}:{i}: badge: true is no longer supported — use 'as: status-badge'"
            )
        if "[badge]" in line:
            errors.append(
                f"{path.name}:{i}: [badge] shorthand not allowed — use 'as: status-badge'"
            )

    return errors


# Field-reference check ---------------------------------------------------

# Fields the reporter injects automatically (extract_fields, alert rollups).
_WELL_KNOWN_REFS: set[str] = {
    "hostname", "collected_at", "metadata", "item", "loop", "config",
    "audit_failed", "_critical_count", "_warning_count", "_total_alerts",
    "ansible_facts",
}

_JINJA_ENV = Environment()


def _jinja_vars(text: Any) -> set[str]:
    if not isinstance(text, str) or ("{{" not in text and "{%" not in text):
        return set()
    try:
        return meta.find_undeclared_variables(_JINJA_ENV.parse(text))
    except Exception:
        return set()


def _walk_strings(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk_strings(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_strings(value, out)
    elif isinstance(node, str):
        out.append(node)


def _declared_fields(doc: dict, base_dir: Path) -> set[str]:
    """Names declared in vars: (resolving a single $include partial)."""
    fields: set[str] = set()
    vars_block = doc.get("vars") or doc.get("fields") or {}
    if isinstance(vars_block, dict):
        if "$include" in vars_block:
            inc = base_dir / vars_block["$include"]
            if inc.exists():
                with inc.open() as fh:
                    inc_doc = yaml.safe_load(fh) or {}
                if isinstance(inc_doc, dict):
                    fields.update(inc_doc.keys())
        else:
            fields.update(vars_block.keys())
    return fields


def _near_match(ref: str, declared: set[str]) -> str | None:
    """Return a declared field whose name is a 1-char-off variant of ref."""
    if ref in declared:
        return None
    for candidate in declared:
        if candidate == f"{ref}s" or f"{candidate}s" == ref:
            return candidate
        if candidate.replace("_count", "_counts") == ref or candidate.replace("_counts", "_count") == ref:
            return candidate
        if len(candidate) == len(ref) and sum(a != b for a, b in zip(candidate, ref)) == 1:
            return candidate
    return None


def lint_field_references(path: Path) -> list[str]:
    try:
        with path.open() as fh:
            doc = yaml.safe_load(fh) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(doc, dict):
        return []
    if not any(k in doc for k in ("vars", "fields", "alerts", "widgets", "config")):
        return []

    declared = _declared_fields(doc, path.parent) | _WELL_KNOWN_REFS
    strings: list[str] = []
    for section in ("alerts", "widgets", "config"):
        _walk_strings(doc.get(section), strings)

    refs: set[str] = set()
    for s in strings:
        refs |= _jinja_vars(s)

    errors: list[str] = []
    for ref in sorted(refs):
        if ref in declared:
            continue
        suggestion = _near_match(ref, declared)
        if suggestion:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: '{{{{ {ref} }}}}' looks like a typo of declared field '{suggestion}'"
            )
    return errors


def main() -> int:
    errors: list[str] = []
    paths = [p for d in CONFIG_DIRS for p in sorted(d.glob("*.yaml"))]
    for path in paths:
        errors.extend(lint_file(path))
        errors.extend(lint_field_references(path))

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n{len(errors)} violation(s) found across {len(paths)} configs.", file=sys.stderr)
        return 1

    print(f"Config lint: OK ({len(paths)} configs scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
