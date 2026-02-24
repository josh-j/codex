"""Template-facing reporting view-model builders."""

from pathlib import Path
import importlib.util

try:
    from .reporting_primitives import canonical_severity, to_float, to_int
except ImportError:
    _helper_path = Path(__file__).resolve().parent / "reporting_primitives.py"
    _spec = importlib.util.spec_from_file_location(
        "internal_core_reporting_primitives", _helper_path
    )
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    canonical_severity = _mod.canonical_severity
    to_float = _mod.to_float
    to_int = _mod.to_int


_DEFAULT_SKIP_KEYS = {
    "Summary",
    "Split",
    "platform",
    "history",
    "raw_state",
    "ubuntu",
    "vmware",
    "all_hosts_state",
    "all_hosts_state.yaml",
    "linux_fleet_state",
    "linux_fleet_state.yaml",
    "vmware_fleet_state",
    "vmware_fleet_state.yaml",
}


def default_report_skip_keys():
    """Return canonical structural/state keys that should be skipped in host loops."""
    return sorted(_DEFAULT_SKIP_KEYS)


def _status_from_health(value):
    if isinstance(value, dict):
        for key in ("overall", "status", "health"):
            v = value.get(key)
            if v is not None:
                return _status_from_health(v)
        return "UNKNOWN"

    text = str(value or "UNKNOWN").strip()
    low = text.lower()
    if low in ("green", "healthy", "ok", "success"):
        return "OK"
    if low in ("yellow", "warning", "degraded"):
        return "WARNING"
    if low in ("red", "critical", "failed", "error"):
        return "CRITICAL"
    if low in ("gray", "unknown"):
        return "UNKNOWN"
    return text.upper()


def _safe_pct(used, total):
    used_f = to_float(used, 0.0)
    total_f = max(to_float(total, 0.0), 1.0)
    return round((used_f / total_f) * 100.0, 1)


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _severity_for_pct(value_pct, warning=85.0, critical=90.0):
    pct = to_float(value_pct, 0.0)
    if pct > to_float(critical, 90.0):
        return "CRITICAL"
    if pct > to_float(warning, 85.0):
        return "WARNING"
    return "OK"


def _count_alerts(alerts):
    counts = {"critical": 0, "warning": 0, "total": 0}
    for alert in list(alerts or []):
        sev = canonical_severity((alert or {}).get("severity"))
        if sev == "CRITICAL":
            counts["critical"] += 1
        elif sev == "WARNING":
            counts["warning"] += 1
    counts["total"] = counts["critical"] + counts["warning"]
    return counts


def _iter_hosts(aggregated_hosts):
    if not isinstance(aggregated_hosts, dict):
        return []
    hosts_map = aggregated_hosts.get("hosts")
    if isinstance(hosts_map, dict):
        aggregated_hosts = hosts_map
    rows = []
    for hostname, bundle in aggregated_hosts.items():
        if hostname in _DEFAULT_SKIP_KEYS:
            continue
        if not isinstance(bundle, dict):
            continue
        rows.append((str(hostname), bundle))
    rows.sort(key=lambda item: item[0])
    return rows


def _iter_vmware_hosts(aggregated_hosts):
    return _iter_hosts(aggregated_hosts)


def _coerce_vmware_bundle(bundle):
    bundle = dict(bundle or {})
    discovery = dict(bundle.get("discovery") or {})
    audit = dict(bundle.get("vcenter") or bundle.get("audit") or {})
    if not audit:
        audit = bundle
    vcenter_health = dict(audit.get("vcenter_health") or bundle.get("vcenter_health") or {})
    alerts = list(
        audit.get("alerts")
        or vcenter_health.get("alerts")
        or bundle.get("alerts")
        or []
    )

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
    util = dict(((vh.get("data") or {}).get("utilization") or {}))
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
    try:
        return (
            discovery.get("health", {})
            .get("appliance", {})
            .get("info", {})
            .get("version", "N/A")
        )
    except AttributeError:
        return "N/A"


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
                "links": {"node_report_latest": "./%s/health_report.html" % hostname},
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


def _coerce_linux_audit(bundle):
    bundle = dict(bundle or {})
    linux_audit = dict(bundle.get("ubuntu_system_audit") or bundle.get("system") or {})
    stig = dict(bundle.get("stig") or {})
    return linux_audit, stig


