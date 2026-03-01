#!/usr/bin/env python3
"""
Built-in script: normalize datastore list for VMware reporting.

Converts capacity and freeSpace from bytes to GB, and computes used_pct.

stdin  — JSON: {
    "fields": {"datastores": [...]},
    "args": {}
}
stdout — JSON list of enriched datastore dicts.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[]")
        return

    # Look for datastores_raw in fields (from schema)
    fields = payload.get("fields", {})
    datastores = fields.get("datastores_raw") or []

    if not isinstance(datastores, list):
        print("[]")
        return

    result = []
    for ds in datastores:
        if not isinstance(ds, dict):
            continue

        # Clone to avoid mutating input if that matters,
        # though subprocess stdin/stdout means we have our own copy anyway.
        item = dict(ds)

        try:
            capacity_bytes = float(item.get("capacity") or 0)
            free_bytes = float(item.get("freeSpace") or 0)
        except (TypeError, ValueError):
            capacity_bytes = 0.0
            free_bytes = 0.0

        # Convert to GB (1024^3)
        gb_factor = 1024 * 1024 * 1024
        capacity_gb = round(capacity_bytes / gb_factor, 2)
        free_gb = round(free_bytes / gb_factor, 2)

        # Compute used percentage
        used_bytes = capacity_bytes - free_bytes
        used_pct = round((used_bytes / capacity_bytes) * 100.0, 1) if capacity_bytes > 0 else 0.0

        item["capacity_gb"] = capacity_gb
        item["free_gb"] = free_gb
        item["used_pct"] = used_pct

        result.append(item)

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Script errors are caught by schema_driven.py and logged
        sys.exit(2)
