"""Site dashboard reporting view-model builders."""

from __future__ import annotations

from typing import Any

from .._report_context import ReportContext
from ..platform_registry import PlatformRegistry, default_registry
from .common import (
    _count_alerts,
    _iter_hosts,
    _status_from_health,
    aggregate_platform_status,
    build_meta,
    extract_platform_alerts,
    safe_list,
    to_int,
)
from .stig import build_stig_fleet_view


def _get_schema_audit(bundle: dict[str, Any], *names: str) -> dict[str, Any] | None:
    """Return the first matching schema audit from a host bundle."""
    for name in names:
        audit = bundle.get(f"schema_{name}")
        if audit:
            return dict(audit)
    return None



def build_site_dashboard_view(
    aggregated_hosts: dict[str, Any],
    *,
    ctx: ReportContext | None = None,
    registry: PlatformRegistry | None = None,
    cklb_dir: Any = None,
    generated_fleet_dirs: set[str] | None = None,
) -> dict[str, Any]:
    from ncs_reporter.models.platforms_config import (
        FILENAME_HEALTH_REPORT as _FHR,
        PLATFORM_DIR_PREFIX as _PDP,
        fleet_link_url,
    )
    reg = registry or default_registry()
    all_alerts: list[dict[str, Any]] = []
    infra: dict[str, int] = {}
    stig_fleet = build_stig_fleet_view(
        aggregated_hosts,
        ctx=ctx,
        registry=reg,
        cklb_dir=cklb_dir,
    )

    site_entries = reg.site_dashboard_entries()

    host_report_dirs: dict[str, str] = {}
    hosts_per_audit_key: dict[str, int] = {}
    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for entry in site_entries:
            audit_key = entry.site_audit_key
            if not audit_key:
                continue
            audit = _get_schema_audit(bundle, audit_key)
            if not audit:
                continue
            hosts_per_audit_key[audit_key] = hosts_per_audit_key.get(audit_key, 0) + 1
            if hostname not in host_report_dirs:
                host_report_dirs[hostname] = entry.report_dir

            display = entry.display_name or entry.platform.capitalize()
            category = display
            audit_type_key = f"schema_{audit_key}"
            alerts_list = safe_list(audit.get("alerts"))
            status = _status_from_health(audit.get("health"))

            _f = audit.get("fields") or {}
            for k, v in _f.items():
                if k.endswith("_count") and isinstance(v, (int, float)):
                    infra[k] = infra.get(k, 0) + int(v)

            all_alerts.extend(
                extract_platform_alerts(alerts_list, hostname, audit_type_key, category, platform_label=display)
            )
            if not alerts_list and status in ("CRITICAL", "WARNING"):
                all_alerts.append(
                    {
                        "severity": status,
                        "host": hostname,
                        "audit_type": audit_type_key,
                        "platform": display,
                        "category": category,
                        "message": f"{display} reported {status} health status.",
                    }
                )

    # Build alert_groups: one entry per host, hosts with CRITICAL first
    _host_order: list[str] = []
    _host_groups: dict[str, dict[str, Any]] = {}
    for alert in sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))):
        host = str(alert.get("host", ""))
        if host not in _host_groups:
            _host_order.append(host)
            _host_groups[host] = {
                "host": host,
                "node_report": f"{_PDP}/{host_report_dirs[host]}/{host}/{_FHR}" if host in host_report_dirs else "",
                "platform": alert.get("platform", ""),
                "worst_severity": alert.get("severity", ""),
                "alerts": [],
            }
        _host_groups[host]["alerts"].append(
            {"severity": alert["severity"], "message": alert.get("message", ""), "category": alert.get("category", "")}
        )
    alert_groups = [_host_groups[h] for h in _host_order]

    totals = _count_alerts(all_alerts)

    # Build platforms dict and nav tree dynamically from registry
    platforms_dict: dict[str, dict[str, Any]] = {}
    site_entries_with_assets: list[dict[str, Any]] = []

    for entry in site_entries:
        p_name = entry.platform
        audit_key = entry.site_audit_key or p_name
        display = entry.display_name or p_name.capitalize()
        fleet_link = entry.fleet_link or fleet_link_url(entry.report_dir, audit_key)
        asset_count = hosts_per_audit_key.get(audit_key, 0)
        audit_type_key = f"schema_{audit_key}"
        p_counts = _count_alerts([a for a in all_alerts if a.get("audit_type") == audit_type_key])
        p_status = aggregate_platform_status(all_alerts, audit_type_key)

        platform_data: dict[str, Any] = {
            "display_name": display,
            "asset_count": asset_count,
            "alert_count": p_counts["total"],
            "status": {"raw": p_status},
            "links": {"fleet_dashboard": fleet_link},
        }
        # Only include platforms that have generated reports
        has_reports = generated_fleet_dirs is None or entry.report_dir in generated_fleet_dirs
        if has_reports:
            platforms_dict[audit_key] = platform_data

        if to_int(asset_count) > 0 and has_reports:
            site_entries_with_assets.append({"display_name": display, "fleet_link": fleet_link})

    # Build nav using NavBuilder
    from .nav_builder import NavBuilder
    nav_builder = NavBuilder(
        reg,
        generated_fleet_dirs=generated_fleet_dirs,
        has_stig_fleet=bool(stig_fleet.get("rows")),
    )
    site_nav = nav_builder.build_for_site(
        site_entries_with_assets,
        has_stig_rows=bool(stig_fleet.get("rows")),
    )

    return {
        "meta": build_meta(ctx),
        "totals": totals,
        "nav": site_nav,
        "alerts": sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))),
        "alert_groups": alert_groups,
        "infra": infra,
        "platforms": platforms_dict,
        "security": {
            "stig_fleet": stig_fleet,
        },
    }
