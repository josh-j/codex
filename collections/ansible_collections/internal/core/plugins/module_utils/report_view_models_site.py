"""Site dashboard reporting view-model builders."""

import importlib.util
from pathlib import Path

try:
    from .report_view_models_common import _count_alerts, _iter_hosts, _status_from_health, canonical_severity
    from .report_view_models_linux import _coerce_linux_audit
    from .report_view_models_stig import build_stig_fleet_view
    from .report_view_models_vmware import _coerce_vmware_bundle, _extract_cluster_list
except ImportError:
    _base = Path(__file__).resolve().parent

    def _load(name):
        path = _base / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"internal_core_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    _common = _load("report_view_models_common")
    _linux = _load("report_view_models_linux")
    _stig = _load("report_view_models_stig")
    _vmware = _load("report_view_models_vmware")
    _count_alerts = _common._count_alerts
    _iter_hosts = _common._iter_hosts
    _status_from_health = _common._status_from_health
    canonical_severity = _common.canonical_severity
    _coerce_linux_audit = _linux._coerce_linux_audit
    build_stig_fleet_view = _stig.build_stig_fleet_view
    _coerce_vmware_bundle = _vmware._coerce_vmware_bundle
    _extract_cluster_list = _vmware._extract_cluster_list


def build_site_dashboard_view(
    aggregated_hosts,
    inventory_groups=None,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    inventory_groups = dict(inventory_groups or {})
    all_alerts = []
    compute_nodes = []
    stig_fleet = build_stig_fleet_view(
        aggregated_hosts,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        linux_audit, _stig = _coerce_linux_audit(bundle)
        if linux_audit:
            for alert in list(linux_audit.get("alerts") or []):
                sev = canonical_severity((alert or {}).get("severity"))
                if sev in ("CRITICAL", "WARNING"):
                    all_alerts.append({"severity": sev, "host": hostname, "audit_type": "system"})

        vmw = _coerce_vmware_bundle(bundle)
        if vmw.get("discovery") or vmw.get("vcenter_health"):
            vm_alerts = _count_alerts(vmw.get("alerts"))
            status = _status_from_health(
                dict(vmw.get("vcenter_health") or {}).get("health") or dict(vmw.get("audit") or {}).get("health")
            )
            clusters = _extract_cluster_list(vmw)
            if clusters or vm_alerts["total"] or dict(vmw.get("vcenter_health") or {}):
                compute_nodes.append(
                    {
                        "host": hostname,
                        "status": {"raw": status},
                        "clusters": clusters,
                        "links": {"fleet_dashboard": "platform/vmware/vmware_health_report.html"},
                    }
                )
                for _ in range(vm_alerts["critical"]):
                    all_alerts.append({"severity": "CRITICAL", "host": hostname, "audit_type": "vcenter"})
                for _ in range(vm_alerts["warning"]):
                    all_alerts.append({"severity": "WARNING", "host": hostname, "audit_type": "vcenter"})

        windows_audit = dict(dict(bundle or {}).get("windows_audit") or dict(bundle or {}).get("windows") or {})
        if windows_audit:
            win_status = _status_from_health(windows_audit.get("health"))
            if win_status == "CRITICAL":
                all_alerts.append({"severity": "CRITICAL", "host": hostname, "audit_type": "windows_audit"})
            elif win_status == "WARNING":
                all_alerts.append({"severity": "WARNING", "host": hostname, "audit_type": "windows_audit"})

    linux_critical = any(a["audit_type"] == "system" and a["severity"] == "CRITICAL" for a in all_alerts)
    linux_warning = any(a["audit_type"] == "system" and a["severity"] == "WARNING" for a in all_alerts)
    linux_status = "CRITICAL" if linux_critical else ("WARNING" if linux_warning else "OK")

    vmware_critical = any("vcenter" in a["audit_type"] and a["severity"] == "CRITICAL" for a in all_alerts)
    vmware_warning = any("vcenter" in a["audit_type"] and a["severity"] == "WARNING" for a in all_alerts)
    vmware_status = "CRITICAL" if vmware_critical else ("WARNING" if vmware_warning else "OK")
    windows_critical = any(a["audit_type"] == "windows_audit" and a["severity"] == "CRITICAL" for a in all_alerts)
    windows_warning = any(a["audit_type"] == "windows_audit" and a["severity"] == "WARNING" for a in all_alerts)
    windows_status = "CRITICAL" if windows_critical else ("WARNING" if windows_warning else "OK")

    linux_count = len(list(inventory_groups.get("ubuntu_servers") or []))
    vmware_count = len(list(inventory_groups.get("vcenters") or []))
    windows_count = len(list(inventory_groups.get("windows_servers") or inventory_groups.get("windows") or []))
    totals = _count_alerts(all_alerts)

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "totals": totals,
        "alerts": sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", a.get("host", ""))),
        "platforms": {
            "linux": {
                "asset_count": linux_count,
                "asset_label": "Nodes",
                "status": {"raw": linux_status},
                "links": {"fleet_dashboard": "platform/ubuntu/ubuntu_health_report.html"},
            },
            "vmware": {
                "asset_count": vmware_count,
                "asset_label": "Clusters",
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
