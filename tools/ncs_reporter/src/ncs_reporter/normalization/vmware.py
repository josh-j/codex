"""VMware-specific normalization logic for raw discovery/audit data."""

import logging
import re
from typing import Any
from urllib.parse import unquote

from ncs_reporter.models.base import MetadataModel, SummaryModel, AlertModel
from ncs_reporter.models.vmware import VMwareAuditModel, VMwareDiscoveryContext
from ncs_reporter.normalization.common import filter_by_age
from ncs_reporter.alerts import (
    append_alerts,
    compute_audit_rollups,
)
from ncs_reporter.date_utils import safe_iso_to_epoch
from ncs_reporter.normalization.core import (
    result_envelope as discovery_result,
)
from ncs_reporter.normalization.core import (
    section_defaults as _section_defaults,
)
from ncs_reporter.primitives import (
    as_list,
    build_alert,
    build_count_alert,
    build_threshold_alert,
    safe_list,
    to_float,
    to_int,
)

logger = logging.getLogger(__name__)

_BACKUP_TS_RE = re.compile(r"EndTime=([^,]+)")
_SYSTEM_VM_RE = re.compile(r"^(vCLS-|vsanhealth|vmware-).*")


def audit_health_alerts(discovery_ctx: dict[str, Any]) -> list[dict[str, Any]]:
    discovery_ctx = dict(discovery_ctx or {})
    health_sect = dict(discovery_ctx.get("health") or {})
    
    # Unwrap appliance envelope if present
    app_env = dict(health_sect.get("appliance") or {})
    app = dict(app_env.get("data") or app_env)
    
    h = dict(app.get("health") or {})
    backup = dict(app.get("backup") or {})
    config = dict(app.get("config") or {})
    overall = str(h.get("overall", "gray")).lower()
    
    # Extract datacenter count for inventory check (Unwrap envelope)
    inventory = discovery_ctx.get("inventory", {})
    dc_env = dict(inventory.get("datacenters") or {})
    datacenters = dict(dc_env.get("data") or dc_env)
    dc_count = to_int(datacenters.get("summary", {}).get("total_count", 0))

    alerts = []
    if dc_count == 0:
        alerts.append(
            build_alert(
                "CRITICAL",
                "infrastructure",
                "Inventory Gap: No Datacenters detected in vCenter",
                {"datacenter_count": dc_count, "status": "Empty Inventory"},
            )
        )

    if overall == "red":
        sev = "CRITICAL"
        msg = f"VCSA Component Failure: Overall health is {overall.upper()}"
    elif overall == "yellow":
        sev = "WARNING"
        msg = f"VCSA Degraded: Overall health is {overall.upper()}"
    elif overall == "gray":
        sev = "WARNING"
        msg = "VCSA Health Unknown: Overall health is GRAY (check permissions / API availability)"
    else:
        sev = None
        msg = None

    if sev:
        detail = {
            "overall": overall.upper(),
            "database": str(h.get("database", "gray")).upper(),
            "storage": str(h.get("storage", "gray")).upper(),
            "swap": str(h.get("swap", "gray")).upper(),
            "memory": str(h.get("memory", "gray")).upper(),
            "cpu": str(h.get("cpu", "gray")).upper(),
        }
        if overall == "gray":
            detail["note"] = (
                "GRAY often indicates unavailable/unknown health from VAMI. "
                "Validate credentials/permissions and VCSA health endpoints."
            )
            category = "data_quality"
        else:
            category = "appliance_health"
        alerts.append(build_alert(sev, category, msg or "", detail))

    if bool(config.get("ssh_enabled", False)):
        alerts.append(
            build_alert(
                "WARNING",
                "security",
                "Hardening Violation: SSH is ENABLED on VCSA",
                {
                    "current_state": "Open",
                    "remediation": "Disable SSH via VAMI or CLI unless a maintenance window is active.",
                },
            )
        )

    if not bool(backup.get("enabled", False)):
        alerts.append(
            build_alert(
                "CRITICAL",
                "data_protection",
                "DR Risk: File-Based Backup is DISABLED",
                {
                    "enabled": bool(backup.get("enabled", False)),
                    "configured": bool(backup.get("configured", False)),
                    "status": backup.get("status", "NOT_CONFIGURED"),
                    "location": backup.get("location", "NONE"),
                    "protocol": backup.get("protocol", "NONE"),
                    "recurrence": backup.get("recurrence", "Manual/None"),
                },
            )
        )

    return alerts


