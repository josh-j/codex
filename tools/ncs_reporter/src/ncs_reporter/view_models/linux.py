"""Linux reporting view-model builders."""

from typing import Any

from .common import (
    _iter_hosts,
    _status_from_health,
    canonical_severity,
    safe_list,
    to_int,
)
from .stig import build_stig_fleet_view


def _coerce_linux_audit(bundle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = dict(bundle or {})
    # Handle nested audit keys from recursive aggregator
    linux_audit = dict(
        bundle.get("linux_system")
        or bundle.get("ubuntu_system_audit")
        or bundle.get("system")
        or bundle.get("audit")
        or {}
    )
    stig = dict(
        bundle.get("stig_linux")
        or bundle.get("stig")
        or bundle.get("ubuntu_stig_audit")
        or bundle.get("stig_ubuntu")
        or {}
    )

    # Fallback for flat loads
    if not linux_audit and ("data" in bundle or "health" in bundle):
        linux_audit = bundle

    return linux_audit, stig


def _extract_linux_sys_facts(linux_audit: Any) -> dict[str, Any]:
    linux_audit = dict(linux_audit or {})
    data = dict(linux_audit.get("data") or {})
    return dict(data.get("system") or {})


def build_linux_fleet_view(
    aggregated_hosts: dict[str, Any],
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
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
            alerts = safe_list(linux_audit.get("alerts"))
            alert_counts = {"critical": crit, "warning": warn, "total": crit + warn}
            rows.append(
                {
                    "name": hostname,
                    "status": {"raw": _status_from_health(linux_audit.get("health"))},
                    "distribution": linux_audit.get("distribution", "Ubuntu"),
                    "distribution_version": linux_audit.get("distribution_version", ""),
                    "summary": {
                        "critical_count": crit,
                        "warning_count": warn,
                        "alerts": alert_counts,
                    },
                    "alerts": alerts,
                    "links": {
                        "node_report_latest": f"./{hostname}/health_report.html",
                        "node_report_stamped": f"./{hostname}/health_report_{report_stamp or ''}.html",
                    },
                }
            )
            totals["critical"] += crit
            totals["warning"] += warn
            totals["hosts"] += 1
            for alert in alerts:
                sev = canonical_severity((alert or {}).get("severity"))
                if sev not in ("CRITICAL", "WARNING"):
                    continue
                active_alerts.append(
                    {
                        "host": hostname,
                        "severity": sev,
                        "category": (alert or {}).get("category", "System"),
                        "audit_type": "linux_system",
                        "message": (alert or {}).get("message", ""),
                        "raw": dict(alert or {}),
                    }
                )

        if stig:
            linux_stig_hosts[hostname] = {"stig_linux": dict(stig)}

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
        "stig_fleet": stig_fleet,
    }


def build_linux_node_view(
    hostname: str,
    bundle: Any,
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
) -> dict[str, Any]:
    linux_audit, stig = _coerce_linux_audit(bundle)
    linux_audit = dict(linux_audit or {})
    sys_facts = _extract_linux_sys_facts(linux_audit)
    audit_data = dict(linux_audit.get("data") or {})

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
            "alerts": safe_list(linux_audit.get("alerts")),
            "summary": dict(linux_audit.get("summary") or {}),
            "sys_facts": sys_facts,
            "data": audit_data,
            "stig": stig,
            "links": {
                "global_dashboard": "../../../site_health_report.html",
                "fleet_dashboard": "../ubuntu_health_report.html",
            },
        },
    }
