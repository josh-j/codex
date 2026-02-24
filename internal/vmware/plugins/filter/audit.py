import copy


def build_audit_export_payload(
    vmware_alerts,
    vmware_ctx,
    audit_failed,
    health,
    summary,
    timestamp,
    thresholds,
):
    alerts = list(vmware_alerts or [])
    vmware_ctx = dict(vmware_ctx or {})
    summary = dict(summary or {})
    thresholds = dict(thresholds or {})

    data = {
        "audit_type": "vcenter_health",
        "alerts": alerts,
        "vcenter_health": {
            "health": health,
            "summary": summary,
            "alerts": alerts,
            "audit_failed": bool(audit_failed),
            "data": copy.deepcopy(((vmware_ctx.get("vcenter_health") or {}).get("data") or {})),
        },
        "check_metadata": {
            "engine": "ansible-ncs-vmware",
            "timestamp": timestamp,
            "thresholds": thresholds,
        },
    }
    return data


class FilterModule(object):
    def filters(self):
        return {
            "build_audit_export_payload": build_audit_export_payload,
        }
