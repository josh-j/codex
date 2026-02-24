"""VMware-specific adapters for core report aggregation."""


def normalize_aggregated_report(hostname, audit_type, report):
    """
    Normalize VMware report payloads into the canonical shape expected by fleet templates.

    Returns (audit_type, report).
    """
    _ = hostname  # Reserved for future host-specific shaping.
    report = dict(report or {})

    if audit_type in ("discovery", "vcenter", "vcenter_health") and (
        "inventory" in report or "vmware_ctx" in report
    ):
        _vcenter_alerts = report.get("alerts", [])
        _vcenter_health = report.get("vcenter_health", {})
        report = {
            "discovery": report.get("inventory", report.get("vmware_ctx", {})),
            "alerts": _vcenter_alerts,
            "summary": report.get("summary", {}),
            "health": report.get("health", "OK"),
            "vcenter_health": {
                "alerts": _vcenter_alerts,
                "data": _vcenter_health.get("data", {}),
                "health": _vcenter_health.get("health", report.get("health", "OK")),
            },
            "audit_type": audit_type,
        }

    return audit_type, report
