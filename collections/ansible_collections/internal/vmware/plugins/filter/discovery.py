# internal.vmware/plugins/filter/discovery.py

import json
import re
from pathlib import Path
import importlib.util

try:
    from ansible_collections.internal.core.plugins.module_utils.normalization import (
        merge_section_defaults as _merge_defaults,
        parse_json_command_result,
        result_envelope as discovery_result,
        section_defaults as _section_defaults,
    )
    from ansible_collections.internal.core.plugins.module_utils.date_utils import (
        safe_iso_to_epoch as _safe_iso_utc_to_epoch,
    )
except ImportError:
    # Repo checkout fallback for local lint/py_compile outside the Ansible collection loader.
    _helper_path = (
        Path(__file__).resolve().parents[3]
        / "core"
        / "plugins"
        / "module_utils"
        / "normalization.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "internal_core_normalization_helpers", _helper_path
    )
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    discovery_result = _mod.result_envelope
    _section_defaults = _mod.section_defaults
    _merge_defaults = _mod.merge_section_defaults
    parse_json_command_result = _mod.parse_json_command_result
    _date_helper_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "date_utils.py"
    _date_spec = importlib.util.spec_from_file_location("internal_core_date_utils", _date_helper_path)
    _date_mod = importlib.util.module_from_spec(_date_spec)
    assert _date_spec is not None and _date_spec.loader is not None
    _date_spec.loader.exec_module(_date_mod)
    _safe_iso_utc_to_epoch = _date_mod.safe_iso_to_epoch

_BACKUP_TS_RE = re.compile(r"EndTime=([^,]+)")
_SYSTEM_VM_RE = re.compile(r"^(vCLS-|vsanhealth|vmware-).*")


def normalize_compute_inventory(cluster_results):
    """
    Normalize vmware.vmware.cluster_info loop results into cluster/host structures.

    Args:
        cluster_results: list of per-datacenter module results (register.results)

    Returns:
        dict with:
          - clusters_by_name
          - clusters_list
          - hosts_list
    """
    cluster_results = cluster_results or []

    raw_clusters = {}
    for result in cluster_results:
        clusters = result.get("clusters")
        if isinstance(clusters, dict):
            raw_clusters.update(clusters)

    clusters_by_name = {}
    hosts_list = []

    for name, data in raw_clusters.items():
        data = data or {}
        stats = data.get("resource_summary") or {}

        cpu_cap = max(int(stats.get("cpuCapacityMHz", 0) or 0), 1)
        mem_cap = max(int(stats.get("memCapacityMB", 0) or 0), 1)
        cpu_used = int(stats.get("cpuUsedMHz", 0) or 0)
        mem_used = int(stats.get("memUsedMB", 0) or 0)
        datacenter = data.get("datacenter", "unknown")
        hosts = list(data.get("hosts") or [])

        cluster_data = {
            "name": name,
            "datacenter": datacenter,
            "utilization": {
                "cpu_pct": round((cpu_used / cpu_cap) * 100, 1),
                "mem_pct": round((mem_used / mem_cap) * 100, 1),
                "cpu_total_mhz": cpu_cap,
                "cpu_used_mhz": cpu_used,
                "mem_total_mb": mem_cap,
                "mem_used_mb": mem_used,
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


def normalize_datastores(datastores, low_space_pct=10):
    """
    Normalize datastore objects from community.vmware.vmware_datastore_info.
    Returns a dict with `list` and `summary`.
    """
    datastores = datastores or []
    gb_factor = 1073741824.0
    low_space_pct = float(low_space_pct)
    normalized = []

    for ds in datastores:
        ds = ds or {}
        accessible = bool(ds.get("accessible", False))
        cap_bytes = int(ds.get("capacity", 0) or 0)
        free_bytes = int(ds.get("freeSpace", 0) or 0)
        cap_safe = max(cap_bytes, 1) if accessible else 1
        free_pct = round((float(free_bytes) / cap_safe) * 100.0, 1) if accessible else 0.0

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
                "uncommitted_gb": round(float(ds.get("uncommitted", 0) or 0) / gb_factor, 1),
            }
        )

    summary = {
        "total_count": len(normalized),
        "inaccessible_count": len([d for d in normalized if not d.get("accessible", False)]),
        "low_space_count": len(
            [
                d
                for d in normalized
                if d.get("accessible", False) and float(d.get("free_pct", 0)) <= low_space_pct
            ]
        ),
        "maintenance_count": len(
            [d for d in normalized if d.get("maintenance_mode", "normal") != "normal"]
        ),
    }

    return {"list": normalized, "summary": summary}


