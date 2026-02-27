"""Reusable alert evaluation and summarization logic."""

from typing import Any

from ncs_reporter.primitives import canonical_severity, safe_list

# Common truthy values from Jinja / YAML / filters
_TRUTHY_STRINGS = frozenset(("true", "yes", "y", "1", "on"))
_FALSY_STRINGS = frozenset(("false", "no", "n", "0", "off", "", "none", "null"))

# Extra fields allowed to pass through from check defs into produced alerts.
_PASSTHROUGH_KEYS = (
    "affected_items",
    "recommendation",
    "remediation",
    "runbook",
    "links",
    "id",
    "source",
)


def is_truthy(value: Any) -> bool:
    """
    Normalize condition values that Ansible/Jinja may produce.
    """
    if value is True:
        return True
    if value is False or value is None:
        return False

    if isinstance(value, (int, float)):
        return value == 1

    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUTHY_STRINGS:
            return True
        if v in _FALSY_STRINGS:
            return False
        return False

    return False


def normalize_detail(detail: Any) -> dict[str, Any]:
    """Ensure detail is always a mapping."""
    if detail is None:
        return {}
    if isinstance(detail, dict):
        return detail
    return {"value": detail}


def build_alerts(checks: list[Any]) -> list[dict[str, Any]]:
    """
    Filters a list of check definitions to those where condition is truthy.
    """
    checks = safe_list(checks)
    if not checks:
        return []

    alerts = []
    for check in checks:
        if not isinstance(check, dict):
            continue

        if not is_truthy(check.get("condition")):
            continue

        severity = check.get("severity") or "INFO"
        category = check.get("category") or "uncategorized"
        message = check.get("message") or ""

        alert = {
            "severity": severity,
            "category": category,
            "message": message,
            "detail": normalize_detail(check.get("detail", {})),
            "affected_items": safe_list(check.get("affected_items", [])),
        }

        # Handle other passthrough keys
        for key in _PASSTHROUGH_KEYS:
            if key == "affected_items":
                continue
            if key in check:
                val = check.get(key)
                if val is not None:
                    alert[key] = val

        alerts.append(alert)

    return alerts


def health_rollup(alerts: list[Any]) -> str:
    """
    Returns overall health status based on the highest severity in a list of alerts.
    """
    alerts = safe_list(alerts)
    if not alerts:
        return "HEALTHY"

    severities = set()
    for a in alerts:
        if isinstance(a, dict):
            severities.add(canonical_severity(a.get("severity", "INFO")))

    if "CRITICAL" in severities:
        return "CRITICAL"
    if "WARNING" in severities:
        return "WARNING"
    return "HEALTHY"


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

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        severity = canonical_severity(alert.get("severity", "INFO"))
        if severity == "CRITICAL":
            summary["critical_count"] += 1
        elif severity == "WARNING":
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


def append_alerts(existing_alerts: list[Any], new_alerts: Any) -> list[Any]:
    """
    Merges new_alerts into existing_alerts.
    """
    out = list(existing_alerts or [])
    if new_alerts is None:
        return out
    if isinstance(new_alerts, list):
        out.extend(new_alerts)
        return out
    out.append(new_alerts)
    return out
