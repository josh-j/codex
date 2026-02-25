"""VMware reporting view-model builders."""

import importlib.util
from pathlib import Path

try:
    from .report_view_models_common import (
        _count_alerts,
        _iter_hosts,
        _optional_float,
        _safe_pct,
        _severity_for_pct,
        _status_from_health,
        safe_list,
        to_int,
    )
except ImportError:
    _helper_path = Path(__file__).resolve().parent / "report_view_models_common.py"
    _spec = importlib.util.spec_from_file_location("internal_core_report_view_models_common", _helper_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _count_alerts = _mod._count_alerts
    _iter_hosts = _mod._iter_hosts
    _optional_float = _mod._optional_float
    _safe_pct = _mod._safe_pct
    _severity_for_pct = _mod._severity_for_pct
    _status_from_health = _mod._status_from_health
    safe_list = _mod.safe_list
    to_int = _mod.to_int


def _iter_vmware_hosts(aggregated_hosts):
    return _iter_hosts(aggregated_hosts)


def _coerce_vmware_bundle(bundle):
    bundle = dict(bundle or {})

    # If the aggregator used nested directories, the bundle might be:
    # {"vcenter": {...}, "discovery": {...}}
    # OR it might be flat if only one audit type was loaded.
    discovery = dict(bundle.get("discovery") or {})
    audit = dict(bundle.get("vcenter") or bundle.get("vcenter_health") or bundle.get("audit") or {})

    # If both are empty, check if the bundle ITSELF is the audit data (flat load)
    if not discovery and not audit:
        if "vcenter_health" in bundle or "inventory" in bundle:
            audit = bundle
        if "health" in bundle and isinstance(bundle.get("health"), dict):
            # Might be discovery data loaded directly
            discovery = bundle

    vcenter_health = dict(audit.get("vcenter_health") or bundle.get("vcenter_health") or {})
    alerts = safe_list(audit.get("alerts") or vcenter_health.get("alerts") or bundle.get("alerts"))

    return {
        "discovery": discovery,
        "audit": audit,
        "vcenter_health": vcenter_health,
        "alerts": alerts,
    }


def _extract_vmware_inventory_summary(bundle_view):
    discovery = dict(bundle_view.get("discovery") or {})
    summary = dict(discovery.get("summary") or {})
    return {
        "clusters": to_int(summary.get("clusters", 0), 0),
        "hosts": to_int(summary.get("hosts", 0), 0),
        "vms": to_int(summary.get("vms", 0), 0),
    }


def _extract_vmware_utilization(bundle_view):
    vh = dict(bundle_view.get("vcenter_health") or {})
    util = dict((vh.get("data") or {}).get("utilization") or {})
    cpu_total = to_int(util.get("cpu_total_mhz", 0), 0)
    cpu_used = to_int(util.get("cpu_used_mhz", 0), 0)
    mem_total = to_int(util.get("mem_total_mb", 0), 0)
    mem_used = to_int(util.get("mem_used_mb", 0), 0)

    cpu_pct = _optional_float(util.get("cpu_pct"))
    if cpu_pct is None:
        cpu_pct = _safe_pct(cpu_used, cpu_total)
    mem_pct = _optional_float(util.get("mem_pct"))
    if mem_pct is None:
        mem_pct = _safe_pct(mem_used, mem_total)

    return {
        "cpu": {
            "used_mhz": cpu_used,
            "total_mhz": cpu_total,
            "pct": round(float(cpu_pct), 1),
        },
        "memory": {
            "used_mb": mem_used,
            "total_mb": mem_total,
            "pct": round(float(mem_pct), 1),
        },
    }


def _extract_vmware_version(bundle_view):
    discovery = dict(bundle_view.get("discovery") or {})
    # Safe navigation through nested dicts
    health = discovery.get("health")
    if not isinstance(health, dict):
        return "N/A"
    appliance = health.get("appliance")
    if not isinstance(appliance, dict):
        return "N/A"
    info = appliance.get("info")
    if not isinstance(info, dict):
        return "N/A"
    return str(info.get("version", "N/A"))


def _extract_cluster_list(bundle_view):
    discovery = dict(bundle_view.get("discovery") or {})
    inventory = dict(discovery.get("inventory") or {})
    clusters = dict(inventory.get("clusters") or {})
    items = list(clusters.get("list") or [])
    return [c for c in items if isinstance(c, dict)]


def _extract_appliance_health(bundle_view):
    discovery = dict(bundle_view.get("discovery") or {})
    health = dict(discovery.get("health") or {})
    appliance = dict(health.get("appliance") or {})
    return {
        "info": dict(appliance.get("info") or {}),
        "health": dict(appliance.get("health") or {}),
        "config": dict(appliance.get("config") or {}),
        "backup": dict(appliance.get("backup") or {}),
    }


def build_vmware_fleet_view(
    aggregated_hosts,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    """Build a template-ready VMware fleet dashboard view model."""
    fleet_rows = []
    fleet_totals = {"clusters": 0, "hosts": 0, "vms": 0}
    fleet_cpu_used = 0
    fleet_cpu_total = 0
    fleet_mem_used = 0
    fleet_mem_total = 0
    fleet_alerts = {"critical": 0, "warning": 0, "total": 0}
    active_alerts = []

    for hostname, bundle in _iter_vmware_hosts(aggregated_hosts):
        bundle_view = _coerce_vmware_bundle(bundle)
        inv = _extract_vmware_inventory_summary(bundle_view)
        util = _extract_vmware_utilization(bundle_view)
        alerts = _count_alerts(bundle_view.get("alerts"))
        vcenter_health = dict(bundle_view.get("vcenter_health") or {})
        status_raw = _status_from_health(vcenter_health.get("health") or bundle_view.get("audit", {}).get("health"))

        fleet_totals["clusters"] += inv["clusters"]
        fleet_totals["hosts"] += inv["hosts"]
        fleet_totals["vms"] += inv["vms"]
        fleet_cpu_used += util["cpu"]["used_mhz"]
        fleet_cpu_total += util["cpu"]["total_mhz"]
        fleet_mem_used += util["memory"]["used_mb"]
        fleet_mem_total += util["memory"]["total_mb"]
        fleet_alerts["critical"] += alerts["critical"]
        fleet_alerts["warning"] += alerts["warning"]

        fleet_rows.append(
            {
                "name": hostname,
                "status": {"raw": status_raw},
                "version": _extract_vmware_version(bundle_view) or "N/A",
                "links": {"node_report_latest": f"./{hostname}/health_report.html"},
                "inventory": inv,
                "utilization": {
                    "cpu_pct": util["cpu"]["pct"],
                    "memory_pct": util["memory"]["pct"],
                    "cpu": util["cpu"],
                    "memory": util["memory"],
                },
                "alerts": alerts,
                "vcenter_health": vcenter_health,
            }
        )
        for alert in safe_list(bundle_view.get("alerts")):
            if not isinstance(alert, dict):
                continue
            counts = _count_alerts([alert])
            if counts.get("critical", 0) > 0:
                sev = "CRITICAL"
            elif counts.get("warning", 0) > 0:
                sev = "WARNING"
            else:
                continue
            active_alerts.append(
                {
                    "host": hostname,
                    "severity": sev,
                    "category": alert.get("category", "vmware"),
                    "message": alert.get("message", ""),
                }
            )

    fleet_alerts["total"] = fleet_alerts["critical"] + fleet_alerts["warning"]
    fleet_cpu_pct = _safe_pct(fleet_cpu_used, fleet_cpu_total)
    fleet_mem_pct = _safe_pct(fleet_mem_used, fleet_mem_total)

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "fleet": {
            "vcenter_count": len(fleet_rows),
            "totals": fleet_totals,
            "utilization": {
                "cpu": {
                    "used_mhz": fleet_cpu_used,
                    "total_mhz": fleet_cpu_total,
                    "pct": fleet_cpu_pct,
                    "severity": _severity_for_pct(fleet_cpu_pct),
                },
                "memory": {
                    "used_mb": fleet_mem_used,
                    "total_mb": fleet_mem_total,
                    "pct": fleet_mem_pct,
                    "severity": _severity_for_pct(fleet_mem_pct),
                },
            },
            "alerts": fleet_alerts,
        },
        "rows": fleet_rows,
        "active_alerts": active_alerts,
    }


def build_vmware_node_view(
    hostname,
    bundle,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    """Build a template-ready per-vCenter report view model."""
    bundle_view = _coerce_vmware_bundle(bundle)
    inv = _extract_vmware_inventory_summary(bundle_view)
    util = _extract_vmware_utilization(bundle_view)
    alerts_list = list(bundle_view.get("alerts") or [])
    alert_counts = _count_alerts(alerts_list)
    vcenter_health = dict(bundle_view.get("vcenter_health") or {})
    status_raw = _status_from_health(vcenter_health.get("health") or bundle_view.get("audit", {}).get("health"))
    appliance = _extract_appliance_health(bundle_view)
    clusters = _extract_cluster_list(bundle_view)

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "node": {
            "name": str(hostname),
            "status": {"raw": status_raw},
            "version": _extract_vmware_version(bundle_view) or "N/A",
            "links": {
                "global_dashboard": "../../site_health_report.html",
                "fleet_dashboard": "../vmware_health_report.html",
            },
            "inventory": inv,
            "utilization": {
                "cpu": util["cpu"],
                "memory": util["memory"],
                "cpu_pct": util["cpu"]["pct"],
                "memory_pct": util["memory"]["pct"],
            },
            "alerts": {
                "counts": alert_counts,
                "items": alerts_list,
            },
            "vcenter_health": vcenter_health,
            "appliance": appliance,
            "clusters": clusters,
        },
    }
