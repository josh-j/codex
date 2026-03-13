#!/usr/bin/env python3
"""
Built-in script: extract JSON from Ansible win_powershell register output.

Ansible's win_powershell module stores output in a structure like:
  {"output": ["<json string>"], ...}

This script unwraps that envelope and returns the parsed JSON value.
If the field is already a dict/list (not wrapped), it is passed through.

stdin  — JSON: {
    "fields": {"<source_field>": <raw win_powershell value>, ...},
    "args": {
        "source_field": "ps_output",  # which field to unwrap (default: ps_output)
        "key": null                   # optional key to extract from parsed object
    }
}
stdout — JSON value (parsed content, or {} on failure)
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    source_field: str = args.get("source_field") or "ps_output"
    ps_output = fields.get(source_field)

    if not ps_output:
        # Source field absent or empty — PS data not collected on this host.
        sys.exit(1)

    extract_key: str | None = args.get("key")

    # Unwrap Ansible win_powershell envelope
    if isinstance(ps_output, dict) and "output" in ps_output:
        try:
            raw_str = ps_output["output"][0]
            ps_output = json.loads(raw_str)
        except (IndexError, json.JSONDecodeError, TypeError):
            ps_output = ps_output  # keep original on parse failure

    # Optionally extract a sub-key
    if extract_key and isinstance(ps_output, dict):
        ps_output = ps_output.get(extract_key, [])

    print(json.dumps(ps_output if ps_output is not None else {}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
