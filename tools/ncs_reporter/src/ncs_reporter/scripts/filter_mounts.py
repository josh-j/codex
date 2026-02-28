#!/usr/bin/env python3
"""
Built-in script: filter a mounts list, removing loop/tmpfs/special devices.

stdin  — JSON: {
    "fields": {"mounts": [...]},
    "args": {
        "exclude_device_patterns": ["loop", "tmpfs", "devtmpfs", "squashfs"],
        "exclude_fstypes": ["tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devpts"]
    }
}
stdout — JSON list (filtered mounts, same structure as input)
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    mounts: list = fields.get("mounts", [])
    exclude_device_patterns: list[str] = args.get(
        "exclude_device_patterns", ["loop", "tmpfs", "devtmpfs", "squashfs"]
    )
    exclude_fstypes: list[str] = args.get(
        "exclude_fstypes", ["tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "devpts"]
    )

    filtered = []
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        device = str(mount.get("device") or "")
        fstype = str(mount.get("fstype") or "")

        if any(pat in device for pat in exclude_device_patterns):
            continue
        if fstype.lower() in {f.lower() for f in exclude_fstypes}:
            continue

        filtered.append(mount)

    print(json.dumps(filtered))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