def _extract_linux_sys_facts(linux_audit):
    linux_audit = dict(linux_audit or {})
    data = dict(linux_audit.get("data") or {})
    return dict(data.get("system") or {})


def build_linux_fleet_view(
    aggregated_hosts,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    rows = []
    active_alerts = []
    linux_stig_hosts = {}
    totals = {"critical": 0, "warning": 0, "hosts": 0}

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        linux_audit, stig = _coerce_linux_audit(bundle)
        if linux_audit:
            summary = dict(linux_audit.get("summary") or {})
            crit = to_int(summary.get("critical_count", 0), 0)
            warn = to_int(summary.get("warning_count", 0), 0)
            alerts = list(linux_audit.get("alerts") or [])
            rows.append(
                {
                    "name": hostname,
                    "status": {"raw": _status_from_health(linux_audit.get("health"))},
                    "distribution": linux_audit.get("distribution", "Ubuntu"),
                    "distribution_version": linux_audit.get("distribution_version", ""),
                    "summary": {
                        "critical_count": crit,
                        "warning_count": warn,
                    },
                    "alerts": alerts,
                    "links": {
                        "node_report_latest": "./%s/health_report.html" % hostname,
                        "node_report_stamped": "./%s/health_report_%s.html" % (hostname, report_stamp or ""),
                    },
                }
            )
            totals["critical"] += crit
            totals["warning"] += warn
            totals["hosts"] += 1
            for alert in alerts:
                active_alerts.append(
                    {
                        "host": hostname,
                        "severity": canonical_severity((alert or {}).get("severity")),
                        "category": (alert or {}).get("category", "System"),
                        "message": (alert or {}).get("message", ""),
                        "raw": dict(alert or {}),
                    }
                )

        if stig:
            linux_stig_hosts[hostname] = {"stig_ubuntu": dict(stig)}

    stig_fleet = build_stig_fleet_view(
        {"hosts": linux_stig_hosts},
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "fleet": {
            "hosts": totals["hosts"],
            "alerts": {
                "critical": totals["critical"],
                "warning": totals["warning"],
                "total": totals["critical"] + totals["warning"],
            },
        },
        "rows": rows,
        "active_alerts": active_alerts,
        "stig_fleet": stig_fleet,
    }


def build_linux_node_view(
    hostname,
    bundle,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    linux_audit, stig = _coerce_linux_audit(bundle)
    linux_audit = dict(linux_audit or {})
    sys_facts = _extract_linux_sys_facts(linux_audit)

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "node": {
            "name": str(hostname),
            "status": {"raw": _status_from_health(linux_audit.get("health"))},
            "distribution": linux_audit.get("distribution", "Linux"),
            "distribution_version": linux_audit.get("distribution_version", ""),
            "alerts": list(linux_audit.get("alerts") or []),
            "summary": dict(linux_audit.get("summary") or {}),
            "sys_facts": sys_facts,
            "stig": stig,
            "links": {
                "global_dashboard": "../../../site_health_report.html",
                "fleet_dashboard": "../ubuntu_health_report.html",
            },
        },
    }


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
                dict(vmw.get("vcenter_health") or {}).get("health")
                or dict(vmw.get("audit") or {}).get("health")
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

    totals = {
        "critical": len([a for a in all_alerts if a["severity"] == "CRITICAL"]),
        "warning": len([a for a in all_alerts if a["severity"] == "WARNING"]),
    }
    c_alarms_critical = len(
        [a for a in all_alerts if a["severity"] == "CRITICAL" and "vcenter" in a["audit_type"]]
    )
    c_alarms_warning = len(
        [a for a in all_alerts if a["severity"] == "WARNING" and "vcenter" in a["audit_type"]]
    )

    linux_count = len(list(inventory_groups.get("ubuntu_servers") or []))
    vmware_count = len(list(inventory_groups.get("vcenters") or []))

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "totals": totals,
        "platforms": {
            "linux": {
                "asset_count": linux_count,
                "asset_label": "Nodes",
                "status": {
                    "raw": (
                        "CRITICAL"
                        if any(a["audit_type"] == "system" and a["severity"] == "CRITICAL" for a in all_alerts)
                        else "OK"
                    )
                },
                "links": {"fleet_dashboard": "platform/ubuntu/ubuntu_health_report.html"},
            },
            "vmware": {
                "asset_count": vmware_count,
                "asset_label": "Clusters",
                "status": {"raw": "CRITICAL" if c_alarms_critical > 0 else "OK"},
                "links": {"fleet_dashboard": "platform/vmware/vmware_health_report.html"},
            },
        },
        "security": {
            "stig_fleet": stig_fleet,
        },
        "compute": {
            "nodes": compute_nodes,
        },
    }


