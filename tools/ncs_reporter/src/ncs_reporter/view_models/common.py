"""Shared helpers for template-facing reporting view-model builders."""

from typing import Any

from ..primitives import canonical_severity as canonical_severity, safe_list as safe_list, to_float as to_float, to_int as to_int  # noqa: F401 (to_int re-exported)

_DEFAULT_SKIP_KEYS = {
    "summary",
    "split",
    "platform",
    "history",
    "raw_state",
    "ubuntu",
    "vmware",
    "windows",
    "all_hosts_state",
    "all_hosts_state.yaml",
    "linux_fleet_state",
    "linux_fleet_state.yaml",
    "vmware_fleet_state",
    "vmware_fleet_state.yaml",
    "windows_fleet_state",
    "windows_fleet_state.yaml",
}


def default_report_skip_keys() -> list[str]:
    """Return canonical structural/state keys that should be skipped in host loops."""
    return sorted(_DEFAULT_SKIP_KEYS)


def _status_from_health(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("overall", "status", "health"):
            v = value.get(key)
            if v is not None:
                return _status_from_health(v)
        return "UNKNOWN"

    text = str(value or "UNKNOWN").strip()
    low = text.lower()
    if low in ("green", "healthy", "ok", "success", "pass", "passed"):
        return "OK"
    if low in ("yellow", "warning", "degraded"):
        return "WARNING"
    if low in ("red", "critical", "failed", "error"):
        return "CRITICAL"
    if low in ("gray", "unknown"):
        return "UNKNOWN"
    return text.upper()


def _safe_pct(used: Any, total: Any) -> float:
    used_f = to_float(used, 0.0)
    total_f = max(to_float(total, 0.0), 1.0)
    return float(round((used_f / total_f) * 100.0, 1))


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _severity_for_pct(value_pct: Any, warning: float = 85.0, critical: float = 90.0) -> str:
    pct = to_float(value_pct, 0.0)
    if pct > to_float(critical, 90.0):
        return "CRITICAL"
    if pct > to_float(warning, 85.0):
        return "WARNING"
    return "OK"


def _count_alerts(alerts: Any) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "total": 0}
    for alert in safe_list(alerts):
        if not isinstance(alert, dict):
            continue
        sev = canonical_severity(alert.get("severity"))
        if sev == "CRITICAL":
            counts["critical"] += 1
        elif sev == "WARNING":
            counts["warning"] += 1
    counts["total"] = counts["critical"] + counts["warning"]
    return counts


def _iter_hosts(aggregated_hosts: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(aggregated_hosts, dict):
        return []
    hosts_map = aggregated_hosts.get("hosts")
    if isinstance(hosts_map, dict):
        aggregated_hosts = hosts_map
    rows: list[tuple[str, dict[str, Any]]] = []
    for hostname, bundle in aggregated_hosts.items():
        if str(hostname).lower() in _DEFAULT_SKIP_KEYS:
            continue
        if not isinstance(bundle, dict):
            continue
        rows.append((str(hostname), bundle))
    rows.sort(key=lambda item: item[0])
    return rows


def status_badge_meta(status: Any) -> dict[str, str]:
    """
    Normalize a status/severity string into badge presentation metadata.
    Returns a dict with:
      - css_class: one of status-ok/status-warn/status-fail
      - label: display text (OK, WARNING, or CRITICAL)
    """
    raw = str(status or "UNKNOWN").strip().upper()

    ok_values = {"OK", "HEALTHY", "GREEN", "PASS", "RUNNING", "SUCCESS"}
    fail_values = {"CRITICAL", "RED", "FAILED", "FAIL", "STOPPED", "ERROR"}

    if raw in ok_values:
        return {"css_class": "status-ok", "label": "OK"}
    if raw in fail_values:
        return {"css_class": "status-fail", "label": "CRITICAL"}

    return {"css_class": "status-warn", "label": "WARNING"}


# ---------------------------------------------------------------------------
# Shared view-model helpers (DRY across fleet/site builders)
# ---------------------------------------------------------------------------

def build_meta(
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, str | None]:
    """Standard meta block shared across all view-model builders."""
    return {
        "report_stamp": report_stamp,
        "report_date": report_date,
        "report_id": report_id,
    }


def extract_platform_alerts(
    alerts_list: list[Any],
    hostname: str,
    audit_type: str,
    category_default: str,
) -> list[dict[str, Any]]:
    """Extract CRITICAL/WARNING alerts from a list into site-dashboard format."""
    result: list[dict[str, Any]] = []
    for alert in safe_list(alerts_list):
        if not isinstance(alert, dict):
            continue
        sev = canonical_severity(alert.get("severity"))
        if sev in ("CRITICAL", "WARNING"):
            result.append({
                "severity": sev,
                "host": hostname,
                "audit_type": audit_type,
                "category": alert.get("category", category_default),
                "message": alert.get("message", ""),
            })
    return result


def aggregate_platform_status(all_alerts: list[dict[str, Any]], audit_type: str) -> str:
    """Derive OK/WARNING/CRITICAL from a list of site-dashboard alerts for a given audit_type."""
    has_critical = any(a["audit_type"] == audit_type and a["severity"] == "CRITICAL" for a in all_alerts)
    has_warning = any(a["audit_type"] == audit_type and a["severity"] == "WARNING" for a in all_alerts)
    if has_critical:
        return "CRITICAL"
    if has_warning:
        return "WARNING"
    return "OK"


def collect_active_alerts(
    alerts_list: list[Any],
    hostname: str,
    audit_type: str,
    category_default: str,
) -> list[dict[str, Any]]:
    """Build active_alerts entries for fleet views (includes raw dict)."""
    result: list[dict[str, Any]] = []
    for alert in safe_list(alerts_list):
        if not isinstance(alert, dict):
            continue
        sev = canonical_severity(alert.get("severity"))
        if sev not in ("CRITICAL", "WARNING"):
            continue
        result.append({
            "host": hostname,
            "severity": sev,
            "category": alert.get("category", category_default),
            "audit_type": audit_type,
            "message": alert.get("message", ""),
            "raw": dict(alert),
        })
    return result
