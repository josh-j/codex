"""VMware-specific adapters for core report aggregation."""


def _as_dict(value):
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value):
    return list(value) if isinstance(value, list) else []


def _normalize_legacy_vcenter_payload(audit_type, report):
    """Normalize older discovery/audit exports into the report-view canonical shape."""
    report = _as_dict(report)
    vcenter_alerts = _as_list(report.get("alerts"))
    vcenter_health = _as_dict(report.get("vcenter_health"))

    return {
        "discovery": _as_dict(report.get("inventory") or report.get("vmware_ctx")),
        "alerts": vcenter_alerts,
        "summary": _as_dict(report.get("summary")),
        "health": report.get("health", "OK"),
        "vcenter_health": {
            "alerts": vcenter_alerts,
            "data": _as_dict(vcenter_health.get("data")),
            "health": vcenter_health.get("health", report.get("health", "OK")),
        },
        "audit_type": str(audit_type or ""),
    }


def normalize_aggregated_report(hostname, audit_type, report):
    """
    Normalize VMware report payloads into the canonical shape expected by fleet templates.

    Returns (audit_type, report).
    """
    _ = hostname  # Reserved for future host-specific shaping.
    report = _as_dict(report)

    if audit_type in ("discovery", "vcenter", "vcenter_health") and (
        "inventory" in report or "vmware_ctx" in report
    ):
        report = _normalize_legacy_vcenter_payload(audit_type, report)

    return audit_type, report