def normalize_appliance_backup_result(raw_result, collected_at=""):
    raw_result = raw_result or {}
    schedules = list(raw_result.get("schedules") or [])
    has_schedules = len(schedules) > 0
    active_schedule = next(
        (s for s in schedules if isinstance(s, dict) and bool(s.get("enabled", False))),
        {},
    )
    location = str(active_schedule.get("location", "NOT_SET") or "NOT_SET")
    protocol = (location.split(":")[0].upper() if ":" in location else (location or "NONE")).upper()
    schedule_cfg = dict(active_schedule.get("schedule") or {})
    days = list(schedule_cfg.get("days_of_week") or [])
    recurrence = "Daily" if len(days) == 7 else (", ".join(days) if len(days) > 0 else "Manual/None")

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


def normalize_appliance_health_result(raw_result, backup_result=None, collected_at=""):
    raw_result = raw_result or {}
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
                "uptime_days": round(float(summary.get("uptime", 0) or 0) / 86400.0, 1),
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
                "shell_enabled": bool(dict(access.get("shell") or {}).get("enabled", False)),
                "ntp_servers": list(time_sync.get("servers") or []),
                "ntp_mode": str(time_sync.get("mode", "disabled")).upper(),
                "timezone": time_cfg.get("time_zone", "UTC"),
            },
            "backup": dict(backup_result or {"enabled": False, "status": "NOT_CONFIGURED"}),
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_compute_result(cluster_loop_result, collected_at=""):
    cluster_loop_result = cluster_loop_result or {}
    results = list(cluster_loop_result.get("results") or [])
    errors = []
    for item in results:
        item = item or {}
        if bool(item.get("failed", False)):
            errors.append(
                {
                    "datacenter": item.get("item"),
                    "failed": True,
                    "msg": item.get("msg", "") or "",
                }
            )

    normalized = normalize_compute_inventory(results)
    error_msg = next((e.get("msg", "") for e in errors if e.get("msg", "")), "")
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


def normalize_storage_result(raw_result, collected_at="", low_space_pct=10):
    raw_result = raw_result or {}
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


def analyze_workload_vms(virtual_machines, current_epoch, backup_overdue_days=2):
    """
    Normalize VM inventory and derive ownership/backup compliance fields.
    Returns a dict with `list`, `summary`, and `metrics`.
    """
    virtual_machines = virtual_machines or []
    current_epoch = int(current_epoch or 0)
    backup_overdue_days = int(backup_overdue_days or 2)
    results = []

    for item in virtual_machines:
        item = item or {}
        attrs = item.get("attributes") or {}
        owner = (attrs.get("Owner Email") or attrs.get("owner_email") or "").strip()

        backup_attr = attrs.get("Last Dell PowerProtect Backup", "") or ""
        match = _BACKUP_TS_RE.search(backup_attr) if isinstance(backup_attr, str) else None
        raw_ts = match.group(1).strip() if match else ""
        backup_epoch = _safe_iso_utc_to_epoch(raw_ts)
        ts_parseable = backup_epoch > 0
        days_since = int((current_epoch - backup_epoch) / 86400) if backup_epoch > 0 else 9999

        vm_name = item.get("guest_name") or item.get("config_name") or ""
        is_system_vm = bool(_SYSTEM_VM_RE.match(vm_name))

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
                "memory_mb": item.get("memory_mb", 0),
                "cpu_count": item.get("num_cpu", 0),
                "last_backup": (
                    raw_ts if ts_parseable else ("INVALID_FORMAT" if match else "NEVER")
                ),
                "days_since": days_since,
                "backup_overdue": (days_since > backup_overdue_days) if ts_parseable else True,
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
                if not v.get("is_system_vm", False) and (v.get("owner_email") or "") == ""
            ]
        ),
    }
    metrics = {
        "powered_off_count": len(
            [v for v in results if str(v.get("power_state", "")) == "POWEREDOFF"]
        )
    }

    return {"list": results, "summary": summary, "metrics": metrics}


