"""Shared helpers for template-facing reporting view-model builders."""

from typing import Any

from ..primitives import canonical_severity as canonical_severity, safe_list as safe_list, to_float as to_float, to_int as to_int  # noqa: F401 (to_int re-exported)

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


def _iter_hosts(aggregated_hosts: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(aggregated_hosts, dict):
        return []
    hosts_map = aggregated_hosts.get("hosts")
    if isinstance(hosts_map, dict):
        aggregated_hosts = hosts_map
    rows: list[tuple[str, dict[str, Any]]] = []
    for hostname, bundle in aggregated_hosts.items():
        if hostname in _DEFAULT_SKIP_KEYS:
            continue
        if not isinstance(bundle, dict):
            continue
        rows.append((str(hostname), bundle))
    rows.sort(key=lambda item: item[0])
    return rows


def status_badge_meta(status: Any, preserve_label: bool = False) -> dict[str, str]:
    """
    Normalize a status/severity string into badge presentation metadata.
    Returns a dict with:
      - css_class: one of status-ok/status-warn/status-fail
      - label: display text
    """
    raw = str(status or "unknown").strip()
    upper = raw.upper()

    ok_values = {"OK", "HEALTHY", "GREEN", "PASS", "RUNNING"}
    fail_values = {"CRITICAL", "RED", "FAILED", "FAIL", "STOPPED"}

    if upper in ok_values:
        css_class = "status-ok"
        label = upper if preserve_label else "OK"
    elif upper in fail_values:
        css_class = "status-fail"
        label = upper if preserve_label else "CRITICAL"
    else:
        css_class = "status-warn"
        label = upper if preserve_label and upper else "WARN"

    return {"css_class": css_class, "label": label}
