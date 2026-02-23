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


_TRUTHY = frozenset([True, "True", "true", "yes", "1", 1])


def build_alerts(checks):
    """
    Filters a list of check definitions to those where condition is truthy.
    Returns a list of alert dicts with severity, category, message, detail.

    Each check dict:
      condition: bool | str  - evaluated by Jinja2 before reaching this filter
      severity:  str         - CRITICAL | WARNING | INFO
      category:  str         - capacity | performance | availability | patching |
                               maintenance | security | configuration | connectivity
      message:   str         - human readable description
      detail:    dict        - optional extra context (default {})
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

    Designed for tiered capacity checks where only the highest severity fires.

    Args:
        value:        float  - current usage percentage
        category:     str    - alert category (e.g. 'capacity')
        message:      str    - base message; '{severity}' and '{pct}' are available
                               as format vars if needed, but plain strings work fine
        critical_pct: float  - threshold above which severity is CRITICAL
        warning_pct:  float  - threshold above which severity is WARNING
        detail:       dict   - optional extra context merged into alert detail

    Returns:
        list: zero or one alert dict
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


class FilterModule(object):
    def filters(self):
        return {
            "build_alerts": build_alerts,
            "threshold_alert": threshold_alert,
        }
