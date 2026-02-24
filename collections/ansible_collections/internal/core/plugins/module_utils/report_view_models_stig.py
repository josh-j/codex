"""STIG reporting view-model builders."""

import importlib.util
from pathlib import Path

try:
    from .report_view_models_common import _iter_hosts, _status_from_health, canonical_severity
except ImportError:
    _helper_path = Path(__file__).resolve().parent / "report_view_models_common.py"
    _spec = importlib.util.spec_from_file_location("internal_core_report_view_models_common", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _iter_hosts = _mod._iter_hosts
    _status_from_health = _mod._status_from_health
    canonical_severity = _mod.canonical_severity


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
        or (item.get("message") or "").replace("STIG Violation: ", "")
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
            source_findings.append(_normalize_stig_finding(row, audit_type, platform_name))
    else:
        for alert in stig_payload.get("alerts") or []:
            source_findings.append(_normalize_stig_finding(alert, audit_type, platform_name))

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
        "windows": {"hosts": 0, "open": 0, "critical": 0, "warning": 0},
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

            if platform_name == "vmware":
                link_base = "platform/vmware"
            elif platform_name == "windows":
                link_base = "platform/windows"
            else:
                link_base = "platform/ubuntu"
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
                        "node_report_latest": f"{link_base}/{hostname}/health_report.html",
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
