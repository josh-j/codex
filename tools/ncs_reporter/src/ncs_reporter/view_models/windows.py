"""Windows reporting view-model builders."""

from typing import Any

from .common import (
    _iter_hosts,
    _status_from_health,
    canonical_severity,
)


def _coerce_windows_audit(bundle: Any) -> dict[str, Any]:
    bundle = dict(bundle or {})
    audit = dict(
        bundle.get("windows_audit")
        or bundle.get("windows")
        or {}
    )
    if not audit and ("data" in bundle or "health" in bundle):
        audit = bundle
    return audit


def build_windows_fleet_view(
    aggregated_hosts: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    rows = []
    active_alerts = []
    totals = {"hosts": 0, "critical": 0, "warning": 0}

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        audit = _coerce_windows_audit(bundle)
        if not audit:
            continue
        summary = dict(audit.get("summary") or {})
        apps = dict(summary.get("applications") or {})
        updates = dict(summary.get("updates") or {})
        alerts_list = list(audit.get("alerts") or [])
        alert_counts = {"critical": 0, "warning": 0, "total": 0}
        
        for alert in alerts_list:
            sev = canonical_severity((alert or {}).get("severity"))
            if sev == "CRITICAL":
                alert_counts["critical"] += 1
            elif sev == "WARNING":
                alert_counts["warning"] += 1
        alert_counts["total"] = alert_counts["critical"] + alert_counts["warning"]

        status = _status_from_health(audit.get("health"))
        if status == "CRITICAL":
            totals["critical"] += 1
        elif status == "WARNING":
            totals["warning"] += 1
        totals["hosts"] += 1
        
        row_summary = dict(summary)
        row_summary["alerts"] = alert_counts

        rows.append(
            {
                "name": hostname,
                "status": {"raw": status},
                "summary": row_summary,
                "applications": apps,
                "updates": updates,
                "alerts": alerts_list,
                "links": {
                    "node_report_latest": f"./{hostname}/health_report.html",
                    "node_report_stamped": f"./{hostname}/health_report_{report_stamp or ''}.html",
                },
            }
        )
        for alert in alerts_list:
            sev = canonical_severity((alert or {}).get("severity"))
            if sev in ("CRITICAL", "WARNING"):
                active_alerts.append(
                    {
                        "host": hostname,
                        "severity": sev,
                        "category": (alert or {}).get("category", "windows"),
                        "audit_type": "windows_audit",
                        "message": (alert or {}).get("message", ""),
                        "raw": dict(alert or {}),
                    }
                )

    rows.sort(key=lambda r: str(r["name"]))
    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "fleet": {
            "asset_count": totals["hosts"],
            "hosts": totals["hosts"],
            "alerts": {
                "critical": totals["critical"],
                "warning": totals["warning"],
                "total": totals["critical"] + totals["warning"],
            },
        },
        "rows": rows,
        "active_alerts": active_alerts,
    }


def build_windows_node_view(
    bundle: Any,
    hostname: str | None = None,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    audit = _coerce_windows_audit(bundle)
    summary = dict(audit.get("summary") or {})
    return {
        "meta": {
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "node": {
            "name": str(hostname or "unknown"),
            "status": {"raw": _status_from_health(audit.get("health"))},
            "summary": summary,
            "alerts": list(audit.get("alerts") or []),
            "data": dict(audit.get("windows_ctx") or audit.get("data") or {}),
            "links": {
                "global_dashboard": "../../../site_health_report.html",
                "fleet_dashboard": "../windows_health_report.html",
            },
        },
    }
