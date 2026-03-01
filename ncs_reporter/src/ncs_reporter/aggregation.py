"""Report aggregation and normalization for ncs_reporter."""

import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

import yaml

from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.normalization.stig import normalize_stig
from ncs_reporter.primitives import canonical_severity  # noqa: F401
from ncs_reporter.schema_loader import detect_schemas_for_bundle

logger = logging.getLogger(__name__)


def deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Recursively merges source into target."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            deep_merge(target[key], value)
        elif key in target and isinstance(target[key], list) and isinstance(value, list):
            # Combine lists (e.g., alerts from discovery + alerts from audit)
            target[key].extend([i for i in value if i not in target[key]])
        else:
            target[key] = value
    return target


def read_report(file_path: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    with open(file_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        logger.warning("Skipping %s: not a YAML mapping (got %s)", file_path, type(raw).__name__)
        return None, None, None

    metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
    payload = raw.get("data")
    if payload is None:
        payload = raw

    audit_type = str(
        metadata.get("audit_type")
        or (payload.get("audit_type") if isinstance(payload, dict) else None)
        or os.path.basename(file_path).replace(".yaml", "")
    )

    # Return the raw document as-is so schema paths match the file exactly.
    # No data unwrapping — vmware_raw_vcenter.data.appliance_health_info maps
    # directly to what is written on disk.
    return raw, raw, audit_type


def _apply_report_normalizer(
    normalizer: Callable[[str, str, dict[str, Any]], tuple[str, dict[str, Any]] | dict[str, Any]] | None,
    hostname: str,
    audit_type: str,
    report: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if normalizer is None:
        return audit_type, report

    normalized = normalizer(hostname, audit_type, report)
    if isinstance(normalized, tuple) and len(normalized) == 2 and isinstance(normalized[1], dict):
        return normalized[0], normalized[1]
    if isinstance(normalized, dict):
        return audit_type, normalized
    return audit_type, report


def load_all_reports(
    report_dir: str,
    audit_filter: str | None = None,
    normalizer: Callable[[str, str, dict[str, Any]], tuple[str, dict[str, Any]] | dict[str, Any]] | None = None,
    host_normalizer: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
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
        "summary",
        "split",
        "__pycache__",
        ".git",
        ".artifacts",
    }
    host_exclude = {
        "platform",
        # Flat-style platform dirs (legacy)
        "ubuntu",
        "vmware",
        "windows",
        # Nested-style platform dirs (linux/ubuntu, vmware/vcenter, etc.)
        "linux",
        "vcenter",
        "esxi",
        "vm",
        "all_hosts_state.yaml",
        "vmware_fleet_state.yaml",
        "esxi_fleet_state.yaml",
        "vm_fleet_state.yaml",
        "linux_fleet_state.yaml",
        "windows_fleet_state.yaml",
    }.union(traversal_exclude)

    if not os.path.isdir(report_dir):
        logger.error("Report directory not found: %s", report_dir)
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

        host_bundle: dict[str, Any] = {}

        for yaml_file in yaml_files:
            file_path = os.path.join(root, yaml_file)
            try:
                _raw_report, report, audit_type = read_report(file_path)
                if not isinstance(report, dict) or audit_type is None:
                    continue
                if audit_filter and audit_type != audit_filter:
                    continue

                audit_type, report = _apply_report_normalizer(normalizer, hostname, audit_type, report)

                # Store in bundle by audit_type (or filename if multiple raws)
                if audit_type in host_bundle and isinstance(host_bundle[audit_type], dict):
                    deep_merge(host_bundle[audit_type], report)
                else:
                    host_bundle[audit_type] = report

            except Exception as e:
                logger.warning("Failed to load %s: %s", file_path, e)

        # Apply host-level normalizer (e.g., merging raw_discovery + config)
        if host_normalizer:
            try:
                host_bundle = host_normalizer(hostname, host_bundle)
            except Exception as e:
                logger.error("Normalization failed for %s: %s", hostname, e)
                continue

        # Merge bundle into aggregated hosts
        deep_merge(aggregated["hosts"][hostname], host_bundle)

        # Update Fleet Stats (look for summary in any part of the bundle)
        def _update_stats(data: Any) -> None:
            if not isinstance(data, dict):
                return
            summary = data.get("summary", {})
            if isinstance(summary, dict):
                aggregated["metadata"]["fleet_stats"]["critical_alerts"] += int(summary.get("critical_count", 0))
                aggregated["metadata"]["fleet_stats"]["warning_alerts"] += int(summary.get("warning_count", 0))

            # Recurse for nested audit types
            for val in data.values():
                if isinstance(val, dict) and "summary" in val:
                    _update_stats(val)

        _update_stats(host_bundle)

    aggregated["metadata"]["fleet_stats"]["total_hosts"] = len(aggregated["hosts"])
    logger.info("Loaded %d hosts from %s", len(aggregated["hosts"]), report_dir)
    return aggregated


def normalize_host_bundle(hostname: str, bundle: dict[str, Any]) -> dict[str, Any]:
    """
    Normalizes a host bundle if it contains raw data.

    Platform normalization is entirely schema-driven.  STIG normalization retains
    its bespoke Python path because the STIG data model is orthogonal to the
    health-report schema system.
    """
    output = dict(bundle)

    # Normalize legacy key aliases so schema detection always finds canonical keys.
    if "raw_discovery" in bundle and "ubuntu_raw_discovery" not in bundle:
        output["ubuntu_raw_discovery"] = bundle["raw_discovery"]
    if "raw_vcenter" in bundle and "vmware_raw_vcenter" not in bundle:
        output["vmware_raw_vcenter"] = bundle["raw_vcenter"]
    if "raw_audit" in bundle and "windows_raw_audit" not in bundle:
        output["windows_raw_audit"] = bundle["raw_audit"]

    # STIG normalization (kept in Python — orthogonal to schema system)
    stig_keys = [k for k in bundle.keys() if str(k).lower().startswith("stig")]
    for k in stig_keys:
        raw_data = bundle[k]
        target_type = ""
        if isinstance(raw_data, dict):
            target_type = raw_data.get("target_type") or ""
            if not target_type:
                data_val = raw_data.get("data")
                if isinstance(data_val, dict):
                    target_type = data_val.get("target_type", "")
        normalized_stig = normalize_stig(raw_data, stig_target_type=target_type)
        output[k] = normalized_stig.model_dump()

    # Schema-driven normalization for all other platforms
    for schema in detect_schemas_for_bundle(output):
        result = normalize_from_schema(schema, output)
        output[f"schema_{schema.name}"] = result

    return output


def load_ncs_reports(report_dir: str, audit_filter: str | None = None) -> dict[str, Any] | None:
    """
    Loads and normalizes reports from the state directory.
    """
    return load_all_reports(
        report_dir,
        audit_filter=audit_filter,
        host_normalizer=normalize_host_bundle,
    )


def write_output(data: dict[str, Any], output_path: str | os.PathLike[str]) -> None:
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        if isinstance(data, dict) and "hosts" in data:
            logger.info("Aggregated %d hosts into %s", len(data["hosts"]), output_path)
        else:
            logger.info("Wrote data to %s", output_path)
    except OSError as e:
        logger.error("Error writing %s: %s", output_path, e)
        sys.exit(1)
