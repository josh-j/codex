"""Site dashboard reporting view-model builders."""

from typing import Any

from .common import (
    _count_alerts,
    _iter_hosts,
    _status_from_health,
    aggregate_platform_status,
    build_meta,
    extract_platform_alerts,
    safe_list,
)
from .stig import build_stig_fleet_view


def _get_schema_audit(bundle: dict[str, Any], *names: str) -> dict[str, Any] | None:
    """Return the first matching schema audit from a host bundle.

    Checks ``schema_<name>`` keys in preference order, then legacy key aliases.
    """
    _legacy: dict[str, str] = {
        "linux": "linux_system",
        "vcenter": "vmware_vcenter",
        "windows": "windows_audit",
    }
    for name in names:
        audit = bundle.get(f"schema_{name}")
        if audit:
            return dict(audit)
        legacy = _legacy.get(name)
        if legacy:
            audit = bundle.get(legacy)
            if audit:
                return dict(audit)
    return None


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
        # 1. Linux
        linux_audit = _get_schema_audit(bundle, "linux")
        if linux_audit:
            linux_alerts = list(linux_audit.get("alerts") or [])
            all_alerts.extend(extract_platform_alerts(linux_alerts, hostname, "schema_linux", "System"))
            if not linux_alerts:
                l_status = _status_from_health(linux_audit.get("health"))
                if l_status in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": l_status,
                        "host": hostname,
                        "audit_type": "schema_linux",
                        "category": "System",
                        "message": f"System reported {l_status} health status.",
                    })

        # 2. VMware vCenter
        vmware_audit = _get_schema_audit(bundle, "vcenter")
        if vmware_audit:
            vm_alerts_list = safe_list(vmware_audit.get("alerts"))
            vm_counts = _count_alerts(vm_alerts_list)
            status = _status_from_health(vmware_audit.get("health"))
            if vm_counts["total"] or vmware_audit.get("health"):
                compute_nodes.append({
                    "host": hostname,
                    "status": {"raw": status},
                    "clusters": [],
                    "links": {"fleet_dashboard": "platform/vcenter/vcenter_fleet_report.html"},
                })
                all_alerts.extend(extract_platform_alerts(vm_alerts_list, hostname, "schema_vcenter", "VMware"))
                if not vm_alerts_list and status in ("CRITICAL", "WARNING"):
                    all_alerts.append({
                        "severity": status,
                        "host": hostname,
                        "audit_type": "schema_vcenter",
                        "category": "VMware",
                        "message": f"vCenter reported {status} health status.",
                    })

        # 3. Windows
        windows_audit = _get_schema_audit(bundle, "windows")
        if windows_audit:
            win_alerts = list(windows_audit.get("alerts") or [])
            win_status = _status_from_health(windows_audit.get("health"))
            all_alerts.extend(extract_platform_alerts(win_alerts, hostname, "schema_windows", "Windows"))
            if not win_alerts and win_status in ("CRITICAL", "WARNING"):
                all_alerts.append({
                    "severity": win_status,
                    "host": hostname,
                    "audit_type": "schema_windows",
                    "category": "Windows",
                    "message": f"Windows reported {win_status} health status.",
                })

    linux_status = aggregate_platform_status(all_alerts, "schema_linux")
    vmware_status = aggregate_platform_status(all_alerts, "schema_vcenter")
    windows_status = aggregate_platform_status(all_alerts, "schema_windows")

    linux_count = len(list(groups.get("ubuntu_servers") or []))
    vmware_count = len(list(groups.get("vcenters") or []))
    windows_count = len(list(groups.get("windows_servers") or groups.get("windows") or []))
    totals = _count_alerts(all_alerts)

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "totals": totals,
        "alerts": sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))),
        "platforms": {
            "linux": {
                "asset_count": linux_count,
                "asset_label": "Nodes",
                "status": {"raw": linux_status},
                "links": {"fleet_dashboard": "platform/ubuntu/linux_fleet_report.html"},
            },
            "vmware": {
                "asset_count": vmware_count,
                "asset_label": "vCenters",
                "status": {"raw": vmware_status},
                "links": {"fleet_dashboard": "platform/vcenter/vcenter_fleet_report.html"},
            },
            "windows": {
                "asset_count": windows_count,
                "asset_label": "Nodes",
                "status": {"raw": windows_status},
                "links": {"fleet_dashboard": "platform/windows/windows_fleet_report.html"},
            },
        },
        "security": {
            "stig_fleet": stig_fleet,
        },
        "compute": {
            "nodes": compute_nodes,
        },
    }
