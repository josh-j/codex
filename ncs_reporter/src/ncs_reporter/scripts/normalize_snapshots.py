#!/usr/bin/env python3
"""
Built-in script: normalize VM snapshots and count aged ones.

stdin  — JSON: {"fields": {"snapshots": [...], "collected_at": "ISO"}, "args": {"age_days": 7}}
stdout — JSON dict: {"snapshots": [...], "aged_count": N}
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    
    # Normalise Z suffix to +00:00 for fromisoformat compatibility in 3.10
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
        
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # Fallback for simple date strings
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print('{"snapshots": [], "aged_count": 0}')
        return

    fields = payload.get("fields", {})
    args = payload.get("args", {})

    snapshots: list = fields.get("snapshots_raw") or fields.get("snapshots") or []
    if not isinstance(snapshots, list):
        snapshots = []
        
    # Build VM -> Owner Email lookup map from already processed virtual_machines field
    vm_owners = {}
    vms_list = fields.get("virtual_machines") or []
    if isinstance(vms_list, list):
        for vm in vms_list:
            if isinstance(vm, dict) and vm.get("guest_name"):
                vm_owners[vm["guest_name"]] = vm.get("owner_email", "")

    mode = args.get("mode", "list")
    age_days = float(args.get("age_days", 7))
    collected_at_str: str = str(fields.get("collected_at") or "")

    ref = _parse_iso(collected_at_str) or datetime.now(timezone.utc)
    threshold_seconds = age_days * 86400.0

    enriched_snapshots = []
    aged_count = 0
    
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        
        item = dict(snap)
        
        # Inject owner email from our lookup map
        vm_name = item.get("vm_name")
        item["owner_email"] = vm_owners.get(vm_name, "") if vm_name else ""

        ts = str(item.get("creation_time") or item.get("createTime") or "")
        dt = _parse_iso(ts)
        
        if dt is not None:
            diff_seconds = (ref - dt).total_seconds()
            days_old = round(diff_seconds / 86400.0, 1)
            item["days_old"] = days_old
            if diff_seconds > threshold_seconds:
                aged_count += 1
        else:
            item["days_old"] = "Unknown"

        enriched_snapshots.append(item)

    if mode == "count":
        print(json.dumps(aged_count))
    else:
        print(json.dumps(enriched_snapshots))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(2)
