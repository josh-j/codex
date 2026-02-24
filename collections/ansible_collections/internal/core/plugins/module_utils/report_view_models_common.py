"""Shared helpers for template-facing reporting view-model builders."""

import importlib.util
from pathlib import Path

try:
    from .reporting_primitives import canonical_severity, to_float, to_int
except ImportError:
    _helper_path = Path(__file__).resolve().parent / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location("internal_core_reporting_primitives", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    canonical_severity = _mod.canonical_severity
    to_float = _mod.to_float
    to_int = _mod.to_int


_DEFAULT_SKIP_KEYS = {
    "Summary",
    "Split",
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


def default_report_skip_keys():
    """Return canonical structural/state keys that should be skipped in host loops."""
    return sorted(_DEFAULT_SKIP_KEYS)


def _status_from_health(value):
    if isinstance(value, dict):
        for key in ("overall", "status", "health"):
            v = value.get(key)
            if v is not None:
                return _status_from_health(v)
        return "UNKNOWN"

    text = str(value or "UNKNOWN").strip()
    low = text.lower()
    if low in ("green", "healthy", "ok", "success"):
        return "OK"
    if low in ("yellow", "warning", "degraded"):
        return "WARNING"
    if low in ("red", "critical", "failed", "error"):
        return "CRITICAL"
    if low in ("gray", "unknown"):
        return "UNKNOWN"
    return text.upper()


def _safe_pct(used, total):
    used_f = to_float(used, 0.0)
    total_f = max(to_float(total, 0.0), 1.0)
    return round((used_f / total_f) * 100.0, 1)


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _severity_for_pct(value_pct, warning=85.0, critical=90.0):
    pct = to_float(value_pct, 0.0)
    if pct > to_float(critical, 90.0):
        return "CRITICAL"
    if pct > to_float(warning, 85.0):
        return "WARNING"
    return "OK"


def _count_alerts(alerts):
    counts = {"critical": 0, "warning": 0, "total": 0}
    for alert in list(alerts or []):
        sev = canonical_severity((alert or {}).get("severity"))
        if sev == "CRITICAL":
            counts["critical"] += 1
        elif sev == "WARNING":
            counts["warning"] += 1
    counts["total"] = counts["critical"] + counts["warning"]
    return counts


def _iter_hosts(aggregated_hosts):
    if not isinstance(aggregated_hosts, dict):
        return []
    hosts_map = aggregated_hosts.get("hosts")
    if isinstance(hosts_map, dict):
        aggregated_hosts = hosts_map
    rows = []
    for hostname, bundle in aggregated_hosts.items():
        if hostname in _DEFAULT_SKIP_KEYS:
            continue
        if not isinstance(bundle, dict):
            continue
        rows.append((str(hostname), bundle))
    rows.sort(key=lambda item: item[0])
    return rows