def _canonical_stig_status(value):
    text = str(value or "").strip().lower()
    if text in ("failed", "fail", "open", "non-compliant", "non_compliant"):
        return "open"
    if text in ("pass", "passed", "compliant", "success"):
        return "pass"
    if text in ("na", "n/a", "not_applicable", "not applicable"):
        return "na"
    if text in ("not_reviewed", "not reviewed", "unreviewed"):
        return "not_reviewed"
    if text in ("error", "unknown"):
        return text
    return text or "unknown"


def _canonical_stig_severity(value):
    return canonical_severity(value)


def _infer_stig_platform(audit_type, payload):
    at = str(audit_type or "").lower()
    if "vmware" in at or "esxi" in at or at in ("stig_vm", "stig_esxi"):
        return "vmware"
    if "ubuntu" in at or "linux" in at:
        return "linux"
    target_type = str((payload or {}).get("target_type", "")).lower()
    if "esxi" in target_type or "vm" in target_type:
        return "vmware"
    if "ubuntu" in target_type or "linux" in target_type:
        return "linux"
    return "unknown"


def _infer_stig_target_type(audit_type, payload):
    at = str(audit_type or "")
    lower_at = at.lower()
    if lower_at.startswith("stig_"):
        return lower_at.replace("stig_", "", 1)
    detail_target = str((payload or {}).get("target_type", "")).strip()
    if detail_target:
        return detail_target
    return lower_at or "unknown"


def _normalize_stig_finding(finding_or_alert, audit_type, platform):
    item = dict(finding_or_alert or {})
    detail = dict(item.get("detail") or {})
    if not detail:
        for key in (
            "checktext",
            "fixtext",
            "details",
            "description",
            "status",
            "id",
            "title",
            "severity",
        ):
            if key in item and item.get(key) is not None:
                detail[key] = item.get(key)
    raw_status = item.get("status", detail.get("status", "open"))
    status = _canonical_stig_status(raw_status)

    raw_severity = (
        item.get("severity")
        or detail.get("original_severity")
        or detail.get("severity")
        or "INFO"
    )
    severity = _canonical_stig_severity(raw_severity)

    rule_id = str(
        detail.get("rule_id")
        or detail.get("vuln_id")
        or item.get("rule_id")
        or item.get("vuln_id")
        or item.get("id")
        or ""
    )

    title = str(
        item.get("title")
        or detail.get("title")
        or (item.get("message") or "").replace("STIG Violation: ", "")
        or rule_id
        or "Unknown Rule"
    )
    message = str(item.get("message") or detail.get("description") or title)
    category = str(item.get("category") or "security_compliance")

    return {
        "rule_id": rule_id,
        "vuln_id": str(detail.get("vuln_id") or rule_id),
        "severity": severity,
        "category": str(raw_severity).upper() if str(raw_severity) else "INFO",
        "status": status,
        "title": title,
        "message": message,
        "check_result": str(raw_status or ""),
        "fix_available": None,
        "references": {},
        "detail": detail,
        "raw": item,
        "platform": platform,
        "audit_type": str(audit_type or ""),
    }


def _summarize_stig_findings(findings):
    findings = list(findings or [])
    out = {
        "findings": {"total": 0, "critical": 0, "warning": 0, "info": 0},
        "by_status": {"open": 0, "pass": 0, "na": 0, "not_reviewed": 0, "unknown": 0},
    }
    for f in findings:
        sev = str((f or {}).get("severity") or "INFO").upper()
        status = str((f or {}).get("status") or "unknown")
        out["findings"]["total"] += 1
        if sev == "CRITICAL":
            out["findings"]["critical"] += 1
        elif sev == "WARNING":
            out["findings"]["warning"] += 1
        else:
            out["findings"]["info"] += 1

        if status not in out["by_status"]:
            status = "unknown"
        out["by_status"][status] += 1
    return out


