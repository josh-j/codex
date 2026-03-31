"""Reusable alert evaluation and summarization logic."""

from typing import Any

from ncs_reporter.primitives import canonical_severity, safe_list


def health_rollup(alerts: list[Any]) -> str:
    """
    Returns overall health status based on the highest severity in a list of alerts.
    """
    from .constants import HEALTH_CRITICAL, HEALTH_HEALTHY, HEALTH_WARNING, SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING
    alerts = safe_list(alerts)
    if not alerts:
        return HEALTH_HEALTHY

    severities = set()
    for a in alerts:
        if isinstance(a, dict):
            severities.add(canonical_severity(a.get("severity", SEVERITY_INFO)))

    if SEVERITY_CRITICAL in severities:
        return HEALTH_CRITICAL
    if SEVERITY_WARNING in severities:
        return HEALTH_WARNING
    return HEALTH_HEALTHY


def summarize_alerts(alerts: list[Any]) -> dict[str, Any]:
    """
    Returns a summary dict tallying alert counts by severity and category.
    """
    alerts = safe_list(alerts)
    summary: dict[str, Any] = {
        "total": len(alerts),
        "critical_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "by_category": {},
    }

    from .constants import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING
    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        severity = canonical_severity(alert.get("severity", SEVERITY_INFO))
        if severity == SEVERITY_CRITICAL:
            summary["critical_count"] += 1
        elif severity == SEVERITY_WARNING:
            summary["warning_count"] += 1
        else:
            summary["info_count"] += 1

        cat = str(alert.get("category", "uncategorized")).lower()
        summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1

    return summary


def compute_audit_rollups(alerts: list[Any]) -> dict[str, Any]:
    """
    Composes summarize_alerts + health_rollup into a standard rollup dict.
    """
    return {"summary": summarize_alerts(alerts), "health": health_rollup(alerts)}
