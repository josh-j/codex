"""Site dashboard reporting view-model builders."""

from typing import Any

from .common import (
    _count_alerts,
    _iter_hosts,
    _status_from_health,
    canonical_severity,
    safe_list,
)
from .linux import _coerce_linux_audit
from .stig import build_stig_fleet_view
from .vmware import _coerce_vmware_bundle, _extract_cluster_list


def build_site_dashboard_view(
    aggregated_hosts: dict[str, Any],
    inventory_groups: dict[str, Any] | None = None,
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    groups = dict(inventory_groups or {})
    all_alerts: list[dict[str, Any]] = []
    compute_nodes: list[dict[str, Any]] = []
    stig_fleet = build_stig_fleet_view(
        aggregated_hosts,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        # 1. Linux System Audit
        linux_audit, _stig = _coerce_linux_audit(bundle)
        if linux_audit:
            linux_alerts = list(linux_audit.get("alerts") or [])
            for alert in linux_alerts:
                sev = canonical_severity((alert or {}).get("severity"))
                if sev in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": sev,
                        "host": hostname,
                        "audit_type": "linux_system",
                        "category": (alert or {}).get("category", "System"),
                        "message": (alert or {}).get("message", ""),
                    })
            # Fallback: if health is bad but no alerts, add a synthetic one
            if not linux_alerts:
                l_status = _status_from_health(linux_audit.get("health"))
                if l_status in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": l_status,
                        "host": hostname,
                        "audit_type": "linux_system",
                        "category": "System",
                        "message": f"System reported {l_status} health status.",
                    })

        # 2. VMware vCenter Audit
        vmw = _coerce_vmware_bundle(bundle)
        if vmw.get("discovery") or vmw.get("vcenter_health"):
            vm_alerts_list = safe_list(vmw.get("alerts"))
            vm_counts = _count_alerts(vm_alerts_list)
            status = _status_from_health(
                dict(vmw.get("vcenter_health") or {}).get("health") or dict(vmw.get("audit") or {}).get("health")
            )
            clusters = _extract_cluster_list(vmw)
            if clusters or vm_counts["total"] or dict(vmw.get("vcenter_health") or {}):
                compute_nodes.append(
                    {
                        "host": hostname,
                        "status": {"raw": status},
                        "clusters": clusters,
                        "links": {"fleet_dashboard": "platform/vmware/vmware_health_report.html"},
                    }
                )
                for alert in vm_alerts_list:
                    sev = canonical_severity((alert or {}).get("severity"))
                    if sev in ("CRITICAL", "WARNING"):
                        all_alerts.append({
                            "severity": sev,
                            "host": hostname,
                            "audit_type": "vmware_vcenter",
                            "category": (alert or {}).get("category", "vmware"),
                            "message": (alert or {}).get("message", ""),
                        })
                # Fallback
                if not vm_alerts_list and status in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": status,
                        "host": hostname,
                        "audit_type": "vmware_vcenter",
                        "category": "vmware",
                        "message": f"vCenter reported {status} health status.",
                    })

        # 3. Windows Audit
        windows_audit = dict(dict(bundle or {}).get("windows_audit") or {})
        if windows_audit:
            win_alerts = list(windows_audit.get("alerts") or [])
            win_status = _status_from_health(windows_audit.get("health"))
            for alert in win_alerts:
                sev = canonical_severity((alert or {}).get("severity"))
                if sev in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": sev,
                        "host": hostname,
                        "audit_type": "windows_audit",
                        "category": (alert or {}).get("category", "windows"),
                        "message": (alert or {}).get("message", ""),
                    })
            # Fallback (matches old behavior for Windows)
            if not win_alerts and win_status in ("CRITICAL", "WARNING"):
                all_alerts.append({
                    "severity": win_status,
                    "host": hostname,
                    "audit_type": "windows_audit",
                    "category": "windows",
                    "message": f"Windows reported {win_status} health status.",
                })

    linux_critical = any(a["audit_type"] == "linux_system" and a["severity"] == "CRITICAL" for a in all_alerts)
    linux_warning = any(a["audit_type"] == "linux_system" and a["severity"] == "WARNING" for a in all_alerts)
    linux_status = "CRITICAL" if linux_critical else ("WARNING" if linux_warning else "OK")

    vmware_critical = any(a["audit_type"] == "vmware_vcenter" and a["severity"] == "CRITICAL" for a in all_alerts)
    vmware_warning = any(a["audit_type"] == "vmware_vcenter" and a["severity"] == "WARNING" for a in all_alerts)
    vmware_status = "CRITICAL" if vmware_critical else ("WARNING" if vmware_warning else "OK")
    windows_critical = any(a["audit_type"] == "windows_audit" and a["severity"] == "CRITICAL" for a in all_alerts)
    windows_warning = any(a["audit_type"] == "windows_audit" and a["severity"] == "WARNING" for a in all_alerts)
    windows_status = "CRITICAL" if windows_critical else ("WARNING" if windows_warning else "OK")

    linux_count = len(list(groups.get("ubuntu_servers") or []))
    vmware_count = len(list(groups.get("vcenters") or []))
    windows_count = len(list(groups.get("windows_servers") or groups.get("windows") or []))
    totals = _count_alerts(all_alerts)

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "totals": totals,
        "alerts": sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))),
        "platforms": {
            "linux": {
                "asset_count": linux_count,
                "asset_label": "Nodes",
                "status": {"raw": linux_status},
                "links": {"fleet_dashboard": "platform/ubuntu/ubuntu_health_report.html"},
            },
            "vmware": {
                "asset_count": vmware_count,
                "asset_label": "vCenters",
                "status": {"raw": vmware_status},
                "links": {"fleet_dashboard": "platform/vmware/vmware_health_report.html"},
            },
            "windows": {
                "asset_count": windows_count,
                "asset_label": "Nodes",
                "status": {"raw": windows_status},
                "links": {"fleet_dashboard": "platform/windows/windows_health_report.html"},
            },
        },
        "security": {
            "stig_fleet": stig_fleet,
        },
        "compute": {
            "nodes": compute_nodes,
        },
    }
