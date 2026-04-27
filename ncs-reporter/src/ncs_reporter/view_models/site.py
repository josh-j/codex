"""Site dashboard reporting view-model builders."""

from __future__ import annotations

from typing import Any

from .._report_context import ReportContext
from ..constants import FLEET_ALERT_SEVERITIES
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


_STATUS_RANK = {"CRITICAL": 3, "WARNING": 2, "OK": 1, "UNKNOWN": 0}


def _merge_status(a: str, b: str) -> str:
    """Return whichever of *a* / *b* is the worse health status."""
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b



def build_site_dashboard_view(
    aggregated_hosts: dict[str, Any],
    *,
    ctx: ReportContext | None = None,
    registry: PlatformRegistry | None = None,
    cklb_dir: Any = None,
    generated_fleet_dirs: set[str] | None = None,
    tree_host_urls: dict[str, str] | None = None,
    tree_products: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    from ncs_reporter.models.platforms_config import fleet_link_url, host_report_url
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
    tree_host_urls = tree_host_urls or {}

    host_report_dirs: dict[str, str] = {}
    hosts_per_audit_key: dict[str, int] = {}
    hostnames_per_audit_key: dict[str, list[str]] = {}
    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for entry in site_entries:
            audit_key = entry.site_audit_key
            if not audit_key:
                continue
            audit = _get_schema_audit(bundle, audit_key)
            if not audit:
                continue
            hosts_per_audit_key[audit_key] = hosts_per_audit_key.get(audit_key, 0) + 1
            hostnames_per_audit_key.setdefault(audit_key, []).append(hostname)
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
            if not alerts_list and status in FLEET_ALERT_SEVERITIES:
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
                "node_report": (
                    tree_host_urls.get(host)
                    or (host_report_url(host_report_dirs[host], host) if host in host_report_dirs else "")
                ),
                "platform": alert.get("platform", ""),
                "worst_severity": alert.get("severity", ""),
                "alerts": [],
            }
        _host_groups[host]["alerts"].append(
            {
                "severity": alert["severity"],
                "message": alert.get("message", ""),
                "category": alert.get("category", ""),
                "detail": alert.get("detail", {}),
                "affected_items": alert.get("affected_items", []),
            }
        )
    alert_groups = [_host_groups[h] for h in _host_order]

    totals = _count_alerts(all_alerts)

    # Per-schema entries that resolve to the same tree URL collapse into
    # one row keyed by tree slug, with summed asset/alert counts.
    platforms_dict: dict[str, dict[str, Any]] = {}
    tree_title_by_slug: dict[str, str] = {p["slug"]: p["name"] for p in (tree_products or [])}
    site_entries_with_assets: list[dict[str, Any]] = []

    def _tree_platform_url(audit_key: str) -> str | None:
        """Tree URL for the platform overview, derived from the first
        segment of any host's tree URL (``vsphere/vc-x/.../h.html`` →
        ``vsphere/vsphere.html``). None when no host has a tree URL."""
        for host in hostnames_per_audit_key.get(audit_key, []):
            url = tree_host_urls.get(host)
            if url and "/" in url:
                slug = url.split("/", 1)[0]
                return f"{slug}/{slug}.html"
        return None

    for entry in site_entries:
        p_name = entry.platform
        audit_key = entry.site_audit_key or p_name
        display = entry.display_name or p_name.capitalize()
        fleet_link = (
            _tree_platform_url(audit_key)
            or entry.fleet_link
            or fleet_link_url(entry.report_dir, audit_key)
        )
        asset_count = hosts_per_audit_key.get(audit_key, 0)
        audit_type_key = f"schema_{audit_key}"
        p_counts = _count_alerts([a for a in all_alerts if a.get("audit_type") == audit_type_key])
        p_status = aggregate_platform_status(all_alerts, audit_type_key)

        if to_int(asset_count) <= 0 and to_int(p_counts["total"]) <= 0:
            continue

        group_key = audit_key
        merged_display = display
        if fleet_link and "/" in fleet_link:
            slug = fleet_link.split("/", 1)[0]
            if slug in tree_title_by_slug:
                group_key = slug
                merged_display = tree_title_by_slug[slug]

        existing = platforms_dict.get(group_key)
        if existing is None:
            platforms_dict[group_key] = {
                "display_name": merged_display,
                "asset_count": asset_count,
                "alert_count": p_counts["total"],
                "status": {"raw": p_status},
                "links": {"fleet_dashboard": fleet_link},
            }
        else:
            existing["asset_count"] = to_int(existing.get("asset_count", 0)) + asset_count
            existing["alert_count"] = to_int(existing.get("alert_count", 0)) + p_counts["total"]
            # Worst status wins for the merged row.
            existing["status"]["raw"] = _merge_status(existing["status"]["raw"], p_status)
            existing["display_name"] = merged_display

        if to_int(asset_count) > 0:
            # Dedupe by fleet_link so the Select Product dropdown shows
            # one entry per tree.
            if not any(e["fleet_link"] == fleet_link for e in site_entries_with_assets):
                site_entries_with_assets.append({"display_name": merged_display, "fleet_link": fleet_link})

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
