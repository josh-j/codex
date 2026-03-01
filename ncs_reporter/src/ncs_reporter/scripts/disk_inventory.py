#!/usr/bin/env python3
"""
Built-in script: filter and enrich a mounts list for Linux disk reporting.

Excludes loop/tmpfs/squashfs devices, then computes total_gb, free_gb, used_pct
for each remaining mount using ansible_facts.mounts field keys (size_total,
size_available).

stdin  — JSON: {
    "fields": {"mounts": [...]},
    "args": {
        "exclude_device_patterns": ["loop", "tmpfs", "devtmpfs", "squashfs"],
        "exclude_fstypes": ["tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devpts"],
        "warn_pct": 80.0,
        "crit_pct": 95.0
    }
}
stdout — JSON list of enriched mount dicts, each with added keys:
         total_gb, free_gb, used_pct
"""

from typing import Any

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    mounts: list[Any] = fields.get("mounts", [])
    exclude_device_patterns: list[str] = args.get("exclude_device_patterns", ["loop", "tmpfs", "devtmpfs", "squashfs"])
    exclude_fstypes: list[str] = args.get(
        "exclude_fstypes", ["tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devpts"]
    )

    result = []
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        device = str(mount.get("device") or "")
        fstype = str(mount.get("fstype") or "")

        if any(pat in device for pat in exclude_device_patterns):
            continue
        if fstype.lower() in {f.lower() for f in exclude_fstypes}:
            continue

        try:
            size_total = float(mount.get("size_total") or 0)
            size_available = float(mount.get("size_available") or 0)
        except (TypeError, ValueError):
            size_total = 0.0
            size_available = 0.0

        used_pct = round((size_total - size_available) / size_total * 100.0, 1) if size_total > 0 else 0.0
        total_gb = round(size_total / 1_073_741_824.0, 1)
        free_gb = round(size_available / 1_073_741_824.0, 1)

        result.append(
            {
                **mount,
                "total_gb": total_gb,
                "free_gb": free_gb,
                "used_pct": used_pct,
            }
        )

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
