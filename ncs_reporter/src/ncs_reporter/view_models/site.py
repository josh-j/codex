"""Site dashboard reporting view-model builders."""

from typing import Any

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
from ..pathing import render_template


def _get_schema_audit(bundle: dict[str, Any], *names: str) -> dict[str, Any] | None:
    """Return the first matching schema audit from a host bundle.

    Checks ``schema_<name>`` keys in preference order, then legacy key aliases
    from the platform registry.
    """
    from ..platform_registry import default_registry
    reg = default_registry()
    for name in names:
        audit = bundle.get(f"schema_{name}")
        if audit:
            return dict(audit)
        legacy = reg.legacy_audit_key_for(name)
        if legacy:
            audit = bundle.get(legacy)
            if audit:
                return dict(audit)
    return None


def _build_platform_links(
    platforms_config: list[dict[str, Any]] | None,
    report_stamp: str | None,
) -> dict[str, str]:
    """Build a mapping of platform name → fleet report relative path from config.

    Returns e.g. {"linux": "platform/linux/ubuntu/linux_fleet_report.html", ...}
    """
    links: dict[str, str] = {}
    for p in platforms_config or []:
        paths = p.get("paths") or {}
        tpl = paths.get("report_fleet", "")
        report_dir = p.get("report_dir", "")
        if not tpl or not report_dir:
            continue
        link = render_template(
            tpl,
            report_dir=report_dir,
            schema_name=p.get("schema_name") or p.get("platform") or "",
            hostname="",
            target_type="",
            report_stamp=report_stamp or "",
        )
        # Only store the first (most specific) entry per platform key
        platform_key = p.get("platform", "")
        if platform_key and platform_key not in links:
            links[platform_key] = link
    return links


def build_site_dashboard_view(
    aggregated_hosts: dict[str, Any],
    inventory_groups: dict[str, Any] | None = None,
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    registry: PlatformRegistry | None = None,
    cklb_dir: Any = None,
) -> dict[str, Any]:
    from ncs_reporter.models.platforms_config import (
        FILENAME_HEALTH_REPORT as _FHR,
        PLATFORM_DIR_PREFIX as _PDP,
        fleet_link_url,
    )
    reg = registry or default_registry()
    groups = dict(inventory_groups or {})
    all_alerts: list[dict[str, Any]] = []
    compute_nodes: list[dict[str, Any]] = []
    infra: dict[str, int] = {}
    stig_fleet = build_stig_fleet_view(
        aggregated_hosts,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
        registry=reg,
        cklb_dir=cklb_dir,
    )

    site_entries = reg.site_dashboard_entries()

    host_report_dirs: dict[str, str] = {}
    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for entry in site_entries:
            audit_key = entry.site_audit_key
            if not audit_key:
                continue
            audit = _get_schema_audit(bundle, audit_key)
            if not audit:
                continue
            if hostname not in host_report_dirs:
                host_report_dirs[hostname] = entry.report_dir

            display = entry.display_name or entry.platform.capitalize()
            category = entry.site_category or display
            audit_type_key = f"schema_{audit_key}"
            alerts_list = safe_list(audit.get("alerts"))
            status = _status_from_health(audit.get("health"))

            # Compute nodes and infra totals (driven by platform config)
            if entry.site_compute_node:
                cn_counts = _count_alerts(alerts_list)
                if cn_counts["total"] or audit.get("health"):
                    fleet_link = entry.fleet_link or fleet_link_url(entry.report_dir, audit_key)
                    compute_nodes.append(
                        {
                            "host": hostname,
                            "status": {"raw": status},
                            "clusters": [],
                            "links": {"fleet_dashboard": fleet_link},
                        }
                    )
                _f = audit.get("fields") or {}
                for infra_field in entry.site_infra_fields:
                    infra[infra_field] = infra.get(infra_field, 0) + int(_f.get(infra_field) or 0)

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
        asset_label = entry.asset_label
        fleet_link = entry.fleet_link or fleet_link_url(entry.report_dir, audit_key)
        asset_count = to_int(reg.count_inventory_assets(entry, groups))
        audit_type_key = f"schema_{audit_key}"
        p_counts = _count_alerts([a for a in all_alerts if a.get("audit_type") == audit_type_key])
        p_status = aggregate_platform_status(all_alerts, audit_type_key)

        platform_data: dict[str, Any] = {
            "display_name": display,
            "asset_count": asset_count,
            "asset_label": asset_label,
            "alert_count": p_counts["total"],
            "status": {"raw": p_status},
            "links": {"fleet_dashboard": fleet_link},
        }
        # Infra-specific fields (driven by platform config)
        if entry.site_infra_fields:
            for infra_field in entry.site_infra_fields:
                if infra_field in infra:
                    platform_data[infra_field] = infra[infra_field]

        platforms_dict[p_name] = platform_data

        if to_int(asset_count) > 0:
            site_entries_with_assets.append({"display_name": display, "fleet_link": fleet_link})

    # Build nav using NavBuilder
    from .nav_builder import NavBuilder
    nav_builder = NavBuilder(reg, has_stig_fleet=bool(stig_fleet.get("rows")))
    site_nav = nav_builder.build_for_site(
        site_entries_with_assets,
        has_stig_rows=bool(stig_fleet.get("rows")),
    )

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "totals": totals,
        "nav": site_nav,
        "alerts": sorted(all_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))),
        "alert_groups": alert_groups,
        "infra": infra,
        "platforms": platforms_dict,
        "security": {
            "stig_fleet": stig_fleet,
        },
        "compute": {
            "nodes": compute_nodes,
        },
    }
