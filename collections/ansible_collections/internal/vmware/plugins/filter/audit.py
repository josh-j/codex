import copy
import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        as_list as _as_list,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        build_alert as _alert,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        build_count_alert as _build_count_alert,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        build_threshold_alert as _build_threshold_alert,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        canonical_severity,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        to_float as _to_float,
    )
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        to_int as _to_int,
    )
except ImportError:
    # Repo checkout fallback for local lint/py_compile outside the Ansible collection loader.
    _helper_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location("internal_core_reporting_primitives", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _as_list = _mod.as_list
    _alert = _mod.build_alert
    _build_count_alert = _mod.build_count_alert
    _build_threshold_alert = _mod.build_threshold_alert
    _to_float = _mod.to_float
    _to_int = _mod.to_int
    canonical_severity = _mod.canonical_severity


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
        "audit_failed": bool(audit_failed),
        "alerts": alerts,
        "vcenter_health": {
            "health": health,
            "summary": summary,
            "alerts": alerts,
            "audit_failed": bool(audit_failed),
            "data": copy.deepcopy((vmware_ctx.get("vcenter_health") or {}).get("data") or {}),
        },
        "check_metadata": {
            "engine": "ansible-ncs-vmware",
            "timestamp": timestamp,
            "thresholds": thresholds,
        },
    }
    return data


