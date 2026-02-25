import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.report_view_models_common import (
        _iter_hosts,
        _status_from_health,
        canonical_severity,
    )
except ImportError:
    _helper_path = (
        Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "report_view_models_common.py"
    )
    _spec = importlib.util.spec_from_file_location("internal_core_report_view_models_common", _helper_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _iter_hosts = _mod._iter_hosts
    _status_from_health = _mod._status_from_health
    canonical_severity = _mod.canonical_severity


def _coerce_windows_audit(bundle):
    bundle = dict(bundle or {})
    audit = dict(bundle.get("windows_audit") or bundle.get("windows") or {})
    if not audit and ("data" in bundle or "health" in bundle):
        audit = bundle
    return audit


def windows_fleet_view(aggregated_hosts, report_stamp=None, report_date=None, report_id=None):
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
        status = _status_from_health(audit.get("health"))
        if status == "CRITICAL":
            totals["critical"] += 1
        elif status == "WARNING":
            totals["warning"] += 1
        totals["hosts"] += 1
        rows.append(
            {
                "name": hostname,
                "status": {"raw": status},
                "summary": summary,
                "applications": apps,
                "updates": updates,
                "alerts": list(audit.get("alerts") or []),
                "links": {
                    "node_report_latest": f"./{hostname}/health_report.html",
                    "node_report_stamped": f"./{hostname}/health_report_{report_stamp or ''}.html",
                },
            }
        )
        for alert in list(audit.get("alerts") or []):
            sev = canonical_severity((alert or {}).get("severity"))
            if sev in ("CRITICAL", "WARNING"):
                active_alerts.append(
                    {
                        "host": hostname,
                        "severity": sev,
                        "category": (alert or {}).get("category", "windows"),
                        "message": (alert or {}).get("message", ""),
                    }
                )

    rows.sort(key=lambda r: r["name"])
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
    }


def windows_node_view(bundle, hostname=None, report_stamp=None, report_date=None, report_id=None):
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


class FilterModule:
    def filters(self):
        return {
            "windows_fleet_view": windows_fleet_view,
            "windows_node_view": windows_node_view,
        }
