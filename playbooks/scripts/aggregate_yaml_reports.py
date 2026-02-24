#!/usr/bin/env python3

import json
import os
import sys
from datetime import datetime

import yaml


def load_all_reports(report_dir, audit_filter=None):
    """
    Groups results by Hostname -> Audit Type and calculates global health metrics.
    Traverses: <report_dir>/<hostname>/<audit_type>.yaml
    """
    aggregated = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "fleet_stats": {
                "total_hosts": 0,
                "critical_alerts": 0,
                "warning_alerts": 0,
            },
        },
        "hosts": {},
    }

    # Files and folders to ignore to prevent infinite loops or processing metadata as hosts
    excluded_names = [
        "Summary",
        "Split",
        "platform",
        "raw_state",
        "history",
        "ubuntu",
        "vmware",
        "all_hosts_state.yaml",
        "vmware_fleet_state.yaml",
        "linux_fleet_state.yaml",
    ]

    try:
        entries = sorted(os.scandir(report_dir), key=lambda e: e.name)
    except FileNotFoundError:
        print(f"Error: Report directory not found: {report_dir}", file=sys.stderr)
        return None

    for entry in entries:
        if not entry.is_dir() or entry.name in excluded_names:
            continue

        hostname = entry.name
        host_has_data = False

        try:
            for file in os.scandir(entry.path):
                if (
                    file.is_file()
                    and file.name.endswith(".yaml")
                    and file.name not in excluded_names
                ):
                    try:
                        with open(file.path, "r", encoding="utf-8") as f:
                            report = yaml.safe_load(f)

                        if not isinstance(report, dict):
                            continue

                        # Standardize Audit Type
                        audit_type = report.get(
                            "audit_type", file.name.replace(".yaml", "")
                        )
                        if audit_filter and audit_type != audit_filter:
                            continue

                        # --- STANDARDIZATION LOGIC ---
                        # Ensure vCenter data is accessible under common keys for the Fleet Template
                        if "inventory" in report or "vmware_ctx" in report:
                            report = {
                                "discovery": report.get(
                                    "inventory", report.get("vmware_ctx", {})
                                ),
                                "vcenter_health": {
                                    "alerts": report.get("alerts", []),
                                    "data": report.get("vcenter_health", {}).get(
                                        "data", {}
                                    ),
                                    "health": report.get("vcenter_health", {}).get(
                                        "health", "OK"
                                    ),
                                },
                                "audit_type": audit_type,
                            }

                        if hostname not in aggregated["hosts"]:
                            aggregated["hosts"][hostname] = {}

                        aggregated["hosts"][hostname][audit_type] = report
                        host_has_data = True

                        # Accumulate Alert Totals
                        # Looks for both top-level summary and standardized vcenter_health summary
                        summary = report.get("summary", {})
                        if not summary and "vcenter_health" in report:
                            # Fallback for VMware standardized structure
                            alerts = report["vcenter_health"].get("alerts", [])
                            criticals = len(
                                [a for a in alerts if a.get("severity") == "CRITICAL"]
                            )
                            warnings = len(
                                [a for a in alerts if a.get("severity") == "WARNING"]
                            )
                        else:
                            criticals = int(summary.get("critical_count", 0))
                            warnings = int(summary.get("warning_count", 0))

                        aggregated["metadata"]["fleet_stats"]["critical_alerts"] += (
                            criticals
                        )
                        aggregated["metadata"]["fleet_stats"]["warning_alerts"] += (
                            warnings
                        )

                    except Exception as e:
                        print(
                            f"Warning: Failed to load {file.path}: {e}", file=sys.stderr
                        )
        except Exception as e:
            print(f"Warning: Access denied for {entry.path}: {e}", file=sys.stderr)

    if host_has_data:
        aggregated["metadata"]["fleet_stats"]["total_hosts"] = len(aggregated["hosts"])

    return aggregated


def write_output(data, output_path):
    """Writes the aggregated data to disk as YAML or JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    is_json = output_path.endswith(".json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            if is_json:
                json.dump(data, f, indent=2)
            else:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"Success: Aggregated {len(data['hosts'])} hosts into {output_path}")
    except OSError as e:
        print(f"Error writing {output_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <report_dir> <output_path> [audit_type_filter]")
        sys.exit(1)

    all_data = load_all_reports(
        sys.argv[1], audit_filter=(sys.argv[3] if len(sys.argv) > 3 else None)
    )
    write_output(
        all_data or {"metadata": {"fleet_stats": {"total_hosts": 0}}, "hosts": {}},
        sys.argv[2],
    )
