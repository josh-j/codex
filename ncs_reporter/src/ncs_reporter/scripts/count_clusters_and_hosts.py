#!/usr/bin/env python3
"""
Built-in script: count clusters and ESXi hosts from clusters_info loop results.

stdin  — JSON: {"fields": {"clusters_info_results": [...], "metric": "cluster_count|esxi_host_count"}, "args": {"metric": "cluster_count"}}
stdout — JSON integer
exit 0 on success, 2 on unrecoverable error

The clusters_info field stored in raw_vcenter is an Ansible loop result:
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

from __future__ import annotations

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})
    args = payload.get("args", {})

    metric = str(args.get("metric", "cluster_count"))
    results: list = fields.get("clusters_info_results", [])

    cluster_count = 0
    esxi_host_count = 0

    for entry in results:
        if not isinstance(entry, dict):
            continue
        dc_clusters = entry.get("clusters")
        if not isinstance(dc_clusters, dict):
            continue
        cluster_count += len(dc_clusters)
        for cdata in dc_clusters.values():
            if isinstance(cdata, dict):
                hosts = cdata.get("hosts")
                if isinstance(hosts, list):
                    esxi_host_count += len(hosts)

    result = cluster_count if metric == "cluster_count" else esxi_host_count
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
