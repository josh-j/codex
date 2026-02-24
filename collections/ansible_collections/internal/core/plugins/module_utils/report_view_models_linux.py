"""Linux reporting view-model builders."""

import importlib.util
from pathlib import Path

try:
    from .report_view_models_common import (
        _iter_hosts,
        _status_from_health,
        canonical_severity,
        safe_list,
        to_int,
    )
    from .report_view_models_stig import build_stig_fleet_view
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
    _stig = _load("report_view_models_stig")
    _iter_hosts = _common._iter_hosts
    _status_from_health = _common._status_from_health
    canonical_severity = _common.canonical_severity
    safe_list = _common.safe_list
    to_int = _common.to_int
    build_stig_fleet_view = _stig.build_stig_fleet_view


def _coerce_linux_audit(bundle):
    bundle = dict(bundle or {})
    # Handle nested audit keys from recursive aggregator
    linux_audit = dict(bundle.get("ubuntu_system_audit") or bundle.get("system") or bundle.get("audit") or {})
    stig = dict(bundle.get("stig") or bundle.get("ubuntu_stig_audit") or bundle.get("stig_ubuntu") or {})

    # Fallback for flat loads
    if not linux_audit and ("data" in bundle or "health" in bundle):
        linux_audit = bundle

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
            alerts = safe_list(linux_audit.get("alerts"))
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
                        "node_report_latest": f"./{hostname}/health_report.html",
                        "node_report_stamped": f"./{hostname}/health_report_{report_stamp or ''}.html",
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
