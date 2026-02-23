#!/usr/bin/env python3
# scripts/aggregate_yaml_reports.py
#
# Reads per-host YAML files written by domain roles during the audit phase.
# Merges them into a single all_hosts.yaml for template rendering.
#
# Expected input structure:
#   <report_dir>/<hostname>/<hostname>.yaml   ← primary audit file only
#
# Output:
#   <output_path> (typically <summary_dir>/all_hosts.yaml)

import os
import sys

import yaml


def load_host_files(report_dir):
    """
    Finds and loads primary per-host YAML files.
    Matches only <report_dir>/<hostname>/<hostname>.yaml —
    ignores stig, discovery, and other supplementary files.
    Returns a dict keyed by hostname.
    """
    hosts = {}

    try:
        entries = os.scandir(report_dir)
    except FileNotFoundError:
        print(f"Report directory not found: {report_dir}", file=sys.stderr)
        return hosts

    for entry in entries:
        if not entry.is_dir() or entry.name == "Summary":
            continue

        hostname = entry.name
        primary = os.path.join(entry.path, f"{hostname}.yaml")

        if not os.path.isfile(primary):
            continue

        try:
            with open(primary, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                hosts[hostname] = data
            else:
                print(
                    f"Warning: unexpected structure in {primary}, skipping",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"Warning: failed to load {primary}: {e}", file=sys.stderr)

    return hosts


def write_combined(hosts, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(hosts, f, default_flow_style=False, allow_unicode=True)
        print(f"Written: {output_path} ({len(hosts)} host(s))")
    except OSError as e:
        print(f"Error writing {output_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <report_dir> <output_path>")
        sys.exit(1)

    hosts = load_host_files(sys.argv[1])

    if not hosts:
        print("No host files found, skipping.", file=sys.stderr)
        sys.exit(0)

    write_combined(hosts, sys.argv[2])