def audit_health_alerts(vmware_ctx):
    vmware_ctx = dict(vmware_ctx or {})
    app = dict((vmware_ctx.get("health") or {}).get("appliance") or {})
    h = dict(app.get("health") or {})
    backup = dict(app.get("backup") or {})
    config = dict(app.get("config") or {})
    overall = str(h.get("overall", "gray")).lower()
    dc_count = _to_int(((vmware_ctx.get("summary") or {}).get("datacenter_count", 0)), 0)

    alerts = []
    if dc_count == 0:
        alerts.append(
            _alert(
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
        alerts.append(_alert(sev, category, msg, detail))

    if bool(config.get("ssh_enabled", False)):
        alerts.append(
            _alert(
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
            _alert(
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


def audit_alarm_alerts(vmware_ctx, max_items=25):
    vmware_ctx = dict(vmware_ctx or {})
    alarms = dict((vmware_ctx.get("health") or {}).get("alarms") or {})
    alarm_list = _as_list(alarms.get("list"))
    metrics = dict(alarms.get("metrics") or {})
    status = str(alarms.get("status", "UNKNOWN"))
    crit_count = _to_int(metrics.get("critical_count", 0))
    warn_count = _to_int(metrics.get("warning_count", 0))
    total = _to_int(metrics.get("total", len(alarm_list)))
    max_items = max(_to_int(max_items, 25), 0)

    critical_items = [a for a in alarm_list if str((a or {}).get("severity", "")).lower() == "critical"]
    warning_items = [a for a in alarm_list if str((a or {}).get("severity", "")).lower() == "warning"]

    alerts = []
    if status != "SUCCESS":
        alerts.append(
            _alert(
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
            _alert(
                "CRITICAL",
                "vcenter_alarms",
                f"Active Critical Alarms: {crit_count} detected",
                {"critical_count": crit_count, "warning_count": warn_count},
                affected_items=critical_items[:max_items],
            )
        )
    elif warn_count > 0:
        alerts.append(
            _alert(
                "WARNING",
                "vcenter_alarms",
                f"Active Warning Alarms: {warn_count} detected",
                {"warning_count": warn_count},
                affected_items=warning_items[:max_items],
            )
        )
    return alerts


def audit_cluster_configuration_alerts(clusters, cpu_threshold=90, mem_threshold=90):
    clusters = _as_list(clusters)
    cpu_threshold = _to_float(cpu_threshold, 90)
    mem_threshold = _to_float(mem_threshold, 90)
    cluster_alerts = []
    noncompliant = []

    for item in clusters:
        item = item or {}
        name = item.get("name", "unknown")
        compliance = dict(item.get("compliance") or {})
        util = dict(item.get("utilization") or {})
        ha_enabled = bool(compliance.get("ha_enabled", False))
        drs_enabled = bool(compliance.get("drs_enabled", False))
        cpu_pct = _to_float(util.get("cpu_pct", 0), 0)
        mem_pct = _to_float(util.get("mem_pct", 0), 0)

        if (not ha_enabled) or (not drs_enabled):
            cluster_alerts.append(
                _alert(
                    "WARNING",
                    "cluster_compliance",
                    f"Policy Violation: HA/DRS disabled on cluster '{name}'",
                    {
                        "cluster": name,
                        "ha_state": "ENABLED" if ha_enabled else "DISABLED",
                        "drs_state": "ENABLED" if drs_enabled else "DISABLED",
                    },
                )
            )
        if not ha_enabled:
            noncompliant.append(item)

        if mem_pct > mem_threshold:
            cluster_alerts.append(
                _alert(
                    "WARNING",
                    "cluster_capacity",
                    f"Memory Saturation: Cluster '{name}' is at {util.get('mem_pct', 0)}%",
                    {
                        "cluster": name,
                        "current_pct": util.get("mem_pct", 0),
                        "threshold_pct": mem_threshold,
                    },
                )
            )
        if cpu_pct > cpu_threshold:
            cluster_alerts.append(
                _alert(
                    "WARNING",
                    "cluster_capacity",
                    f"CPU Saturation: Cluster '{name}' is at {util.get('cpu_pct', 0)}%",
                    {
                        "cluster": name,
                        "current_pct": util.get("cpu_pct", 0),
                        "threshold_pct": cpu_threshold,
                    },
                )
            )

    rollup_alerts = []
    if noncompliant:
        rollup_alerts.append(
            _alert(
                "WARNING",
                "cluster_compliance",
                f"{len(noncompliant)} cluster(s) have HA disabled",
                {},
                affected_items=[(c or {}).get("name") for c in noncompliant if (c or {}).get("name")],
            )
        )

    return {"cluster_alerts": cluster_alerts, "rollup_alerts": rollup_alerts}


def audit_storage_rollup_alerts(datastores, crit_pct=10, warn_pct=15, max_items=25):
    ds = _as_list(datastores)
    crit_pct = _to_float(crit_pct, 10)
    warn_pct = _to_float(warn_pct, 15)
    max_items = max(_to_int(max_items, 25), 0)

    crit_list = [d for d in ds if "free_pct" in (d or {}) and _to_float((d or {}).get("free_pct", 100), 100) < crit_pct]
    warn_list = [
        d
        for d in ds
        if "free_pct" in (d or {})
        and _to_float((d or {}).get("free_pct", 100), 100) < warn_pct
        and _to_float((d or {}).get("free_pct", 100), 100) >= crit_pct
    ]
    maint_list = [d for d in ds if str((d or {}).get("maintenance_mode", "normal")).lower() != "normal"]
    inacc_list = [d for d in ds if bool((d or {}).get("accessible", True)) is False]

    alerts = []
    if inacc_list:
        alerts.append(
            _build_count_alert(
                len(inacc_list),
                "CRITICAL",
                "storage_connectivity",
                f"Connectivity Failure: {len(inacc_list)} Datastore(s) are INACCESSIBLE",
                affected_items=inacc_list[:max_items],
                count_key="inaccessible_count",
            )
        )
    if crit_list:
        alerts.append(
            _build_count_alert(
                len(crit_list),
                "CRITICAL",
                "storage_capacity",
                f"{len(crit_list)} Datastore(s) critically low (<{crit_pct}% free)",
                affected_items=crit_list[:max_items],
                count_key="critical_count",
            )
        )
    if warn_list:
        alerts.append(
            _build_count_alert(
                len(warn_list),
                "WARNING",
                "storage_capacity",
                f"{len(warn_list)} Datastore(s) low (<{warn_pct}% free)",
                affected_items=warn_list[:max_items],
                count_key="warning_count",
            )
        )
    if maint_list:
        alerts.append(
            _build_count_alert(
                len(maint_list),
                "WARNING",
                "storage_configuration",
                f"Config Alert: {len(maint_list)} Datastore(s) in Maintenance Mode",
                affected_items=maint_list[:max_items],
                count_key="maintenance_count",
            )
        )
    return alerts


def audit_storage_object_alerts(datastores, crit_pct=10, warn_pct=15):
    ds = _as_list(datastores)
    crit_pct = _to_float(crit_pct, 10)
    warn_pct = _to_float(warn_pct, 15)
    alerts = []
    for item in ds:
        item = item or {}
        name = item.get("name", "unknown")
        free_pct = _to_float(item.get("free_pct", 100), 100)
        if not bool(item.get("accessible", True)):
            alerts.append(
                _alert(
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
        threshold_alert = _build_threshold_alert(
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
                threshold_alert["message"] = f"Datastore {name} is critically low ({free_pct}% free)"
            alerts.append(threshold_alert)
    return alerts


def audit_snapshot_alerts(vmware_ctx, age_warning_days=7, size_warning_gb=100, max_items=25):
    vmware_ctx = dict(vmware_ctx or {})
    summary = dict(((vmware_ctx.get("inventory") or {}).get("snapshots") or {}).get("summary") or {})
    aged_count = _to_int(summary.get("aged_count", 0))
    total_size_gb = _to_float(summary.get("total_size_gb", 0.0))
    oldest_days = _to_int(summary.get("oldest_days", 0))
    large = _as_list(summary.get("large_snapshots"))
    max_items = max(_to_int(max_items, 25), 0)

    alerts = []
    if aged_count > 0:
        alerts.append(
            _build_count_alert(
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
            _build_count_alert(
                len(large),
                "WARNING",
                "snapshots",
                f"{len(large)} VM(s) have oversized snapshots (>{_to_float(size_warning_gb, 100):g}GB)",
                affected_items=large[:max_items],
                count_key="large_snapshot_count",
            )
        )
    return alerts


def audit_tools_alerts(vmware_ctx, max_items=50):
    vmware_ctx = dict(vmware_ctx or {})
    vms = _as_list(((vmware_ctx.get("inventory") or {}).get("vms") or {}).get("list"))
    max_items = max(_to_int(max_items, 50), 0)
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
        _alert(
            "WARNING",
            "workload_compliance",
            f"Compliance Gap: {len(unhealthy)} powered-on VM(s) have unhealthy VMware Tools",
            {"total_impacted": len(unhealthy)},
            affected_items=[(vm or {}).get("name") for vm in unhealthy if (vm or {}).get("name")][:max_items],
            recommendation="Verify Tools installation to ensure backup quiescing and driver performance.",
        )
    ]


def audit_resource_rollup(clusters, cpu_crit=90, cpu_warn=80, mem_crit=90, mem_warn=80):
    clusters = _as_list(clusters)
    cpu_caps = [_to_int(((c or {}).get("utilization") or {}).get("cpu_total_mhz", 0)) for c in clusters]
    cpu_useds = [_to_int(((c or {}).get("utilization") or {}).get("cpu_used_mhz", 0)) for c in clusters]
    mem_caps = [_to_int(((c or {}).get("utilization") or {}).get("mem_total_mb", 0)) for c in clusters]
    mem_useds = [_to_int(((c or {}).get("utilization") or {}).get("mem_used_mb", 0)) for c in clusters]

    cpu_cap = sum(cpu_caps)
    cpu_used = sum(cpu_useds)
    mem_cap = sum(mem_caps)
    mem_used = sum(mem_useds)
    cpu_pct = round((cpu_used / max(cpu_cap, 1)) * 100.0, 1)
    mem_pct = round((mem_used / max(mem_cap, 1)) * 100.0, 1)

    alerts = []
    cpu_alert = _build_threshold_alert(
        cpu_pct,
        cpu_crit,
        cpu_warn,
        "capacity",
        f"CPU Saturation: {cpu_pct}%",
        detail={"cpu_used_mhz": cpu_used, "cpu_total_mhz": cpu_cap},
        value_key="usage_pct",
    )
    if cpu_alert is not None:
        alerts.append(cpu_alert)
    mem_alert = _build_threshold_alert(
        mem_pct,
        mem_crit,
        mem_warn,
        "capacity",
        f"Mem Saturation: {mem_pct}%",
        detail={"mem_used_mb": mem_used, "mem_total_mb": mem_cap},
        value_key="usage_pct",
    )
    if mem_alert is not None:
        alerts.append(mem_alert)

    return {
        "alerts": alerts,
        "utilization": {
            "cpu_total_mhz": cpu_cap,
            "cpu_used_mhz": cpu_used,
            "mem_total_mb": mem_cap,
            "mem_used_mb": mem_used,
            "cpu_pct": cpu_pct,
            "mem_pct": mem_pct,
        },
    }


def attach_audit_utilization(vmware_ctx, utilization):
    vmware_ctx = copy.deepcopy(dict(vmware_ctx or {}))
    utilization = dict(utilization or {})
    vmware_ctx.setdefault("vcenter_health", {})
    vmware_ctx["vcenter_health"].setdefault("data", {})
    vmware_ctx["vcenter_health"]["data"]["utilization"] = utilization
    return vmware_ctx


def attach_audit_results(vmware_ctx, alerts, audit_failed, health, summary):
    vmware_ctx = copy.deepcopy(dict(vmware_ctx or {}))
    alerts = list(alerts or [])
    health = dict(health or {})
    summary = dict(summary or {})

    vmware_ctx["alerts"] = alerts
    vmware_ctx.setdefault("vcenter_health", {})
    vmware_ctx["vcenter_health"]["health"] = health
    vmware_ctx["vcenter_health"]["summary"] = summary
    vmware_ctx["vcenter_health"]["alerts"] = alerts
    vmware_ctx["vcenter_health"]["audit_failed"] = bool(audit_failed)
    vmware_ctx["vcenter_health"].setdefault("data", {})
    return vmware_ctx


def append_alerts(existing_alerts, new_alerts):
    out = list(existing_alerts or [])
    if new_alerts is None:
        return out
    if isinstance(new_alerts, list):
        out.extend(new_alerts)
        return out
    out.append(new_alerts)
    return out


def compute_audit_rollups(alerts):
    alerts = list(alerts or [])
    summary = {
        "total": len(alerts),
        "critical_count": 0,
        "warning_count": 0,
        "info_count": 0,
        "by_category": {},
    }
    severities = set()

    for alert in alerts:
        if not isinstance(alert, dict):
            continue

        raw_severity = alert.get("severity", "INFO")
        severity = canonical_severity(raw_severity)
        category = str(alert.get("category", "uncategorized") or "uncategorized")
        severities.add(severity)

        if severity == "CRITICAL":
            summary["critical_count"] += 1
        elif severity == "WARNING":
            summary["warning_count"] += 1
        else:
            summary["info_count"] += 1

        summary["by_category"][category] = summary["by_category"].get(category, 0) + 1

    if "CRITICAL" in severities:
        health = "CRITICAL"
    elif "WARNING" in severities:
        health = "WARNING"
    else:
        health = "HEALTHY"

    return {"summary": summary, "health": health}


def build_owner_notification_context(vmware_ctx, owner_email):
    vmware_ctx = dict(vmware_ctx or {})
    owner_email = str(owner_email or "")
    inventory = dict(vmware_ctx.get("inventory") or {})
    vms_section = dict(inventory.get("vms") or {})
    snapshots_section = dict(inventory.get("snapshots") or {})

    all_vms = _as_list(vms_section.get("list"))
    my_vms = [vm for vm in all_vms if isinstance(vm, dict) and str(vm.get("owner_email") or "") == owner_email]
    my_names = [str(vm.get("name")) for vm in my_vms if str(vm.get("name") or "")]
    my_name_set = set(my_names)

    def _by_name(items, key="name"):
        return [item for item in _as_list(items) if isinstance(item, dict) and str(item.get(key) or "") in my_name_set]

    powered_off = [vm for vm in my_vms if str(vm.get("power_state") or "").upper() == "POWEREDOFF"]

    return {
        "my_vms": my_vms,
        "my_names": my_names,
        "my_issues": {
            "no_backup": _by_name(vms_section.get("never_backed_up"), "name"),
            "no_backup_tags": _by_name(vms_section.get("without_backup_tags"), "name"),
            "overdue_backup": _by_name(vms_section.get("with_overdue_backup"), "name"),
            "aged_snapshots": _by_name(snapshots_section.get("aged"), "vm_name"),
            "powered_off": powered_off,
        },
    }


def normalize_esxi_stig_facts(raw_api_facts, identity_facts=None, services_facts=None, ssh_facts=None):
    """
    Normalizes varied VMware ESXi facts into a canonical STIG schema.
    Fixes the advanced_settings dict -> config.option_value list mismatch.
    """
    api = dict(raw_api_facts or {})
    identity = dict(identity_facts or {})
    services = dict(services_facts or {})
    ssh = dict(ssh_facts or {})

    # 1. Build compatibility config.option_value list from advanced_settings dict
    adv_settings = api.get("advanced_settings", {})
    option_value_list = [{"key": k, "value": str(v)} for k, v in adv_settings.items()]

    # 2. Determine base identity fields
    name = api.get("name") or identity.get("name")
    uuid = api.get("uuid") or identity.get("uuid")
    version = identity.get("version") or api.get("version") or "unknown"
    build = identity.get("build") or api.get("build") or "unknown"

    # 3. Build canonical result
    return {
        "name": name,
        "uuid": uuid,
        "identity": {
            "version": version,
            "build": build,
            "uuid": uuid,
        },
        "services": services or api.get("services", {}),
        "system": api.get("system", {}),
        "advanced_settings_map": adv_settings,
        "config": {
            "option_value": option_value_list  # FIX for kernel/syslog templates
        },
        "ssh": {
            "sshd_config": ssh.get("sshd_config", ""),
            "banner_content": ssh.get("banner_content", ""),
            "firewall_raw": ssh.get("firewall_raw", ""),
        },
        "discovery_meta": {
            "schema_version": 1,
            "collectors": {
                "api": "vcenter_powercli_hybrid",
                "identity": "community.vmware.vmware_host_info",
                "services": "community.vmware.vmware_host_service_info",
                "ssh": "raw_ssh" if ssh_facts else "none",
            },
        },
    }


def normalize_vm_stig_facts(
    raw_vms,
    inventory_map=None,
    security_map=None,
    extra_config_map=None,
    hardware_map=None,
):
    """
    Normalizes VM STIG facts from multiple sources.
    """
    raw_vms = list(raw_vms or [])
    inv_map = dict(inventory_map or {})
    sec_map = dict(security_map or {})
    extra_map = dict(extra_config_map or {})
    hw_map = dict(hardware_map or {})

    results = []
    for vm in raw_vms:
        vm = dict(vm or {})
        name = vm.get("name", "unknown")

        inv = inv_map.get(name, {})
        sec = sec_map.get(name, {})
        extra = extra_map.get(name, {})
        hw = hw_map.get(name, {})

        # Determine shared fields with proper precedence
        uuid = inv.get("uuid") or vm.get("uuid")
        guest_id = inv.get("guest_id") or vm.get("guest_id", "unknown")
        tools_status = inv.get("tools_status") or vm.get("tools_status", "unknown")

        encryption = sec.get("encryption") or vm.get("encryption", "None")
        vmotion_encryption = sec.get("vmotion_encryption") or vm.get("vmotion_encryption", "disabled")
        logging_enabled = (
            sec.get("logging_enabled")
            if sec.get("logging_enabled") is not None
            else vm.get("logging_enabled", True)
        )
        ft_encryption = sec.get("ft_encryption") or vm.get("ft_encryption", "ftEncryptionDisabled")

        results.append(
            {
                "name": name,
                "uuid": uuid,
                "identity": {
                    "name": name,
                    "uuid": uuid,
                    "guest_id": guest_id,
                    "tools_status": tools_status,
                },
                "security": {
                    "encryption": encryption,
                    "vmotion_encryption": vmotion_encryption,
                    "logging_enabled": logging_enabled,
                    "ft_encryption": ft_encryption,
                },
                "advanced_settings": extra or vm.get("advanced_settings", {}),
                "hardware": hw or vm.get("hardware", {}),
                # Compatibility aliases for existing templates
                "tools_status": tools_status,
                "encryption": encryption,
                "vmotion_encryption": vmotion_encryption,
                "logging_enabled": logging_enabled,
                "ft_encryption": ft_encryption,
                "discovery_meta": {
                    "schema_version": 1,
                    "source": "hybrid_vm_collector",
                },
            }
        )
    return results


class FilterModule:
    def filters(self):
        return {
            "build_audit_export_payload": build_audit_export_payload,
            "audit_health_alerts": audit_health_alerts,
            "audit_alarm_alerts": audit_alarm_alerts,
            "audit_cluster_configuration_alerts": audit_cluster_configuration_alerts,
            "audit_storage_rollup_alerts": audit_storage_rollup_alerts,
            "audit_storage_object_alerts": audit_storage_object_alerts,
            "audit_snapshot_alerts": audit_snapshot_alerts,
            "audit_tools_alerts": audit_tools_alerts,
            "audit_resource_rollup": audit_resource_rollup,
            "attach_audit_utilization": attach_audit_utilization,
            "attach_audit_results": attach_audit_results,
            "append_alerts": append_alerts,
            "compute_audit_rollups": compute_audit_rollups,
            "build_owner_notification_context": build_owner_notification_context,
            "normalize_esxi_stig_facts": normalize_esxi_stig_facts,
            "normalize_vm_stig_facts": normalize_vm_stig_facts,
        }
