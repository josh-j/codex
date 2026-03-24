"""Shared helpers for template-facing reporting view-model builders."""

from typing import Any

from ..constants import (
    HEALTH_OK, HEALTH_UNKNOWN, SEVERITY_CRITICAL, SEVERITY_WARNING,
)
from ..platform_registry import default_registry
from ..primitives import (
    canonical_severity as canonical_severity,
    safe_list as safe_list,
    to_float as to_float,
    to_int as to_int,
)  # noqa: F401 (to_int re-exported)

_DEFAULT_SKIP_KEYS = default_registry().skip_keys_set()


def default_report_skip_keys() -> list[str]:
    """Return canonical structural/state keys that should be skipped in host loops."""
    return sorted(_DEFAULT_SKIP_KEYS)


def _status_from_health(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("overall", "status", "health"):
            v = value.get(key)
            if v is not None:
                return _status_from_health(v)
        return HEALTH_UNKNOWN

    from ..constants import (
        CRITICAL_STATUS_ALIASES, HEALTH_CRITICAL, HEALTH_OK, HEALTH_UNKNOWN,
        HEALTH_WARNING, OK_STATUS_ALIASES, UNKNOWN_STATUS_ALIASES,
        WARNING_STATUS_ALIASES,
    )
    text = str(value or HEALTH_UNKNOWN).strip()
    low = text.lower()
    if low in OK_STATUS_ALIASES:
        return HEALTH_OK
    if low in WARNING_STATUS_ALIASES:
        return HEALTH_WARNING
    if low in CRITICAL_STATUS_ALIASES:
        return HEALTH_CRITICAL
    if low in UNKNOWN_STATUS_ALIASES:
        return HEALTH_UNKNOWN
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



def _count_alerts(alerts: Any) -> dict[str, int]:
    from ..constants import SEVERITY_CRITICAL, SEVERITY_WARNING
    counts = {"critical": 0, "warning": 0, "total": 0}
    for alert in safe_list(alerts):
        if not isinstance(alert, dict):
            continue
        sev = canonical_severity(alert.get("severity"))
        if sev == SEVERITY_CRITICAL:
            counts["critical"] += 1
        elif sev == SEVERITY_WARNING:
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


def status_badge_meta(status: Any, preserve_label: bool = False) -> dict[str, str]:
    """
    Normalize a status/severity string into badge presentation metadata.
    Returns a dict with:
      - css_class: one of status-ok/status-warn/status-fail
      - label: display text (OK, WARNING, or CRITICAL)
    """
    from ..constants import (
        BADGE_FAIL_VALUES, BADGE_OK_VALUES, HEALTH_UNKNOWN,
        SEVERITY_CRITICAL, SEVERITY_WARNING, HEALTH_OK,
    )
    raw = str(status or HEALTH_UNKNOWN).strip().upper()

    if raw in BADGE_OK_VALUES:
        return {"css_class": "status-ok", "label": raw if preserve_label else HEALTH_OK}
    if raw in BADGE_FAIL_VALUES:
        return {"css_class": "status-fail", "label": raw if preserve_label else SEVERITY_CRITICAL}

    return {"css_class": "status-warn", "label": raw if preserve_label and raw != HEALTH_UNKNOWN else SEVERITY_WARNING}


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
    *,
    platform_label: str | None = None,
) -> list[dict[str, Any]]:
    """Extract CRITICAL/WARNING alerts from a list into site-dashboard format."""
    result: list[dict[str, Any]] = []
    for alert in safe_list(alerts_list):
        if not isinstance(alert, dict):
            continue
        sev = canonical_severity(alert.get("severity"))
        if sev in (SEVERITY_CRITICAL, SEVERITY_WARNING):
            result.append(
                {
                    "severity": sev,
                    "host": hostname,
                    "audit_type": audit_type,
                    "platform": platform_label or audit_type,
                    "category": alert.get("category", category_default),
                    "message": alert.get("message", ""),
                }
            )
    return result


def aggregate_platform_status(all_alerts: list[dict[str, Any]], audit_type: str) -> str:
    """Derive OK/WARNING/CRITICAL from a list of site-dashboard alerts for a given audit_type."""
    has_critical = any(a["audit_type"] == audit_type and a["severity"] == SEVERITY_CRITICAL for a in all_alerts)
    has_warning = any(a["audit_type"] == audit_type and a["severity"] == SEVERITY_WARNING for a in all_alerts)
    if has_critical:
        return SEVERITY_CRITICAL
    if has_warning:
        return SEVERITY_WARNING
    return HEALTH_OK


def fleet_entry_for_dir(plt_dir: str) -> tuple[str, str]:
    """Map a platform directory to (label, schema_name) for fleet nav trees.

    Uses the platform registry to resolve display names and schema names
    from report_dir paths.
    """
    reg = default_registry()
    for entry in reg.entries:
        if entry.report_dir == plt_dir:
            label = entry.display_name or entry.platform.capitalize()
            schema_name = (entry.schema_names[0] if entry.schema_names
                           else entry.schema_name or entry.platform)
            return (label, schema_name)
    leaf = plt_dir.split("/")[-1]
    return (leaf.capitalize(), leaf)


def fleet_entries_for_dir(plt_dir: str) -> list[tuple[str, str]]:
    """Return all (display_name, schema_name) pairs for a platform directory.

    When multiple schemas share the same report_dir (e.g. vcenter, esxi, vm
    all under vmware/vcenter), this returns one entry per schema so fleet nav
    trees can link to all fleet reports.
    """
    from ..schema_loader import discover_schemas

    reg = default_registry()
    for entry in reg.entries:
        if entry.report_dir == plt_dir and len(entry.schema_names) > 1:
            all_schemas = discover_schemas()
            results = []
            for name in entry.schema_names:
                schema = all_schemas.get(name)
                label = schema.display_name if schema else name.replace("_", " ").title()
                results.append((label, name))
            return results
    # Fallback: single entry
    return [fleet_entry_for_dir(plt_dir)]


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
        if sev not in (SEVERITY_CRITICAL, SEVERITY_WARNING):
            continue
        result.append(
            {
                "host": hostname,
                "severity": sev,
                "category": alert.get("category", category_default),
                "audit_type": audit_type,
                "message": alert.get("message", ""),
                "raw": dict(alert),
            }
        )
    return result
