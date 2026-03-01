#!/usr/bin/env python3
"""
Built-in script: extract a flattened list of cluster details from clusters_info results.

stdin  — JSON: {"fields": {"clusters_info_results": [...]}}
stdout — JSON list of objects
exit 0 on success, 2 on error
"""

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    results: list = fields.get("clusters_info_results", [])

    clusters_list = []

    for entry in results:
        if not isinstance(entry, dict):
            continue
        dc_name = entry.get("item", "unknown")
        dc_clusters = entry.get("clusters")
        if not isinstance(dc_clusters, dict):
            continue

        for cname, cdata in dc_clusters.items():
            if not isinstance(cdata, dict):
                continue
            
            hosts = cdata.get("hosts", [])
            host_count = len(hosts) if isinstance(hosts, list) else 0
            
            res = cdata.get("resource_summary", {})
            cpu_used = float(res.get("cpuUsedMHz") or 0)
            cpu_cap = float(res.get("cpuCapacityMHz") or 1)
            mem_used = float(res.get("memUsedMB") or 0)
            mem_cap = float(res.get("memCapacityMB") or 1)

            clusters_list.append({
                "name": cname,
                "datacenter": dc_name,
                "drs_enabled": cdata.get("drs_enabled", False),
                "ha_enabled": cdata.get("ha_enabled", False),
                "host_count": host_count,
                "cpu_usage_pct": round((cpu_used / cpu_cap) * 100, 1) if cpu_cap > 0 else 0,
                "mem_usage_pct": round((mem_used / mem_cap) * 100, 1) if mem_cap > 0 else 0,
            })

    print(json.dumps(clusters_list))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
