import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        canonical_severity,
        safe_list,
    )
except ImportError:
    _helper_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location("internal_core_reporting_primitives", _helper_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    canonical_severity = _mod.canonical_severity
    safe_list = _mod.safe_list


def compute_audit_rollups(alerts):
    alerts = safe_list(alerts)
    summary: dict[str, Any] = {
        "total": len(alerts),
        "critical_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "by_category": {},
    }
    severities = set()

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        raw_severity = alert.get("severity", "INFO")
        severity = canonical_severity(raw_severity)
        category = str(alert.get("category", "uncategorized") or "uncategorized")
        severities.add(severity)

        if severity == "CRITICAL":
            summary["critical_count"] += 1
        elif severity == "WARNING":
            summary["warning_count"] += 1
        else:
            summary["info_count"] += 1

        summary["by_category"][category] = summary["by_category"].get(category, 0) + 1

    if "CRITICAL" in severities:
        health = "CRITICAL"
    elif "WARNING" in severities:
        health = "WARNING"
    else:
        health = "HEALTHY"

    return {"summary": summary, "health": health}


def build_system_audit_export_payload(ubuntu_ctx, ubuntu_alerts, health, summary):
    out = copy.deepcopy(dict(ubuntu_ctx or {}))
    out["audit_type"] = "system"
    out["audit_failed"] = False
    out["health"] = health
    out["alerts"] = safe_list(ubuntu_alerts)
    out["summary"] = dict(summary or {})
    out["check_metadata"] = {
        "engine": "ansible-ncs-linux",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return out


class FilterModule:
    def filters(self):
        return {
            "compute_audit_rollups": compute_audit_rollups,
            "build_system_audit_export_payload": build_system_audit_export_payload,
        }
