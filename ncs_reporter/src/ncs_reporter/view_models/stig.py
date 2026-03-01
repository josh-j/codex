"""STIG reporting view-model builders."""

from typing import Any

from .common import _iter_hosts, _status_from_health, build_meta, canonical_severity, safe_list


def _canonical_stig_status(value: Any) -> str:
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


def _canonical_stig_severity(value: Any) -> str:
    return canonical_severity(value)


def _infer_stig_platform(audit_type: Any, payload: dict[str, Any] | None) -> str:
    at = str(audit_type or "").lower()
    if "vmware" in at or "esxi" in at or at in ("stig_vm", "stig_esxi"):
        return "vmware"
    if "ubuntu" in at or "linux" in at:
        return "linux"
    if "windows" in at or at in ("stig_windows",):
        return "windows"
    target_type = str((payload or {}).get("target_type", "")).lower()
    if "esxi" in target_type or "vm" in target_type:
        return "vmware"
    if "ubuntu" in target_type or "linux" in target_type:
        return "linux"
    if "windows" in target_type:
        return "windows"
    return "unknown"


def _infer_stig_target_type(audit_type: Any, payload: dict[str, Any] | None) -> str:
    at = str(audit_type or "")
    lower_at = at.lower()
    if lower_at.startswith("stig_"):
        return lower_at.replace("stig_", "", 1)
    detail_target = str((payload or {}).get("target_type", "")).strip()
    if detail_target:
        return detail_target
    return lower_at or "unknown"


def _normalize_stig_finding(finding_or_alert: Any, audit_type: Any, platform: str) -> dict[str, Any]:
    if not isinstance(finding_or_alert, dict):
        finding_or_alert = {"message": str(finding_or_alert)}

    item = dict(finding_or_alert)
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

    raw_severity = item.get("severity") or detail.get("original_severity") or detail.get("severity") or "INFO"
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
        or (str(item.get("message") or "")).replace("STIG Violation: ", "")
        or rule_id
        or "Unknown Rule"
    )
    message = str(item.get("message") or detail.get("description") or title)

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


def _summarize_stig_findings(findings: Any) -> dict[str, dict[str, int]]:
    out = {
        "findings": {"total": 0, "critical": 0, "warning": 0, "info": 0},
        "by_status": {"open": 0, "pass": 0, "na": 0, "not_reviewed": 0, "unknown": 0},
    }
    for f in safe_list(findings):
        sev = str((f or {}).get("severity") or "INFO").upper()
        status = str((f or {}).get("status") or "unknown")
        out["findings"]["total"] += 1
        
        if status not in out["by_status"]:
            status = "unknown"
        out["by_status"][status] += 1
        
        if status == "open":
            if sev in ("CRITICAL", "HIGH"):
                out["findings"]["critical"] += 1
            elif sev in ("WARNING", "MEDIUM"):
                out["findings"]["warning"] += 1
            else:
                out["findings"]["info"] += 1
    return out


def build_stig_host_view(
    hostname: str,
    audit_type: Any,
    stig_payload: Any,
    *,
    host_bundle: dict[str, Any] | None = None,
    hosts_data: dict[str, Any] | None = None,
    platform: str | None = None,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: dict[str, str] | None = None,
) -> dict[str, Any]:
    stig_payload = dict(stig_payload or {})
    platform_name = platform or _infer_stig_platform(audit_type, stig_payload)
    target_type = _infer_stig_target_type(audit_type, stig_payload)

    source_findings = []
    full_audit = stig_payload.get("full_audit")
    if isinstance(full_audit, list):
        for row in full_audit:
            source_findings.append(_normalize_stig_finding(row, audit_type, platform_name))
    else:
        for alert in safe_list(stig_payload.get("alerts")):
            source_findings.append(_normalize_stig_finding(alert, audit_type, platform_name))

    summary = _summarize_stig_findings(source_findings)
    health = _status_from_health(stig_payload.get("health"))

    _status_order = {"open": 0, "na": 1, "pass": 2}
    _sev_order = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "low": 2, "info": 2}
    source_findings.sort(
        key=lambda f: (
            _status_order.get(str(f.get("status") or "").lower(), 3),
            _sev_order.get(str(f.get("severity") or "").lower(), 3),
            str(f.get("rule_id") or "")
        )
    )

    # Build nav tree information
    nav_with_tree = {**nav} if nav else {}
    
    # Sibling STIG audits for the same host (e.g. if a host has both ESXi and VM STIGs)
    siblings = []
    if host_bundle:
        for k in host_bundle.keys():
            if k.lower().startswith("stig_") and k != audit_type:
                # Determine target type for the link
                p = host_bundle[k]
                t_type = _infer_stig_target_type(k, p)
                siblings.append({
                    "name": f"{t_type.upper()} STIG",
                    "report": f"{hostname}_stig_{t_type}.html"
                })
    siblings.sort(key=lambda x: x["name"])
    nav_with_tree["tree_siblings"] = siblings

    # Global fleets dropdown
    if hosts_data:
        current_plt_dir = hosts_data.get(hostname)
        depth = len(current_plt_dir.split('/')) + 1 if current_plt_dir else 3
        back_to_root = "../" * (depth + 1) # back to site root
        
        fleets = []
        p_dirs = sorted(list(set(hosts_data.values())))
        for plt_dir in p_dirs:
            if "vcenter" in plt_dir:
                label = "VMware"
                schema_name = "vcenter"
            elif "ubuntu" in plt_dir:
                label = "Linux"
                schema_name = "linux"
            else:
                label = plt_dir.split('/')[-1].capitalize()
                schema_name = plt_dir.split('/')[-1]
            
            fleets.append({
                "name": label, 
                "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"
            })
        
        fleets.append({
            "name": "STIG",
            "report": f"{back_to_root}stig_fleet_report.html"
        })
        nav_with_tree["tree_fleets"] = fleets
    
    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "nav": nav_with_tree,
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
        "widgets": [],
    }


