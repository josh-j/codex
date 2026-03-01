"""STIG normalization logic for ncs_reporter."""

import logging
from typing import Any

from ncs_reporter.models.base import MetadataModel, SummaryModel, AlertModel
from ncs_reporter.models.stig import STIGAuditModel
from ncs_reporter.alerts import health_rollup

logger = logging.getLogger(__name__)


def _severity_to_alert(raw_severity: Any) -> str:
    sev = str(raw_severity or "medium").upper()
    if sev in ("CAT_I", "HIGH", "SEVERE"):
        return "CRITICAL"
    if sev in ("CAT_II", "MEDIUM", "MODERATE"):
        return "WARNING"
    return "INFO"


def _canonical_stig_status(value: Any) -> str:
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


def _row_status(item: dict[str, Any]) -> str:
    return _canonical_stig_status(
        item.get("status") or item.get("finding_status") or item.get("result") or item.get("compliance") or ""
    )


def _row_rule_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("rule_id") or item.get("vuln_id") or item.get("ruleId") or "")


def _row_title(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("rule_title")
        or item.get("rule")
        or item.get("id")
        or item.get("rule_id")
        or "Unknown Rule"
    )


def _row_description(item: dict[str, Any]) -> str:
    return str(
        item.get("checktext") or item.get("details") or item.get("description") or item.get("finding_details") or ""
    )


def _row_severity(item: dict[str, Any]) -> str:
    return item.get("severity") or item.get("cat") or item.get("severity_override") or "medium"


def normalize_stig(raw_bundle: dict[str, Any] | list[dict[str, Any]], stig_target_type: str = "") -> STIGAuditModel:
    """
    Normalize raw STIG results into canonical fleet-ready structure.
    """
    # raw_bundle might be the raw JSON/XML from an artifact
    rows: list[dict[str, Any]] = []
    collected_at = ""

    # Try to detect target type from the bundle if not provided
    detected_type = stig_target_type

    if isinstance(raw_bundle, list):
        rows = raw_bundle
    elif isinstance(raw_bundle, dict):
        # Handle cases where it's wrapped in 'data' from the callback plugin
        rows = raw_bundle.get("data") or raw_bundle.get("full_audit") or []
        collected_at = raw_bundle.get("metadata", {}).get("timestamp", "")

        if not detected_type:
            detected_type = str(raw_bundle.get("target_type") or "")

        if not isinstance(rows, list):
            rows = [rows]

    # If still no type, peek at rules to guess (useful for raw XCCDF-to-JSON results)
    if not detected_type and rows:
        first = rows[0]
        if isinstance(first, dict):
            rv = str(first.get("rule_version") or "").upper()
            if rv.startswith("VMCH"):
                detected_type = "vm"
            elif rv.startswith("ESXI"):
                detected_type = "esxi"
            elif rv.startswith("WN") or rv.startswith("MS"):
                detected_type = "windows"
            elif rv.startswith("UBTU") or rv.startswith("GEN"):
                detected_type = "ubuntu"

    logger.debug(
        "normalize_stig: input type=%s, target_type=%s, detected=%s",
        type(raw_bundle).__name__,
        stig_target_type,
        detected_type,
    )

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
                    "target_type": str(detected_type or ""),
                },
            }
        )

    critical_count = len([a for a in alerts if a.get("severity") == "CRITICAL"])
    warning_count = len([a for a in alerts if a.get("severity") == "WARNING"])
    summary_dict = {
        "total": len(full_audit),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "info_count": len(alerts) - critical_count - warning_count,
        "by_category": {"security_compliance": len(alerts)},
    }

    return STIGAuditModel(
        metadata=MetadataModel(
            audit_type="stig",
            timestamp=collected_at,
        ),
        target_type=stig_target_type,
        health=health_rollup(alerts),
        summary=SummaryModel.model_validate(summary_dict),
        alerts=[AlertModel.model_validate(a) for a in alerts],
        full_audit=full_audit,
    )
