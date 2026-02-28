#!/usr/bin/env python3
"""
Built-in script: count VM snapshots older than age_days.

stdin  — JSON: {"fields": {"snapshots": [...], "collected_at": "ISO"}, "args": {"age_days": 7}}
stdout — JSON integer count
exit 0 on success, 1 if snapshot data absent, 2 on unrecoverable error
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    # Normalise Z suffix
    ts = ts.rstrip("Z")
    # Try with microseconds, then without
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    snapshots: list = fields.get("snapshots", [])
    age_days = float(args.get("age_days", 7))
    collected_at_str: str = str(fields.get("collected_at") or "")

    ref = _parse_iso(collected_at_str) or datetime.now(timezone.utc)
    threshold_seconds = age_days * 86400.0

    count = 0
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        ts = str(snap.get("creation_time") or snap.get("createTime") or "")
        dt = _parse_iso(ts)
        if dt is None:
            continue
        if (ref - dt).total_seconds() > threshold_seconds:
            count += 1

    print(json.dumps(count))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
