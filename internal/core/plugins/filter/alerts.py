#!/usr/bin/env python3
# collections/ansible_collections/internal/core/plugins/filter/alerts.py
#
# build_alerts: evaluates a list of check definitions and returns alerts
# for any where condition is truthy.
#
# Ansible evaluates Jinja2 expressions before passing values to Python filters,
# so boolean conditions arrive as Python bools, strings ("True"/"False"),
# or integers. All forms are handled explicitly.
#
# Usage:
#   vars:
#     checks:
#       - condition: "{{ some_value | int > threshold }}"
#         severity: CRITICAL
#         category: capacity
#         message: "Something is wrong"
#         detail: {}   # optional
#         affected_items: []  # optional (preserved)
#   set_fact:
#     my_alerts: "{{ checks | internal.core.build_alerts }}"

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
  name: build_alerts
  short_description: Filter check dicts to those where condition is truthy
  version_added: "1.0"
  author: Internal
  description:
    - Filters a list of check definition dicts to those where condition is truthy.
    - Returns alert dicts with severity, category, message, and detail fields.
  options:
    _input:
      description: List of check definition dicts
      type: list
      required: true
"""

# Common truthy values from Jinja / YAML / filters
_TRUTHY_STRINGS = frozenset(("true", "yes", "y", "1", "on"))
_FALSY_STRINGS = frozenset(("false", "no", "n", "0", "off", "", "none", "null"))


# Extra fields allowed to pass through from check defs into produced alerts.
# Keeps dashboards and exports rich without forcing complex Jinja.
_PASSTHROUGH_KEYS = (
    "affected_items",
    "recommendation",
    "remediation",
    "runbook",
    "links",
    "id",
    "source",
)


def _is_truthy(value):
    """
    Normalize condition values that Ansible/Jinja may produce.
    Accepts bool/int/float/str/None.
    """
    if value is True:
        return True
    if value is False or value is None:
        return False

    # Some templates emit ints (0/1) or strings.
    if isinstance(value, (int, float)):
        return value == 1

    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUTHY_STRINGS:
            return True
        if v in _FALSY_STRINGS:
            return False
        # If the string is something unexpected, treat as falsy to avoid noisy false-positives.
        return False

    # Unknown types: default to False
    return False


def _normalize_detail(detail):
    """
    Ensure detail is always a mapping. If a non-mapping is provided, wrap it.
    """
    if detail is None:
        return {}
    if isinstance(detail, dict):
        return detail
    return {"value": detail}


def build_alerts(checks):
    """
    Filters a list of check definitions to those where condition is truthy.
    Returns a list of alert dicts with severity, category, message, detail.

    Also preserves optional enrichment fields (e.g., affected_items) if present.
    """
    if not checks:
        return []

    alerts = []
    # Defensive: callers sometimes pass a single mapping; accept it.
    if isinstance(checks, dict):
        checks = [checks]

    for check in checks:
        if not isinstance(check, dict):
            continue

        if not _is_truthy(check.get("condition")):
            continue

        severity = check.get("severity") or "INFO"
        category = check.get("category") or "uncategorized"
        message = check.get("message") or ""

        alert = {
            "severity": severity,
            "category": category,
            "message": message,
            "detail": _normalize_detail(check.get("detail", {})),
        }

        # Pass through enrichment fields if provided
        for key in _PASSTHROUGH_KEYS:
            if key in check:
                val = check.get(key)
                # Preserve empty lists/dicts if explicitly set; drop None.
                if val is not None:
                    alert[key] = val

        alerts.append(alert)

    return alerts


def threshold_alert(value, category, message, critical_pct, warning_pct, detail=None):
    """
    Returns a single-element list with a CRITICAL or WARNING alert if value
    exceeds the respective threshold, or an empty list if neither is met.
    Only the highest threshold fires — never both.
    """
    try:
        value_f = float(value)
        crit_f = float(critical_pct)
        warn_f = float(warning_pct)
    except (TypeError, ValueError):
        # Avoid hard-failing audits on malformed metrics. If you want visibility,
        # create an explicit "data_quality" check using build_alerts.
        return []

    if value_f > crit_f:
        severity, threshold = "CRITICAL", crit_f
    elif value_f > warn_f:
        severity, threshold = "WARNING", warn_f
    else:
        return []

    alert = {
        "severity": severity,
        "category": category,
        "message": message,
        "detail": {"usage_pct": value_f, "threshold_pct": threshold},
    }
    if detail:
        alert["detail"].update(_normalize_detail(detail))
    return [alert]


def health_rollup(alerts):
    """
    Returns overall health status based on the highest severity in a list of alerts.
    Returns: 'CRITICAL', 'WARNING', or 'HEALTHY'
    """
    if not alerts:
        return "HEALTHY"

    severities = set()
    for a in alerts or []:
        if isinstance(a, dict):
            severities.add(str(a.get("severity", "INFO")).upper())

    if "CRITICAL" in severities:
        return "CRITICAL"
    if "WARNING" in severities:
        return "WARNING"
    return "HEALTHY"


def summarize_alerts(alerts):
    """
    Returns a summary dict tallying alert counts by severity and category.
    Eliminates complex Jinja2 loops in roles.
    """
    alerts = alerts or []
    summary = {
        "total": len(alerts),
        "critical_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "by_category": {},
    }

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        severity = str(alert.get("severity", "INFO")).upper()
        if severity == "CRITICAL":
            summary["critical_count"] += 1
        elif severity == "WARNING":
            summary["warning_count"] += 1
        elif severity in ("INFO", "OK"):
            summary["info_count"] += 1
        else:
            # Unrecognized severities are counted in total but not split out further.
            summary["info_count"] += 1

        cat = str(alert.get("category", "uncategorized")).lower()
        summary["by_category"][cat] = summary["by_category"].get(cat, 0) + 1

    return summary


class FilterModule(object):
    def filters(self):
        return {
            "build_alerts": build_alerts,
            "threshold_alert": threshold_alert,
            "health_rollup": health_rollup,
            "summarize_alerts": summarize_alerts,
        }