def audit_alarm_alerts(discovery_ctx: dict[str, Any], max_items: int = 25) -> list[dict[str, Any]]:
    discovery_ctx = dict(discovery_ctx or {})
    health_sect = dict(discovery_ctx.get("health") or {})
    
    # Unwrap alarms envelope if present
    alarms_env = dict(health_sect.get("alarms") or {})
    alarms = dict(alarms_env.get("data") or alarms_env)
    
    alarm_list = as_list(alarms.get("list"))
    metrics = dict(alarms.get("metrics") or {})
    status = str(alarms.get("status", "UNKNOWN"))
    crit_count = to_int(metrics.get("critical_count", 0))
    warn_count = to_int(metrics.get("warning_count", 0))
    total = to_int(metrics.get("total", len(alarm_list)))
    max_items = max(to_int(max_items, 25), 0)

    critical_items = [
        a
        for a in alarm_list
        if str((a or {}).get("severity", "")).lower() == "critical"
    ]
    warning_items = [
        a for a in alarm_list if str((a or {}).get("severity", "")).lower() == "warning"
    ]

    alerts = []
    if status != "SUCCESS":
        alerts.append(
            build_alert(
                "WARNING",
                "vcenter_alarms",
                f"Alarm collection status: {status}",
                {
                    "status": status,
                    "total": total,
                    "critical_count": crit_count,
                    "warning_count": warn_count,
                },
            )
        )
    if crit_count > 0:
        alerts.append(
            build_alert(
                "CRITICAL",
                "vcenter_alarms",
                f"Active Critical Alarms: {crit_count} detected",
                {"critical_count": crit_count, "warning_count": warn_count},
                affected_items=critical_items[:max_items],
            )
        )
    elif warn_count > 0:
        alerts.append(
            build_alert(
                "WARNING",
                "vcenter_alarms",
                f"Active Warning Alarms: {warn_count} detected",
                {"warning_count": warn_count},
                affected_items=warning_items[:max_items],
            )
        )
    return alerts


def audit_storage_object_alerts(datastores: list[Any], crit_pct: float = 10.0, warn_pct: float = 15.0) -> list[dict[str, Any]]:
    ds = as_list(datastores)
    crit_pct = to_float(crit_pct, 10)
    warn_pct = to_float(warn_pct, 15)
    alerts = []
    for item in ds:
        item = item or {}
        name = item.get("name", "unknown")
        free_pct = to_float(item.get("free_pct", 100), 100)
        if not bool(item.get("accessible", True)):
            alerts.append(
                build_alert(
                    "CRITICAL",
                    "storage_connectivity",
                    f"Datastore {name} is INACCESSIBLE",
                    {
                        "datastore": name,
                        "type": item.get("type", "unknown"),
                        "accessible": bool(item.get("accessible", False)),
                        "path_status": "Down",
                    },
                )
            )
        threshold_alert = build_threshold_alert(
            free_pct,
            crit_pct,
            warn_pct,
            "storage_capacity",
            f"Datastore {name} is low ({free_pct}% free)",
            detail={
                "datastore": name,
                "free_pct": free_pct,
                "free_gb": item.get("free_gb", 0),
                "capacity_gb": item.get("capacity_gb", 0),
            },
            direction="le",
            value_key="free_pct",
        )
        if threshold_alert is not None:
            if threshold_alert["severity"] == "CRITICAL":
                threshold_alert["message"] = (
                    f"Datastore {name} is critically low ({free_pct}% free)"
                )
            alerts.append(threshold_alert)
    return alerts


def audit_tools_alerts(vms: list[Any], max_items: int = 50) -> list[dict[str, Any]]:
    vms = as_list(vms)
    max_items = max(to_int(max_items, 50), 0)
    healthy_statuses = {"toolsok", "toolsold"}
    unhealthy = []
    for vm in vms:
        vm = vm or {}
        if str(vm.get("power_state", "")).lower() != "poweredon":
            continue
        tools_status = vm.get("tools_status")
        if tools_status is None or str(tools_status).lower() not in healthy_statuses:
            unhealthy.append(vm)
    if not unhealthy:
        return []
    return [
        build_alert(
            "WARNING",
            "workload_compliance",
            f"Compliance Gap: {len(unhealthy)} powered-on VM(s) have unhealthy VMware Tools",
            {"total_impacted": len(unhealthy)},
            affected_items=[
                str((vm or {}).get("name")) for vm in unhealthy if (vm or {}).get("name")
            ][:max_items],
            recommendation="Verify Tools installation to ensure backup quiescing and driver performance.",
        )
    ]


