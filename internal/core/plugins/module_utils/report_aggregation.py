"""Reusable report aggregation helpers for fleet/platform state directories."""

import json
import os
import sys
from datetime import datetime

import yaml

try:
    from .reporting_primitives import canonical_severity
except ImportError:
    import importlib.util
    from pathlib import Path

    _helper_path = Path(__file__).resolve().parent / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location(
        "internal_core_reporting_primitives", _helper_path
    )
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    canonical_severity = _mod.canonical_severity


def read_report(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return None, None, None

    metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
    payload = raw.get("data", raw)
    if not isinstance(payload, dict):
        payload = {}

    audit_type = (
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


def _apply_report_normalizer(normalizer, hostname, audit_type, report):
    if normalizer is None:
        return audit_type, report

    normalized = normalizer(hostname, audit_type, report)
    if (
        isinstance(normalized, tuple)
        and len(normalized) == 2
        and isinstance(normalized[1], dict)
    ):
        return normalized[0], normalized[1]
    if isinstance(normalized, dict):
        return audit_type, normalized
    return audit_type, report


def load_all_reports(report_dir, audit_filter=None, normalizer=None):
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
                        _raw_report, report, audit_type = read_report(file.path)
                        if not isinstance(report, dict):
                            continue
                        if audit_filter and audit_type != audit_filter:
                            continue

                        audit_type, report = _apply_report_normalizer(
                            normalizer, hostname, audit_type, report
                        )

                        if hostname not in aggregated["hosts"]:
                            aggregated["hosts"][hostname] = {}

                        aggregated["hosts"][hostname][audit_type] = report
                        host_has_data = True

                        summary = report.get("summary", {})
                        if not summary and "vcenter_health" in report:
                            alerts = report["vcenter_health"].get("alerts", [])
                            criticals = len(
                                [
                                    a
                                    for a in alerts
                                    if canonical_severity(a.get("severity")) == "CRITICAL"
                                ]
                            )
                            warnings = len(
                                [
                                    a
                                    for a in alerts
                                    if canonical_severity(a.get("severity")) == "WARNING"
                                ]
                            )
                        else:
                            criticals = int(summary.get("critical_count", 0))
                            warnings = int(summary.get("warning_count", 0))

                        aggregated["metadata"]["fleet_stats"]["critical_alerts"] += criticals
                        aggregated["metadata"]["fleet_stats"]["warning_alerts"] += warnings

                    except Exception as e:
                        print(f"Warning: Failed to load {file.path}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Access denied for {entry.path}: {e}", file=sys.stderr)

        if host_has_data:
            # reserved for future host-level stats; keeps parity with prior traversal semantics
            pass

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
