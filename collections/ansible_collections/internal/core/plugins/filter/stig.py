
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
        return "open"
    if text in ("fixed", "remediated"):
        return "pass"
    if text in ("pass", "passed", "compliant", "success", "closed", "notafinding"):
        return "pass"
    if text in ("na", "n/a", "not_applicable", "not applicable"):
        return "na"
    return text


def _row_status(item):
    return _canonical_stig_status(
        item.get("status")
        or item.get("finding_status")
        or item.get("result")
        or item.get("compliance")
        or ""
    )


def _row_rule_id(item):
    return str(
        item.get("id")
        or item.get("rule_id")
        or item.get("vuln_id")
        or item.get("ruleId")
        or ""
    )


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
        item.get("checktext")
        or item.get("details")
        or item.get("description")
        or item.get("finding_details")
        or ""
    )


def _row_severity(item):
    return (
        item.get("severity")
        or item.get("cat")
        or item.get("severity_override")
        or "medium"
    )


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
        status = _row_status(item)
        rule_id = _row_rule_id(item)
        title = _row_title(item)
        description = _row_description(item)
        raw_sev = _row_severity(item)

        normalized["status"] = status
        normalized["rule_id"] = rule_id
        normalized["title"] = title
        normalized["description"] = description
        normalized["severity"] = raw_sev

        full_audit.append(normalized)

        if status != "open":
            continue

        violations.append(normalized)

        alerts.append(
            {
                "severity": _severity_to_alert(raw_sev),
                "category": "security_compliance",
                "message": "STIG Violation: " + title,
                "detail": {
                    "rule_id": rule_id,
                    "description": description,
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


def get_adv(settings, key, default="unknown"):
    """
    Look up a value in a list of option_value dicts (key/value pairs).
    """
    settings = settings or []
    for s in settings:
        if isinstance(s, dict) and s.get("key") == key:
            return s.get("value")
    return default


def stig_eval(rules, item=None):
    """
    Evaluates a list of STIG rules against a discovery item.
    Rules are dicts with:
      id: str
      title: str (optional)
      severity: str (optional, default: medium)
      check: bool
      pass_msg: str (optional)
      fail_msg: str (optional)
    """
    results = []
    for rule in rules:
        rule_id = str(rule.get("id", "UNKNOWN"))
        title = str(rule.get("title") or rule_id)
        severity = rule.get("severity", "medium")
        check_passed = bool(rule.get("check", False))

        status = "pass" if check_passed else "open"

        if check_passed:
            details = rule.get("pass_msg") or "Check passed"
        else:
            details = rule.get("fail_msg") or "Check failed"

        results.append(
            {
                "id": rule_id,
                "title": title,
                "status": status,
                "severity": severity,
                "checktext": str(details),
                "fixtext": "",
            }
        )
    return results


class FilterModule:
    def filters(self):
        return {
            "normalize_stig_results": normalize_stig_results,
            "stig_eval": stig_eval,
            "get_adv": get_adv,
        }