def normalize_compute_inventory(cluster_results: list[Any]) -> dict[str, Any]:
    """
    Normalize vmware.vmware.cluster_info loop results into cluster/host structures.
    """
    cluster_results = safe_list(cluster_results)

    raw_clusters = {}
    for result in cluster_results:
        if not isinstance(result, dict):
            continue
        clusters = result.get("clusters")
        if isinstance(clusters, dict):
            raw_clusters.update(clusters)

    clusters_by_name = {}
    hosts_list = []

    for name, data in raw_clusters.items():
        data = dict(data or {})
        stats = dict(data.get("resource_summary") or {})

        cpu_cap = max(to_int(stats.get("cpuCapacityMHz", 0)), 1)
        memory_cap = max(to_int(stats.get("memCapacityMB", 0)), 1)
        cpu_used = to_int(stats.get("cpuUsedMHz", 0))
        memory_used = to_int(stats.get("memUsedMB", 0))
        datacenter = data.get("datacenter", "unknown")
        hosts = safe_list(data.get("hosts"))

        cluster_data = {
            "name": str(name),
            "datacenter": datacenter,
            "utilization": {
                "cpu_pct": round((cpu_used / cpu_cap) * 100, 1),
                "memory_pct": round((memory_used / memory_cap) * 100, 1),
                "cpu_total_mhz": cpu_cap,
                "cpu_used_mhz": cpu_used,
                "memory_total_mb": memory_cap,
                "memory_used_mb": memory_used,
            },
            "compliance": {
                "ha_enabled": bool(data.get("ha_enabled", False)),
                "drs_enabled": bool(data.get("drs_enabled", False)),
                "vsan_enabled": bool(data.get("vsan_enabled", False)),
            },
            "hosts": hosts,
        }
        clusters_by_name[name] = cluster_data

        for host in hosts:
            if isinstance(host, dict):
                hosts_list.append({**host, "cluster": name, "datacenter": datacenter})
            else:
                hosts_list.append(
                    {"name": str(host), "cluster": name, "datacenter": datacenter}
                )

    return {
        "clusters_by_name": clusters_by_name,
        "clusters_list": list(clusters_by_name.values()),
        "hosts_list": hosts_list,
    }


def normalize_datastores(datastores: list[Any], low_space_pct: float = 10.0) -> dict[str, Any]:
    """
    Normalize datastore objects from community.vmware.vmware_datastore_info.
    Returns a dict with `list` and `summary`.
    """
    datastores = safe_list(datastores)
    gb_factor = 1073741824.0
    low_space_pct = float(low_space_pct)
    normalized = []

    for ds in datastores:
        if not isinstance(ds, dict):
            continue
        accessible = bool(ds.get("accessible", False))
        cap_bytes = to_int(ds.get("capacity", 0))
        free_bytes = to_int(ds.get("freeSpace", 0))
        cap_safe = max(cap_bytes, 1) if accessible else 1
        free_pct = (
            round((float(free_bytes) / cap_safe) * 100.0, 1) if accessible else 0.0
        )

        normalized.append(
            {
                "name": ds.get("name", "UNKNOWN_DS"),
                "type": ds.get("type", "N/A"),
                "capacity_gb": round(float(cap_bytes) / gb_factor, 1),
                "free_gb": round(float(free_bytes) / gb_factor, 1),
                "used_gb": round(float(cap_bytes - free_bytes) / gb_factor, 1),
                "free_pct": free_pct,
                "accessible": accessible,
                "maintenance_mode": str(ds.get("maintenanceMode", "normal")).lower(),
                "uncommitted_gb": round(
                    float(ds.get("uncommitted", 0) or 0) / gb_factor, 1
                ),
            }
        )

    summary = {
        "total_count": len(normalized),
        "inaccessible_count": len(
            [d for d in normalized if not d.get("accessible", False)]
        ),
        "low_space_count": len(
            [
                d
                for d in normalized
                if d.get("accessible", False)
                and float(d.get("free_pct", 0)) <= low_space_pct
            ]
        ),
        "maintenance_count": len(
            [d for d in normalized if d.get("maintenance_mode", "normal") != "normal"]
        ),
    }

    return {"list": normalized, "summary": summary}


