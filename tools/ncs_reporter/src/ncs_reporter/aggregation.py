"""Reusable report aggregation helpers for fleet/platform state directories."""

import os
import sys
from datetime import datetime
from typing import Any
from collections.abc import Callable

import yaml


def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Recursively merges source into target."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_merge(target[key], value)
        elif (
            key in target and isinstance(target[key], list) and isinstance(value, list)
        ):
            # Combine lists (e.g., alerts from discovery + alerts from audit)
            target[key].extend([i for i in value if i not in target[key]])
        else:
            target[key] = value
    return target


def read_report(file_path: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    with open(file_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return None, None, None

    metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
    payload = raw.get("data", raw)
    if not isinstance(payload, dict):
        payload = {}

    audit_type = str(
        payload.get("audit_type")
        or metadata.get("audit_type")
        or os.path.basename(file_path).replace(".yaml", "")
    )

    merged = dict(payload)
    if "health" in raw and "health" not in merged:
        merged["health"] = raw.get("health")
    if "summary" in raw and "summary" not in merged:
        merged["summary"] = raw.get("summary")
    if "alerts" in raw and "alerts" not in merged:
        merged["alerts"] = raw.get("alerts")
    if metadata and "metadata" not in merged:
        merged["metadata"] = metadata

    return raw, merged, audit_type


def load_all_reports(
    report_dir: str,
    audit_filter: str | None = None,
    normalizer: Callable[[str, str, dict[str, Any]], tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    aggregated: dict[str, Any] = {
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

    traversal_exclude = {
        "history",
        "raw_state",
        "Summary",
        "Split",
        "__pycache__",
        ".git",
        ".artifacts",
    }
    host_exclude = {
        "platform",
        "ubuntu",
        "vmware",
        "windows",
        "all_hosts_state.yaml",
        "vmware_fleet_state.yaml",
        "linux_fleet_state.yaml",
        "windows_fleet_state.yaml",
    }.union(traversal_exclude)

    if not os.path.isdir(report_dir):
        return None

    for root, dirs, files in os.walk(report_dir):
        dirs[:] = [d for d in dirs if d not in traversal_exclude]
        if root == report_dir:
            continue

        rel_path = os.path.relpath(root, report_dir)
        path_parts = rel_path.split(os.sep)

        while path_parts and path_parts[0] in host_exclude:
            path_parts.pop(0)

        if not path_parts or len(path_parts) > 1:
            continue

        hostname = path_parts[0]
        yaml_files = [f for f in files if f.endswith(".yaml") and f not in host_exclude]

        if not yaml_files:
            continue

        if hostname not in aggregated["hosts"]:
            aggregated["hosts"][hostname] = {}

        for yaml_file in yaml_files:
            file_path = os.path.join(root, yaml_file)
            try:
                _raw_report, report, audit_type = read_report(file_path)
                if not isinstance(report, dict) or audit_type is None:
                    continue
                if audit_filter and audit_type != audit_filter:
                    continue

                if normalizer:
                    audit_type, report = normalizer(hostname, audit_type, report)

                deep_merge(aggregated["hosts"][hostname], report)

                # Update Fleet Stats
                summary = report.get("summary", {})
                criticals = (
                    int(summary.get("critical_count", 0))
                    if isinstance(summary, dict)
                    else 0
                )
                warnings = (
                    int(summary.get("warning_count", 0))
                    if isinstance(summary, dict)
                    else 0
                )

                aggregated["metadata"]["fleet_stats"]["critical_alerts"] += criticals
                aggregated["metadata"]["fleet_stats"]["warning_alerts"] += warnings

            except Exception as e:
                print(f"Warning: Failed to load {file_path}: {e}", file=sys.stderr)

    aggregated["metadata"]["fleet_stats"]["total_hosts"] = len(aggregated["hosts"])
    return aggregated


def write_output(data: dict[str, Any], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