def normalize_workload_result(raw_result, current_epoch, collected_at="", backup_overdue_days=2):
    raw_result = raw_result or {}
    analyzed = analyze_workload_vms(
        raw_result.get("virtual_machines") or [],
        current_epoch,
        backup_overdue_days=backup_overdue_days,
    )
    return discovery_result(
        {
            "list": analyzed.get("list", []) or [],
            "summary": analyzed.get("summary", {}) or {},
            "metrics": analyzed.get("metrics", {}) or {},
        },
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def normalize_datacenters_result(raw_result, collected_at=""):
    raw_result = raw_result or {}
    raw_list = list(raw_result.get("value") or [])
    dc_names = [str(item.get("name", "")) for item in raw_list if isinstance(item, dict)]
    dc_ids = [item.get("datacenter") for item in raw_list if isinstance(item, dict)]
    payload = {
        "list": dc_names,
        "raw": raw_list,
        "by_name": dict(zip(dc_names, dc_ids)),
        "summary": {
            "total_count": len(raw_list),
            "primary_dc": dc_names[0] if dc_names else "",
        },
    }
    return discovery_result(
        payload,
        failed=bool(raw_result.get("failed", False)),
        error=raw_result.get("msg", "") or "",
        collected_at=collected_at,
    )


def parse_alarm_script_output(command_result):
    parsed = parse_json_command_result(command_result, object_only=True)
    payload = parsed.get("payload")
    stdout = parsed.get("stdout", "")
    stderr = parsed.get("stderr", "")

    if parsed.get("script_valid", False) and isinstance(payload, dict):
        parsed["payload"] = payload
        return parsed

    if parsed.get("script_valid", False):
        error_msg = "Invalid JSON from alarm script"
    else:
        error_msg = (
            stderr
            if len(stderr) > 0
            else (
                "Empty stdout from alarm script"
                if len(stdout) == 0
                else "Non-JSON stdout from alarm script"
            )
        )

    parsed["payload"] = {
        "success": False,
        "error": error_msg,
        "alarms": [],
    }
    return parsed


def normalize_alarm_result(parsed_result, site, collected_at=""):
    parsed_result = parsed_result or {}
    payload = parsed_result.get("payload") or {}
    alarms = list(payload.get("alarms") or [])
    normalized_list = []

    for item in alarms:
        item = item or {}
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

    script_ok = bool(parsed_result.get("script_valid", False)) and bool(payload.get("success", False))
    rc = int(parsed_result.get("rc", 1) or 1)
    if script_ok:
        status = "SUCCESS"
    elif rc != 0:
        status = "SCRIPT_ERROR"
    else:
        status = "COLLECT_ERROR"

    critical_items = [i for i in normalized_list if i.get("severity") == "critical"]
    warning_count = len([i for i in normalized_list if i.get("severity") == "warning"])

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


def snapshot_owner_map(vms_section):
    vms_section = vms_section or {}
    vm_list = list(vms_section.get("list") or [])
    out = {}
    for item in vm_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        out[str(name)] = item.get("owner_email", "")
    return out


def snapshot_no_datacenter_result(collected_at=""):
    return discovery_result(
        {
            "all": [],
            "aged": [],
            "summary": {
                "total_count": 0,
                "aged_count": 0,
                "total_size_gb": 0.0,
                "large_snapshots": [],
                "oldest_days": 0,
                "status": "NO_DATACENTER",
            },
        },
        collected_at=collected_at,
        status="NO_DATACENTER",
    )


def normalize_snapshots_result(
    raw_result,
    all_snaps,
    aged_snaps,
    collected_at="",
    size_warning_gb=100,
):
    raw_result = raw_result or {}
    all_snaps = list(all_snaps or [])
    aged_snaps = list(aged_snaps or [])
    size_warning_gb = float(size_warning_gb or 100)
    total_size_gb = round(
        float(sum(float(item.get("size_gb", 0) or 0) for item in aged_snaps)), 1
    )
    large_snapshots = [
        item for item in aged_snaps if float(item.get("size_gb", 0) or 0) > size_warning_gb
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


def _default_inventory_sections(collected_at=""):
    base = _section_defaults(collected_at)
    return {
        "datacenters": {
            **base,
            "list": [],
            "raw": [],
            "by_name": {},
            "summary": {"total_count": 0, "primary_dc": ""},
        },
        "clusters": {
            **base,
            "list": [],
            "by_name": {},
        },
        "hosts": {
            **base,
            "list": [],
            "count": 0,
        },
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
            "metrics": {"powered_off_count": 0, "powered_off_pct": 0},
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


def _default_health_sections(collected_at=""):
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


def build_discovery_ctx(base_ctx, disc, collected_at=""):
    base_ctx = dict(base_ctx or {})
    disc = dict(disc or {})
    collected_at = str(collected_at or "")

    inventory_defaults = _default_inventory_sections(collected_at)
    health_defaults = _default_health_sections(collected_at)

    datacenters = _merge_defaults(
        inventory_defaults["datacenters"],
        disc.get("datacenters"),
        collected_at,
    )
    clusters = _merge_defaults(inventory_defaults["clusters"], disc.get("clusters"), collected_at)
    hosts = _merge_defaults(inventory_defaults["hosts"], disc.get("hosts"), collected_at)
    datastores = _merge_defaults(
        inventory_defaults["datastores"], disc.get("datastores"), collected_at
    )
    vms = _merge_defaults(inventory_defaults["vms"], disc.get("vms"), collected_at)
    snapshots = _merge_defaults(
        inventory_defaults["snapshots"], disc.get("snapshots"), collected_at
    )
    snapshots_summary = dict(snapshots.get("summary") or {})
    snapshots_summary.setdefault("status", snapshots.get("status", "NOT_RUN"))
    if snapshots.get("error", ""):
        snapshots_summary.setdefault("error", snapshots.get("error", ""))
    snapshots["summary"] = snapshots_summary

    appliance = _merge_defaults(health_defaults["appliance"], disc.get("appliance"), collected_at)
    alarms = _merge_defaults(health_defaults["alarms"], disc.get("alarms"), collected_at)

    dc_failed = datacenters.get("status") == "QUERY_ERROR"
    dc_count = len(datacenters.get("list") or [])
    if dc_failed:
        system_status = "DISCOVERY_ERROR_DATACENTERS"
    elif dc_count == 0:
        system_status = "NO_DATACENTERS_FOUND"
    else:
        system_status = "DISCOVERY_COMPLETE"

    alerts = list(base_ctx.get("alerts") or [])
    if dc_failed:
        alerts.append(
            {
                "severity": "CRITICAL",
                "category": "discovery",
                "message": "Datacenter discovery failed",
                "detail": {
                    "component": "datacenter",
                    "error": datacenters.get("error", ""),
                },
            }
        )

    out = dict(base_ctx)
    system = dict(base_ctx.get("system") or {})
    system["status"] = system_status
    system["updated_at"] = collected_at
    out["system"] = system
    out["health"] = {
        **dict(base_ctx.get("health") or {}),
        "appliance": appliance,
        "alarms": alarms,
    }
    out["inventory"] = {
        **dict(base_ctx.get("inventory") or {}),
        "datacenters": datacenters,
        "clusters": clusters,
        "hosts": hosts,
        "datastores": datastores,
        "vms": vms,
        "snapshots": snapshots,
    }
    out["alerts"] = alerts
    return out


class FilterModule(object):
    def filters(self):
        return {
            "normalize_compute_inventory": normalize_compute_inventory,
            "normalize_datastores": normalize_datastores,
            "normalize_appliance_backup_result": normalize_appliance_backup_result,
            "normalize_appliance_health_result": normalize_appliance_health_result,
            "normalize_compute_result": normalize_compute_result,
            "normalize_storage_result": normalize_storage_result,
            "analyze_workload_vms": analyze_workload_vms,
            "normalize_workload_result": normalize_workload_result,
            "discovery_result": discovery_result,
            "normalize_datacenters_result": normalize_datacenters_result,
            "parse_alarm_script_output": parse_alarm_script_output,
            "normalize_alarm_result": normalize_alarm_result,
            "snapshot_owner_map": snapshot_owner_map,
            "snapshot_no_datacenter_result": snapshot_no_datacenter_result,
            "normalize_snapshots_result": normalize_snapshots_result,
            "build_discovery_ctx": build_discovery_ctx,
        }