def normalize_appliance_backup_result(raw_result: dict[str, Any], collected_at: str = "") -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    schedules = safe_list(raw_result.get("schedules"))
    has_schedules = len(schedules) > 0
    active_schedule = next(
        (s for s in schedules if isinstance(s, dict) and bool(s.get("enabled", False))),
        {},
    )
    location = str(active_schedule.get("location", "NOT_SET") or "NOT_SET")
    protocol = (
        location.split(":")[0].upper() if ":" in location else (location or "NONE")
    ).upper()
    schedule_cfg = dict(active_schedule.get("schedule") or {})
    days = safe_list(schedule_cfg.get("days_of_week"))
    recurrence = (
        "Daily"
        if len(days) == 7
        else (", ".join(days) if len(days) > 0 else "Manual/None")
    )

    return discovery_result(
        {
            "configured": has_schedules,
            "enabled": bool(active_schedule.get("enabled", False)),
            "location": location,
            "protocol": protocol if protocol else "NONE",
            "recurrence": recurrence,
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_appliance_health_result(raw_result: dict[str, Any], backup_result: dict[str, Any] | None = None, collected_at: str = "") -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    app = dict(raw_result.get("appliance") or {})
    summary = dict(app.get("summary") or {})
    health = dict(summary.get("health") or {})
    access = dict(app.get("access") or {})
    time_cfg = dict(app.get("time") or {})
    time_sync = dict(time_cfg.get("time_sync") or {})

    return discovery_result(
        {
            "info": {
                "product": summary.get("product", "vCenter Server"),
                "version": summary.get("version", "unknown"),
                "build": summary.get("build_number", "unknown"),
                "uptime_days": int(
                    round(float(summary.get("uptime", 0) or 0) / 86400.0, 1)
                ),
            },
            "health": {
                "overall": str(health.get("overall", "gray")).lower(),
                "cpu": str(health.get("cpu", "gray")).lower(),
                "memory": str(health.get("memory", "gray")).lower(),
                "database": str(health.get("database", "gray")).lower(),
                "storage": str(health.get("storage", "gray")).lower(),
                "swap": str(health.get("swap", "gray")).lower(),
            },
            "config": {
                "ssh_enabled": bool(access.get("ssh", False)),
                "shell_enabled": bool(
                    dict(access.get("shell") or {}).get("enabled", False)
                ),
                "ntp_servers": safe_list(time_sync.get("servers")),
                "ntp_mode": str(time_sync.get("mode", "disabled")).upper(),
                "timezone": time_cfg.get("time_zone", "UTC"),
            },
            "backup": dict(
                backup_result or {"enabled": False, "status": "NOT_CONFIGURED"}
            ),
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_compute_result(cluster_loop_result: dict[str, Any], collected_at: str = "") -> dict[str, Any]:
    cluster_loop_result = dict(cluster_loop_result or {})
    results = safe_list(cluster_loop_result.get("results"))
    errors = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if bool(item.get("failed", False)):
            errors.append(
                {
                    "datacenter": item.get("item"),
                    "failed": True,
                    "msg": item.get("msg", "") or "",
                }
            )

    normalized = normalize_compute_inventory(results)
    error_msg: str = str(next((e.get("msg", "") for e in errors if e.get("msg", "")), ""))
    failed = len(errors) > 0

    return {
        "errors": errors,
        "clusters": discovery_result(
            {
                "by_name": normalized.get("clusters_by_name", {}) or {},
                "list": list(normalized.get("clusters_list") or []),
            },
            failed=failed,
            error=error_msg,
            collected_at=collected_at,
        ),
        "hosts": discovery_result(
            {
                "list": list(normalized.get("hosts_list") or []),
                "count": len(normalized.get("hosts_list") or []),
            },
            failed=failed,
            error=error_msg,
            collected_at=collected_at,
        ),
    }


def normalize_storage_result(raw_result: dict[str, Any], collected_at: str = "", low_space_pct: float = 10.0) -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    normalized = normalize_datastores(
        raw_result.get("datastores") or [],
        low_space_pct=low_space_pct,
    )
    return discovery_result(
        {
            "list": normalized.get("list", []) or [],
            "summary": normalized.get("summary", {}) or {},
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def analyze_workload_vms(virtual_machines: list[Any], current_epoch: int, backup_overdue_days: int = 2) -> dict[str, Any]:
    """
    Normalize VM inventory and derive ownership/backup compliance fields.
    Returns a dict with `list`, `summary`, and `metrics`.
    """
    virtual_machines = safe_list(virtual_machines)
    current_epoch = to_int(current_epoch)
    backup_overdue_days = to_int(backup_overdue_days, 2)
    results = []

    for item in virtual_machines:
        if not isinstance(item, dict):
            continue
        attrs = dict(item.get("attributes") or {})
        owner = str(attrs.get("Owner Email") or attrs.get("owner_email") or "").strip()

        backup_attr = attrs.get("Last Dell PowerProtect Backup", "") or ""
        match = (
            _BACKUP_TS_RE.search(backup_attr) if isinstance(backup_attr, str) else None
        )
        raw_ts = match.group(1).strip() if match else ""
        backup_epoch = safe_iso_to_epoch(raw_ts)
        ts_parseable = backup_epoch > 0

        days_since = 9999
        if ts_parseable and current_epoch > 0:
            days_since = max(int((current_epoch - backup_epoch) / 86400), 0)

        vm_name = str(item.get("guest_name") or item.get("config_name") or "unknown")
        is_system_vm = bool(_SYSTEM_VM_RE.match(vm_name)) or bool(
            item.get("is_template", False)
        )

        results.append(
            {
                "name": vm_name,
                "uuid": item.get("uuid"),
                "is_system_vm": is_system_vm,
                "power_state": str(item.get("power_state", "")).upper(),
                "cluster": item.get("cluster", "standalone"),
                "owner_email": owner,
                "tools_status": item.get("tools_status", "toolsNotInstalled"),
                "tools_version": item.get("tools_version", "unknown"),
                "guest_os": item.get("guest_id", "unknown"),
                "memory_mb": to_int(item.get("memory_mb", 0)),
                "cpu_count": to_int(item.get("num_cpu", 0)),
                "last_backup": (
                    raw_ts if ts_parseable else ("INVALID_FORMAT" if match else "NEVER")
                ),
                "days_since": days_since,
                "backup_overdue": (days_since > backup_overdue_days)
                if ts_parseable
                else True,
                "has_backup": ts_parseable,
            }
        )

    summary = {
        "total_vms": len(results),
        "overdue_backups": len([v for v in results if v.get("backup_overdue") is True]),
        "unprotected": len([v for v in results if v.get("has_backup") is False]),
        "missing_owners": len(
            [
                v
                for v in results
                if not v.get("is_system_vm", False)
                and (v.get("owner_email") or "") == ""
            ]
        ),
    }

    powered_off_count = len(
        [v for v in results if str(v.get("power_state", "")) == "POWEREDOFF"]
    )
    total = max(len(results), 0)

    powered_off_pct = 0.0
    if total > 0:
        powered_off_pct = round((float(powered_off_count) / float(total)) * 100.0, 1)

    metrics = {
        "powered_off_count": powered_off_count,
        "powered_off_pct": float(powered_off_pct),
    }

    return {"list": results, "summary": summary, "metrics": metrics}


def normalize_workload_result(
    raw_result: dict[str, Any], current_epoch: int, collected_at: str = "", backup_overdue_days: int = 2
) -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    analyzed = analyze_workload_vms(
        raw_result.get("virtual_machines") or [],
        current_epoch,
        backup_overdue_days=backup_overdue_days,
    )

    metrics = dict(analyzed.get("metrics") or {})
    # Defensive: if powered_off_pct is missing for any reason, derive it.
    if "powered_off_pct" not in metrics:
        lst = safe_list(analyzed.get("list"))
        po_count = to_int(metrics.get("powered_off_count", 0))
        total = len(lst)
        metrics["powered_off_pct"] = float(
            0.0 if total == 0 else round((po_count / max(total, 1)) * 100.0, 1)
        )

    return discovery_result(
        {
            "list": analyzed.get("list", []) or [],
            "summary": analyzed.get("summary", {}) or {},
            "metrics": metrics,
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_datacenters_result(raw_result: dict[str, Any], collected_at: str = "") -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    raw_list = safe_list(raw_result.get("value"))
    dc_names = [
        str(item.get("name", "")) for item in raw_list if isinstance(item, dict)
    ]
    dc_ids = [item.get("datacenter") for item in raw_list if isinstance(item, dict)]
    payload = {
        "list": dc_names,
        "raw": raw_list,
        "by_name": dict(zip(dc_names, dc_ids, strict=False)),
        "summary": {
            "total_count": len(dc_names),
            "primary_dc": dc_names[0] if dc_names else "",
        },
    }
    return discovery_result(
        payload,
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_alarm_result(parsed_result: dict[str, Any], site: str, collected_at: str = "") -> dict[str, Any]:
    parsed_result = dict(parsed_result or {})
    # Handle both legacy script payload and native module result
    payload = dict(parsed_result.get("payload") or parsed_result)
    alarms = safe_list(payload.get("alarms"))
    normalized_list = []

    for item in alarms:
        if not isinstance(item, dict):
            continue
        normalized_list.append(
            {
                "site": site,
                "alarm_name": item.get("alarm_name", "Unknown Alarm"),
                "entity": item.get("entity", "Unknown Entity"),
                "severity": str(item.get("severity", "info")).lower(),
                "status": item.get("status", "gray"),
                "time": item.get("time", collected_at),
                "description": item.get("description", ""),
            }
        )

    # script_valid is for legacy, failed is for native
    script_ok = (
        bool(parsed_result.get("script_valid", False))
        and bool(payload.get("success", False))
    ) or (not bool(parsed_result.get("failed", False)) and "alarms" in parsed_result)
    rc = to_int(
        parsed_result.get("rc", 0) if "rc" in parsed_result else (0 if script_ok else 1)
    )

    critical_items = [i for i in normalized_list if i.get("severity") == "critical"]
    warning_count = len([i for i in normalized_list if i.get("severity") == "warning"])

    if script_ok:
        status = "CRITICAL" if critical_items else "SUCCESS"
    elif rc != 0:
        status = "SCRIPT_ERROR"
    else:
        status = "COLLECT_ERROR"

    return discovery_result(
        {
            "list": normalized_list,
            "metrics": {
                "total": len(normalized_list),
                "critical_count": len(critical_items),
                "warning_count": warning_count,
            },
            "critical_items": critical_items,
        },
        error=payload.get("error", "") or "",
        collected_at=collected_at,
        status=status,
    )


def enrich_snapshots(snapshots: list[Any], owner_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """
    Enriches age-filtered snapshot dicts with vmware-specific fields.
    """
    owner_map = dict(owner_map or {})
    results = []

    for snap in safe_list(snapshots):
        if not isinstance(snap, dict):
            continue
        vm_name = snap.get("vm_name", "unknown")
        results.append(
            {
                **snap,
                "vm_name": vm_name,
                "snapshot_name": unquote(snap.get("name", "unnamed")),
                "size_gb": to_float(snap.get("size_gb", 0)),
                "owner_email": owner_map.get(vm_name, ""),
            }
        )

    return results


def normalize_snapshots_result(
    raw_result: dict[str, Any],
    all_snaps: list[Any],
    aged_snaps: list[Any],
    collected_at: str = "",
    size_warning_gb: float = 100.0,
) -> dict[str, Any]:
    raw_result = dict(raw_result or {})
    all_snaps = safe_list(all_snaps)
    aged_snaps = safe_list(aged_snaps)
    size_warning_gb = float(size_warning_gb or 100)
    total_size_gb = round(
        float(sum(float(item.get("size_gb", 0) or 0) for item in aged_snaps)), 1
    )
    large_snapshots = [
        item
        for item in aged_snaps
        if float(item.get("size_gb", 0) or 0) > size_warning_gb
    ]
    oldest_days = 0
    if aged_snaps:
        oldest_days = int(max(int(item.get("days_old", 0) or 0) for item in aged_snaps))

    failed = bool(raw_result.get("failed", False))
    status = "QUERY_ERROR" if failed else "SUCCESS"
    error = raw_result.get("msg", "") or ""

    return discovery_result(
        {
            "all": all_snaps,
            "aged": aged_snaps,
            "summary": {
                "total_count": len(all_snaps),
                "aged_count": len(aged_snaps),
                "total_size_gb": total_size_gb,
                "large_snapshots": large_snapshots,
                "oldest_days": oldest_days,
                "status": status,
                "error": error,
            },
        },
        failed=failed,
        error=error,
        collected_at=collected_at,
    )


def _default_inventory_sections(collected_at: str = "") -> dict[str, Any]:
    base = _section_defaults(collected_at)
    return {
        "datacenters": {
            **base,
            "list": [],
            "raw": [],
            "by_name": {},
            "summary": {"total_count": 0, "primary_dc": ""},
        },
        "clusters": {**base, "list": [], "by_name": {}},
        "hosts": {**base, "list": [], "count": 0},
        "datastores": {
            **base,
            "list": [],
            "summary": {
                "total_count": 0,
                "inaccessible_count": 0,
                "low_space_count": 0,
                "maintenance_count": 0,
            },
        },
        "vms": {
            **base,
            "list": [],
            "summary": {
                "total_vms": 0,
                "overdue_backups": 0,
                "unprotected": 0,
                "missing_owners": 0,
            },
            "metrics": {"powered_off_count": 0, "powered_off_pct": 0.0},
        },
        "snapshots": {
            **base,
            "all": [],
            "aged": [],
            "summary": {
                "total_count": 0,
                "aged_count": 0,
                "total_size_gb": 0.0,
                "large_snapshots": [],
                "oldest_days": 0,
                "status": "NOT_RUN",
            },
        },
    }


def _default_health_sections(collected_at: str = "") -> dict[str, Any]:
    base = _section_defaults(collected_at)
    return {
        "appliance": {
            **base,
            "info": {"version": "unknown", "build": "unknown", "uptime_days": 0},
            "health": {"overall": "gray", "database": "gray", "storage": "gray"},
            "config": {"ssh_enabled": False, "ntp_mode": "unknown"},
            "backup": {"enabled": False, "configured": False, "status": "UNKNOWN"},
        },
        "alarms": {
            **base,
            "list": [],
            "metrics": {"total": 0, "critical_count": 0, "warning_count": 0},
            "critical_items": [],
        },
    }


def audit_snapshot_alerts(discovery_ctx: dict[str, Any] | None, age_warning_days: int = 7, size_warning_gb: int = 100, max_items: int = 25) -> list[dict[str, Any]]:
    discovery_ctx = dict(discovery_ctx or {})
    inventory = dict(discovery_ctx.get("inventory") or {})
    
    # Unwrap snapshots envelope
    snaps_env = dict(inventory.get("snapshots") or {})
    snapshots = dict(snaps_env.get("data") or snaps_env)
    
    summary = dict(snapshots.get("summary") or {})
    aged_count = to_int(summary.get("aged_count", 0))
    total_size_gb = to_float(summary.get("total_size_gb", 0.0))
    oldest_days = to_int(summary.get("oldest_days", 0))
    large = as_list(summary.get("large_snapshots"))
    max_items = max(to_int(max_items, 25), 0)

    alerts = []
    if aged_count > 0:
        alerts.append(
            build_count_alert(
                aged_count,
                "WARNING",
                "snapshots",
                f"Capacity Risk: {aged_count} snapshot(s) older than {int(age_warning_days)} days",
                detail={"total_gb": total_size_gb, "oldest_days": oldest_days},
                count_key="aged_count",
            )
        )
    if large:
        alerts.append(
            build_count_alert(
                len(large),
                "WARNING",
                "snapshots",
                f"{len(large)} VM(s) have oversized snapshots (>{to_float(size_warning_gb, 100):g}GB)",
                affected_items=large[:max_items],
                count_key="large_snapshot_count",
            )
        )
    return [a for a in alerts if a is not None]


def normalize_vmware(raw_bundle: dict[str, Any], config: dict[str, Any] | None = None) -> VMwareAuditModel:
    """
    Main entry point for normalizing a VMware bundle (discovery + audit results).
    """
    config = dict(config or {})
    logger.debug("normalize_vmware: raw_bundle keys=%s", list(raw_bundle.keys()))

    # 1. Normalize Discovery
    # Assume raw_bundle contains keys like 'raw_discovery' or similar if aggregated
    # Or it might be the flat data if it's a single file.
    discovery_raw = raw_bundle.get("raw_discovery") or raw_bundle.get("discovery") or raw_bundle
    
    # If it's the new 'raw' format from Ansible:
    if isinstance(discovery_raw, dict) and "data" in discovery_raw:
        metadata_raw = discovery_raw.get("metadata", {})
        collected_at = metadata_raw.get("timestamp", "")
        payload = discovery_raw.get("data", {})
    else:
        collected_at = ""
        payload = discovery_raw

    # Perform discovery normalization
    datacenters = normalize_datacenters_result(payload.get("datacenters_info", {}), collected_at)
    clusters_hosts = normalize_compute_result(payload.get("clusters_info", {}), collected_at)
    datastores = normalize_storage_result(
        payload.get("datastores_info", {}), 
        collected_at, 
        low_space_pct=config.get("vmware_datastore_free_warning_pct", 15.0)
    )
    vms = normalize_workload_result(
        payload.get("vms_info", {}), 
        safe_iso_to_epoch(collected_at), 
        collected_at
    )
    
    backup = normalize_appliance_backup_result(payload.get("appliance_backup_info", {}), collected_at)
    appliance = normalize_appliance_health_result(payload.get("appliance_health_info", {}), backup, collected_at)
    alarms = normalize_alarm_result(payload.get("alarms_info", {}), "vcenter", collected_at)

    # Snapshot normalization
    raw_snapshots = payload.get("snapshots_info", {})
    all_snapshots = raw_snapshots.get("snapshots", []) if isinstance(raw_snapshots, dict) else []
    aged_snapshots = filter_by_age(
        all_snapshots, 
        safe_iso_to_epoch(collected_at), 
        config.get("vmware_snapshot_age_warning_days", 7)
    )
    snapshots = normalize_snapshots_result(
        raw_snapshots if isinstance(raw_snapshots, dict) else {},
        all_snapshots,
        aged_snapshots,
        collected_at,
        size_warning_gb=config.get("vmware_snapshot_size_warning_gb", 100.0)
    )

    # Compute utilization rollup
    clusters_list = clusters_hosts["clusters"].get("list", [])
    total_cpu_mhz = sum(c.get("utilization", {}).get("cpu_total_mhz", 0) for c in clusters_list)
    used_cpu_mhz = sum(c.get("utilization", {}).get("cpu_used_mhz", 0) for c in clusters_list)
    total_mem_mb = sum(c.get("utilization", {}).get("memory_total_mb", 0) for c in clusters_list)
    used_mem_mb = sum(c.get("utilization", {}).get("memory_used_mb", 0) for c in clusters_list)
    
    vcenter_util = {
        "cpu_total_mhz": total_cpu_mhz,
        "cpu_used_mhz": used_cpu_mhz,
        "cpu_pct": round((used_cpu_mhz / max(total_cpu_mhz, 1)) * 100, 1),
        "memory_total_mb": total_mem_mb,
        "memory_used_mb": used_mem_mb,
        "memory_pct": round((used_mem_mb / max(total_mem_mb, 1)) * 100, 1),
    }

    discovery_ctx_dict = {
        "audit_type": "discovery",
        "system": {
            "status": "DISCOVERY_COMPLETE",
            "updated_at": collected_at,
            "utilization": vcenter_util,
        },
        "health": {
            "appliance": appliance,
            "alarms": alarms,
        },
        "inventory": {
            "datacenters": datacenters,
            "clusters": clusters_hosts["clusters"],
            "hosts": clusters_hosts["hosts"],
            "datastores": datastores,
            "vms": vms,
            "snapshots": snapshots,
        },
        "summary": {
            "clusters": to_int(clusters_hosts["clusters"].get("data", {}).get("list_count") or len(clusters_hosts["clusters"].get("by_name", {}))),
            "hosts": to_int(clusters_hosts["hosts"].get("data", {}).get("count", 0)),
            "vms": to_int(vms.get("summary", {}).get("total_vms", 0)),
            "datastores": to_int(datastores.get("summary", {}).get("total_count", 0)),
        }
    }

    # 2. Perform Audit (Alert Generation)
    alerts: list[dict[str, Any]] = []
    alerts = append_alerts(alerts, audit_health_alerts(discovery_ctx_dict))
    alerts = append_alerts(alerts, audit_alarm_alerts(discovery_ctx_dict))
    alerts = append_alerts(alerts, audit_storage_object_alerts(
        datastores.get("list", []),
        crit_pct=config.get("vmware_datastore_free_critical_pct", 10.0),
        warn_pct=config.get("vmware_datastore_free_warning_pct", 15.0)
    ))
    alerts = append_alerts(alerts, audit_tools_alerts(vms.get("list", [])))
    alerts = append_alerts(alerts, audit_snapshot_alerts(
        discovery_ctx_dict,
        age_warning_days=config.get("vmware_snapshot_age_warning_days", 7),
        size_warning_gb=config.get("vmware_snapshot_size_warning_gb", 100.0)
    ))

    # Compute rollups
    rollups = compute_audit_rollups(alerts)
    
    return VMwareAuditModel(
        metadata=MetadataModel(
            audit_type="vmware_vcenter",
            timestamp=collected_at,
        ),
        health=rollups["health"],
        summary=SummaryModel.model_validate(rollups["summary"]),
        alerts=[AlertModel.model_validate(a) for a in alerts],
        discovery=VMwareDiscoveryContext.model_validate(discovery_ctx_dict),
        vmware_vcenter={
            "health": rollups["health"],
            "summary": rollups["summary"],
            "alerts": alerts,
            "data": {
                "utilization": vcenter_util,
            }
        }
    )