def build_stig_host_view(
    hostname,
    audit_type,
    stig_payload,
    *,
    platform=None,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    stig_payload = dict(stig_payload or {})
    platform_name = platform or _infer_stig_platform(audit_type, stig_payload)
    target_type = _infer_stig_target_type(audit_type, stig_payload)

    source_findings = []
    if isinstance(stig_payload.get("full_audit"), list):
        for row in stig_payload.get("full_audit") or []:
            source_findings.append(
                _normalize_stig_finding(row, audit_type, platform_name)
            )
    else:
        for alert in stig_payload.get("alerts") or []:
            source_findings.append(
                _normalize_stig_finding(alert, audit_type, platform_name)
            )

    summary = _summarize_stig_findings(source_findings)
    health = _status_from_health(stig_payload.get("health"))

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "target": {
            "host": str(hostname),
            "platform": platform_name,
            "target_type": target_type,
            "audit_type": str(audit_type or ""),
            "status": {"raw": health, "label": health},
        },
        "summary": {
            "findings": summary["findings"],
            "by_status": summary["by_status"],
            "score": {"compliance_pct": None},
        },
        "findings": source_findings,
        "sections": [],
    }


def build_stig_fleet_view(
    aggregated_hosts,
    *,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    rows = []
    top_index = {}
    totals = {"hosts": 0, "findings_open": 0, "critical": 0, "warning": 0}
    by_platform = {
        "linux": {"hosts": 0, "open": 0, "critical": 0, "warning": 0},
        "vmware": {"hosts": 0, "open": 0, "critical": 0, "warning": 0},
        "unknown": {"hosts": 0, "open": 0, "critical": 0, "warning": 0},
    }

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for audit_type, payload in dict(bundle or {}).items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            host_view = build_stig_host_view(
                hostname,
                audit_type,
                payload,
                report_stamp=report_stamp,
                report_date=report_date,
                report_id=report_id,
            )
            target = host_view["target"]
            summary = host_view["summary"]
            findings = host_view["findings"]
            platform_name = target["platform"] if target["platform"] in by_platform else "unknown"
            open_count = summary["by_status"].get("open", 0)
            crit = summary["findings"].get("critical", 0)
            warn = summary["findings"].get("warning", 0)

            totals["hosts"] += 1
            totals["findings_open"] += open_count
            totals["critical"] += crit
            totals["warning"] += warn
            by_platform[platform_name]["hosts"] += 1
            by_platform[platform_name]["open"] += open_count
            by_platform[platform_name]["critical"] += crit
            by_platform[platform_name]["warning"] += warn

            link_base = "platform/vmware" if platform_name == "vmware" else "platform/ubuntu"
            rows.append(
                {
                    "host": hostname,
                    "platform": platform_name,
                    "audit_type": str(audit_type),
                    "status": dict(target.get("status") or {}),
                    "findings_open": open_count,
                    "critical": crit,
                    "warning": warn,
                    "links": {
                        "node_report_latest": "%s/%s/health_report.html" % (link_base, hostname),
                    },
                    "findings": [f for f in findings if f.get("status") == "open"],
                }
            )

            for f in findings:
                rid = f.get("rule_id") or "UNKNOWN"
                idx = top_index.setdefault(
                    rid,
                    {
                        "rule_id": rid,
                        "affected_hosts": set(),
                        "severity": f.get("severity", "INFO"),
                        "title": f.get("title", rid),
                    },
                )
                if f.get("status") == "open":
                    idx["affected_hosts"].add(hostname)

    top_findings = []
    for item in top_index.values():
        count = len(item["affected_hosts"])
        if count == 0:
            continue
        top_findings.append(
            {
                "rule_id": item["rule_id"],
                "affected_hosts": count,
                "severity": item["severity"],
                "title": item["title"],
            }
        )
    top_findings.sort(key=lambda x: (-x["affected_hosts"], x["rule_id"]))
    rows.sort(key=lambda x: (x["platform"], x["host"], x["audit_type"]))

    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "fleet": {
            "totals": totals,
            "by_platform": by_platform,
        },
        "rows": rows,
        "findings_index": {"top_findings": top_findings[:20]},
    }
