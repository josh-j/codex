#!/usr/bin/env python3
# scripts/aggregate_yaml_reports.py

import json
import os
import sys
from datetime import datetime

import yaml


def load_all_reports(report_dir):
    """
    Groups results by Hostname -> Audit Type and calculates global health metrics.
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

    try:
        entries = sorted(os.scandir(report_dir), key=lambda e: e.name)
    except FileNotFoundError:
        print(f"Error: Report directory not found: {report_dir}", file=sys.stderr)
        return None

    for entry in entries:
        if not entry.is_dir() or entry.name == "Summary":
            continue

        hostname = entry.name
        aggregated["hosts"][hostname] = {}
        aggregated["metadata"]["fleet_stats"]["total_hosts"] += 1

        # Process each audit type (.yaml file) for the host
        for file in os.scandir(entry.path):
            if file.is_file() and file.name.endswith(".yaml"):
                try:
                    with open(file.path, "r", encoding="utf-8") as f:
                        report = yaml.safe_load(f)

                    if not isinstance(report, dict):
                        continue

                    audit_type = report.get("audit_type", "system")
                    aggregated["hosts"][hostname][audit_type] = report

                    # Pre-calculate global alert counts for the dashboard header
                    summary = report.get("summary", {})
                    aggregated["metadata"]["fleet_stats"]["critical_alerts"] += int(
                        summary.get("critical_count", 0)
                    )
                    aggregated["metadata"]["fleet_stats"]["warning_alerts"] += int(
                        summary.get("warning_count", 0)
                    )

                except Exception as e:
                    print(f"Warning: Failed to load {file.path}: {e}", file=sys.stderr)

    return aggregated


def write_output(data, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # We support YAML for human debugging and JSON for potentially faster JS dashboarding
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
        print(f"Usage: {sys.argv[0]} <report_dir> <output_path>")
        sys.exit(1)

    all_data = load_all_reports(sys.argv[1])
    if all_data and all_data["hosts"]:
        write_output(all_data, sys.argv[2])
    else:
        print("No valid host reports found.", file=sys.stderr)
