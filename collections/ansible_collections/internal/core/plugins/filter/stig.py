#!/usr/bin/env python3


def _severity_to_alert(raw_severity):
    sev = str(raw_severity or "medium").upper()
    if sev in ("CAT_I", "HIGH", "SEVERE"):
        return "CRITICAL"
    if sev in ("CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
    return "INFO"


def _canonical_stig_status(value):
    text = str(value or "").strip().lower()
    if text in ("failed", "fail", "open", "finding", "non-compliant", "non_compliant"):
        return "failed"
    if text in ("pass", "passed", "compliant", "success", "closed", "notafinding"):
        return "pass"
    if text in ("na", "n/a", "not_applicable", "not applicable"):
        return "na"
    return text


def _row_status(item):
    return _canonical_stig_status(
        item.get("status") or item.get("finding_status") or item.get("result") or item.get("compliance") or ""
    )


def _row_rule_id(item):
    return str(item.get("id") or item.get("rule_id") or item.get("vuln_id") or item.get("ruleId") or "")


def _row_title(item):
    return str(
        item.get("title")
        or item.get("rule_title")
        or item.get("rule")
        or item.get("id")
        or item.get("rule_id")
        or "Unknown Rule"
    )


def _row_description(item):
    return str(
        item.get("checktext") or item.get("details") or item.get("description") or item.get("finding_details") or ""
    )


def _row_severity(item):
    return item.get("severity") or item.get("cat") or item.get("severity_override") or "medium"


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
        normalized["status"] = _row_status(item)
        full_audit.append(normalized)

        if normalized["status"] != "failed":
            continue

        violations.append(normalized)

        raw_sev = _row_severity(item)
        alerts.append(
            {
                "severity": _severity_to_alert(raw_sev),
                "category": "security_compliance",
                "message": "STIG Violation: " + _row_title(item),
                "detail": {
                    "rule_id": _row_rule_id(item),
                    "description": _row_description(item),
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


class FilterModule:
    def filters(self):
        return {
            "normalize_stig_results": normalize_stig_results,
        }
