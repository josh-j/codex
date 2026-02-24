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
# Ansible evaluates Jinja2 expressions before passing values to Python filters,
# so boolean conditions arrive as Python bools, strings ("True"/"False"),
# or integers. All forms are handled explicitly.
_TRUTHY = frozenset([True, "True", "true", "yes", "1", 1])


def build_alerts(checks):
    """
    Filters a list of check definitions to those where condition is truthy.
    Returns a list of alert dicts with severity, category, message, detail.

    Usage:
      vars:
        checks:
          - condition: "{{ some_value | int > threshold }}"
            severity:  CRITICAL
            category:  capacity
            message:   "Something is wrong"
            detail:    {}   # optional
      set_fact:
        my_alerts: "{{ checks | internal.core.build_alerts }}"
    """
    alerts = []
    for check in checks:
        if check.get("condition") in _TRUTHY:
            alerts.append(
                {
                    "severity": check["severity"],
                    "category": check["category"],
                    "message": check["message"],
                    "detail": check.get("detail", {}),
                }
            )
    return alerts


def threshold_alert(value, category, message, critical_pct, warning_pct, detail=None):
    """
    Returns a single-element list with a CRITICAL or WARNING alert if value
    exceeds the respective threshold, or an empty list if neither is met.
    Only the highest threshold fires — never both.
    """
    value = float(value)
    if value > float(critical_pct):
        severity, threshold = "CRITICAL", critical_pct
    elif value > float(warning_pct):
        severity, threshold = "WARNING", warning_pct
    else:
        return []

    alert = {
        "severity": severity,
        "category": category,
        "message": message,
        "detail": {"usage_pct": value, "threshold_pct": threshold},
    }
    if detail:
        alert["detail"].update(detail)
    return [alert]


def health_rollup(alerts):
    """
    Returns overall health status based on the highest severity in a list of alerts.
    Returns: 'CRITICAL', 'WARNING', or 'HEALTHY'
    """
    if not alerts:
        return "HEALTHY"
    severities = {a.get("severity", "INFO").upper() for a in alerts}
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
        severity = alert.get("severity", "INFO").upper()
        if severity == "CRITICAL":
            summary["critical_count"] += 1
        elif severity == "WARNING":
            summary["warning_count"] += 1
        elif severity in ("INFO", "OK"):
            summary["info_count"] += 1

        cat = alert.get("category", "uncategorized").lower()
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
