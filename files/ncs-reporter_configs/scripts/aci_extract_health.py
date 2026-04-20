#!/usr/bin/env python3
"""Built-in script: extract fabric + tenant health scores from an APIC payload.

stdin  - JSON: {"fields": {"health_results": [...]}, "args": {}}
stdout - JSON dict: {"fabric": int|null, "tenant": int|null}

The APIC REST API returns two separate responses (fabric and tenant health),
looped together into `health_results`. Each entry is an `ansible.builtin.uri`
response envelope, so the raw shape is:

    health_results[0].json.imdata[0].fabricHealthTotal.attributes.cur   # fabric
    health_results[1].json.imdata[0].healthInst.attributes.cur          # tenant
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _cur_from(result: Any, key: str) -> int | None:
    try:
        attrs = result["json"]["imdata"][0][key]["attributes"]
    except (KeyError, IndexError, TypeError):
        return None
    val = attrs.get("cur")
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps({"fabric": None, "tenant": None}))
        return

    fields = payload.get("fields") or {}
    results = fields.get("health_results") or []
    if not isinstance(results, list):
        results = []

    fabric = _cur_from(results[0], "fabricHealthTotal") if len(results) >= 1 else None
    tenant = _cur_from(results[1], "healthInst") if len(results) >= 2 else None

    print(json.dumps({"fabric": fabric, "tenant": tenant}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(2)
