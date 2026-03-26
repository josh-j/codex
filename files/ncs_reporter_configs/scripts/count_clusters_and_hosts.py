#!/usr/bin/env python3
"""
Built-in script: count clusters and ESXi hosts from clusters_info loop results.

stdin  — JSON: {"fields": {"clusters_info_results": [...], "metric": "cluster_count|esxi_host_count"}, "args": {"metric": "cluster_count"}}
stdout — JSON integer
exit 0 on success, 2 on unrecoverable error

The clusters_info field stored in raw_vcsa is an Ansible loop result:
  {
    "results": [
      {
        "item": "DC-Name",
        "clusters": {
          "ClusterName": {
            "hosts": [{"name": "esxi01", "folder": "..."}, ...],
            ...
          }
        }
      }
    ]
  }
"""

from typing import Any

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    metric = str(args.get("metric", "cluster_count"))
    results: list[Any] = fields.get("clusters_info_results", [])

    cluster_count = 0
    esxi_host_count = 0
    ha_disabled = 0
    drs_disabled = 0
    total_cpu_cap = 0.0
    total_cpu_used = 0.0
    total_mem_cap = 0.0
    total_mem_used = 0.0

    for entry in results:
        if not isinstance(entry, dict):
            continue
        dc_clusters = entry.get("clusters")
        if not isinstance(dc_clusters, dict):
            continue
        cluster_count += len(dc_clusters)
        for cdata in dc_clusters.values():
            if not isinstance(cdata, dict):
                continue
            hosts = cdata.get("hosts")
            if isinstance(hosts, list):
                esxi_host_count += len(hosts)
            if not cdata.get("ha_enabled", False):
                ha_disabled += 1
            if not cdata.get("drs_enabled", False):
                drs_disabled += 1
            res = cdata.get("resource_summary", {})
            if isinstance(res, dict):
                total_cpu_cap += float(res.get("cpuCapacityMHz") or 0)
                total_cpu_used += float(res.get("cpuUsedMHz") or 0)
                total_mem_cap += float(res.get("memCapacityMB") or 0)
                total_mem_used += float(res.get("memUsedMB") or 0)

    metrics = {
        "cluster_count": cluster_count,
        "esxi_host_count": esxi_host_count,
        "cluster_ha_disabled_count": ha_disabled,
        "cluster_drs_disabled_count": drs_disabled,
        "total_cpu_capacity": int(total_cpu_cap),
        "total_mem_capacity": int(total_mem_cap),
        "total_cpu_used_pct": round((total_cpu_used / total_cpu_cap) * 100, 1) if total_cpu_cap > 0 else 0.0,
        "total_mem_used_pct": round((total_mem_used / total_mem_cap) * 100, 1) if total_mem_cap > 0 else 0.0,
    }
    print(json.dumps(metrics if metric == "_all" else metrics.get(metric, 0)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