def build_stig_fleet_view(
    aggregated_hosts: dict[str, Any],
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = []
    top_index: dict[str, dict[str, Any]] = {}
    totals = {"hosts": 0, "findings_open": 0, "critical": 0, "warning": 0, "info": 0}
    by_platform = {
        "linux": {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0},
        "vmware": {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0},
        "windows": {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0},
        "unknown": {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0},
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
                nav=nav,
            )
            target = host_view["target"]
            summary = host_view["summary"]
            findings = host_view["findings"]
            p_name = target["platform"] if target["platform"] in by_platform else "unknown"
            open_count = summary["by_status"].get("open", 0)
            crit = summary["findings"].get("critical", 0)
            warn = summary["findings"].get("warning", 0)
            info = summary["findings"].get("info", 0)

            totals["hosts"] += 1
            totals["findings_open"] += open_count
            totals["critical"] += crit
            totals["warning"] += warn
            totals["info"] += info
            by_platform[p_name]["hosts"] += 1
            by_platform[p_name]["open"] += open_count
            by_platform[p_name]["critical"] += crit
            by_platform[p_name]["warning"] += warn
            by_platform[p_name]["info"] += info

            # Use the canonical STIG report name pattern: <host>_stig_<target_type>.html
            t_type = target.get("target_type", "unknown")
            stamped_name = f"{hostname}_stig_{t_type}.html"

            if p_name == "vmware":
                if t_type == "esxi":
                    link_base = "platform/vmware/esxi"
                elif t_type == "vm":
                    link_base = "platform/vmware/vm"
                else:
                    link_base = "platform/vmware/vcenter"
            elif p_name == "windows":
                link_base = "platform/windows"
            else:
                link_base = "platform/linux/ubuntu"

            rows.append(
                {
                    "host": hostname,
                    "platform": p_name,
                    "audit_type": str(audit_type),
                    "status": dict(target.get("status") or {}),
                    "findings_open": open_count,
                    "critical": crit,
                    "warning": warn,
                    "links": {
                        "node_report_latest": f"{link_base}/{hostname}/{stamped_name}",
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
    _sev_order = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "low": 2, "info": 2}
    top_findings.sort(
        key=lambda x: (
            -int(x["affected_hosts"]),
            _sev_order.get(str(x.get("severity") or "").lower(), 3),
            str(x["rule_id"])
        )
    )
    rows.sort(key=lambda x: (str(x["platform"]), str(x["host"]), str(x["audit_type"])))

    # Build nav tree information
    nav_with_tree = {**nav} if nav else {}
    # We can derive tree_fleets from by_platform if they have hosts
    tree_fleets = []
    p_config = {
        "linux": {"label": "Linux", "link": "platform/linux/ubuntu/linux_fleet_report.html"},
        "vmware": {"label": "VMware", "link": "platform/vmware/vcenter/vcenter_fleet_report.html"},
        "windows": {"label": "Windows", "link": "platform/windows/windows_fleet_report.html"},
    }
    for p_key in ["linux", "vmware", "windows"]:
        if by_platform.get(p_key, {}).get("hosts", 0) > 0:
            tree_fleets.append({"name": p_config[p_key]["label"], "report": p_config[p_key]["link"]})
    
    # Add STIG fleet
    tree_fleets.append({"name": "STIG", "report": "stig_fleet_report.html"})
    nav_with_tree["tree_fleets"] = tree_fleets

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "nav": nav_with_tree,
        "fleet": {
            "totals": totals,
            "by_platform": by_platform,
        },
        "rows": rows,
        "findings_index": {"top_findings": top_findings[:20]},
    }
