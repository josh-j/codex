#!/usr/bin/env python3

from __future__ import absolute_import, division, print_function

__metaclass__ = type


def _severity_to_alert(raw_severity):
    sev = str(raw_severity or "medium").upper()
    if sev in ("CAT_I", "HIGH", "SEVERE"):
        return "CRITICAL"
    if sev in ("CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
    return "INFO"


def normalize_stig_results(audit_full_list, stig_target_type=""):
    """
    Normalize STIG audit rows into canonical full_audit/violations/alerts/summary structures.
    """
    rows = list(audit_full_list or [])

    full_audit = []
    violations = []
    alerts = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        normalized = dict(item)
        normalized["status"] = str(item.get("status", "")).lower()
        full_audit.append(normalized)

        if normalized["status"] != "failed":
            continue

        violations.append(normalized)

        raw_sev = item.get("severity", "medium")
        alerts.append(
            {
                "severity": _severity_to_alert(raw_sev),
                "category": "security_compliance",
                "message": "STIG Violation: "
                + str(item.get("title") or item.get("id") or "Unknown Rule"),
                "detail": {
                    "rule_id": str(item.get("id", "") or ""),
                    "description": str(
                        item.get("checktext") or item.get("details") or ""
                    ),
                    "original_severity": str(raw_sev).upper(),
                    "target_type": str(stig_target_type or ""),
                },
            }
        )

    critical_count = len([a for a in alerts if a.get("severity") == "CRITICAL"])
    warning_count = len([a for a in alerts if a.get("severity") == "WARNING"])
    passed_count = len([r for r in full_audit if r.get("status") == "pass"])

    return {
        "full_audit": full_audit,
        "violations": violations,
        "alerts": alerts,
        "summary": {
            "total": len(full_audit),
            "violations": len(violations),
            "passed": passed_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
        },
    }


class FilterModule(object):
    def filters(self):
        return {
            "normalize_stig_results": normalize_stig_results,
        }
