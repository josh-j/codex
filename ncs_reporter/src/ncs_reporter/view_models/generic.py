"""Generic schema-driven view model builders."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ncs_reporter.models.report_schema import (
    AlertPanelWidget,
    KeyValueWidget,
    ReportSchema,
    TableWidget,
)
from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.view_models.common import _count_alerts, _iter_hosts, status_badge_meta


def _render_widget(
    widget: Any,
    fields: dict[str, Any],
    alerts: list[dict[str, Any]],
    hosts_data: dict[str, Any] | None = None,
    current_platform_dir: str | None = None,
) -> dict[str, Any]:
    """Render a single schema widget into a template-ready dict."""
    if isinstance(widget, KeyValueWidget):
        rows = []
        for kv in widget.fields:
            value = fields.get(kv.field, "")
            if kv.format:
                try:
                    # Support both old-style .replace and new-style .format with specifiers (e.g. {value:.1f})
                    if "{value" in kv.format:
                        label_str = kv.format.format(value=value)
                    else:
                        label_str = kv.format.replace("{value}", str(value))
                except (ValueError, KeyError, TypeError):
                    label_str = str(value)
            else:
                label_str = str(value)
            rows.append({"label": kv.label, "value": label_str})
        return {"id": widget.id, "title": widget.title, "type": "key_value", "rows": rows}

    if isinstance(widget, TableWidget):
        raw_rows = fields.get(widget.rows_field, [])
        if not isinstance(raw_rows, list):
            raw_rows = []
        table_rows = []
        for item in raw_rows:
            if not isinstance(item, dict):
                item = {"value": item}
            rendered_cells = []
            for col in widget.columns:
                value = item.get(col.field, "")
                link = None

                # Resolve link if specified
                if col.link_field and hosts_data:
                    link_val = str(item.get(col.link_field) or "")
                    if link_val in hosts_data:
                        # link_val is the hostname, hosts_data[link_val] is the platform directory
                        target_platform = hosts_data[link_val]
                        # Calculate steps back to 'platform' root
                        depth = len(current_platform_dir.split("/")) + 1 if current_platform_dir else 2
                        back_to_root = "../" * (depth + 1)
                        link = f"{back_to_root}platform/{target_platform}/{link_val}/health_report.html"

                if col.format:
                    try:
                        if "{value" in col.format:
                            rendered_value = col.format.format(value=value)
                        else:
                            rendered_value = col.format.replace("{value}", str(value))
                    except (ValueError, KeyError, TypeError):
                        rendered_value = str(value)
                else:
                    rendered_value = value

                rendered_cells.append({"value": rendered_value, "badge": col.badge, "link": link})
            table_rows.append(rendered_cells)
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "table",
            "columns": [c.model_dump() for c in widget.columns],
            "rows": table_rows,
        }

    if isinstance(widget, AlertPanelWidget):
        return {"id": widget.id, "title": widget.title, "type": "alert_panel", "alerts": alerts}

    return {"id": getattr(widget, "id", ""), "title": getattr(widget, "title", ""), "type": "unknown"}


def build_generic_node_view(
    schema: ReportSchema,
    hostname: str,
    bundle: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: Mapping[str, Any] | None = None,
    hosts_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a single host report."""
    normalized = normalize_from_schema(schema, bundle)
    fields = normalized["fields"]
    alerts = normalized["alerts"]
    # Sort alerts by severity (CRITICAL first)
    alerts.sort(key=lambda a: (a.get("severity") != "CRITICAL", a.get("category", ""), a.get("message", "")))

    health = normalized["health"]
    summary = normalized["summary"]

    # siblings in the same platform (as indexed in hosts_data)
    current_plt_dir = hosts_data.get(hostname) if hosts_data else None
    widgets_rendered = [
        _render_widget(w, fields, alerts, hosts_data=hosts_data, current_platform_dir=current_plt_dir)
        for w in schema.widgets
    ]

    # Build nav tree information if possible
    nav_with_tree = {**nav} if nav else {}
    if hosts_data and hostname in hosts_data:
        current_plt_dir = hosts_data[hostname]
        depth = len(current_plt_dir.split("/")) + 1
        back_to_root = "../" * (depth + 1)

        siblings = []
        for h, plt_dir in hosts_data.items():
            if plt_dir == current_plt_dir:
                siblings.append({"name": h, "report": f"../{h}/health_report.html" if h != hostname else "#"})
        siblings.sort(key=lambda x: x["name"])
        nav_with_tree["tree_siblings"] = siblings

        # fleets
        fleets = []
        p_dirs = sorted(list(set(hosts_data.values())))

        for plt_dir in p_dirs:
            # Map directory/internal names to labels and schema names
            if "vcenter" in plt_dir:
                label = "VMware"
                schema_name = "vcenter"
            elif "ubuntu" in plt_dir:
                label = "Linux"
                schema_name = "linux"
            else:
                label = plt_dir.split("/")[-1].capitalize()
                schema_name = plt_dir.split("/")[-1]

            fleets.append(
                {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"}
            )

        # Add STIG fleet
        fleets.append({"name": "STIG", "report": f"{back_to_root}stig_fleet_report.html"})
        nav_with_tree["tree_fleets"] = fleets

    return {
        "meta": {
            "host": hostname,
            "display_name": schema.display_name,
            "platform": schema.platform,
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "nav": nav_with_tree,
        "health": health,
        "health_badge": status_badge_meta(health),
        "summary": summary,
        "alerts": alerts,
        "fields": fields,
        "widgets": widgets_rendered,
    }


def build_generic_fleet_view(
    schema: ReportSchema,
    aggregated_hosts: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: Mapping[str, Any] | None = None,
    hosts_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a fleet-level report."""
    schema_key = f"schema_{schema.name}"
    host_rows: list[dict[str, Any]] = []
    fleet_alerts: list[dict[str, Any]] = []

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        # Use pre-normalized data if present, otherwise normalize on the fly
        node_data = bundle.get(schema_key)
        if not isinstance(node_data, dict):
            node_data = normalize_from_schema(schema, bundle)

        health = node_data.get("health", "UNKNOWN")
        alerts = node_data.get("alerts", [])
        summary = node_data.get("summary", {})
        fields = node_data.get("fields", {})
        counts = _count_alerts(alerts)

        for alert in alerts:
            fleet_alerts.append({**alert, "host": hostname})

        row = {
            "hostname": hostname,
            "node_report": f"{hostname}/health_report.html",
            "health": health,
            "health_badge": status_badge_meta(health),
            "critical_count": counts["critical"],
            "warning_count": counts["warning"],
            "total_alerts": counts["total"],
            "summary": summary,
            "fields": fields,
        }
        # Add quick access for schema-driven columns
        for col in schema.fleet_columns:
            row[f"col_{col.field}"] = fields.get(col.field, "")

        host_rows.append(row)

    host_rows.sort(key=lambda r: r["hostname"])

    # Group fleet alerts by host, similar to the site report logic
    _host_order: list[str] = []
    _host_groups: dict[str, dict[str, Any]] = {}

    # Only process WARNING/CRITICAL
    queued_alerts = [a for a in fleet_alerts if a.get("severity") in ("CRITICAL", "WARNING")]

    for alert in sorted(queued_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))):
        host = str(alert.get("host", ""))
        if host not in _host_groups:
            _host_order.append(host)
            _host_groups[host] = {
                "host": host,
                "platform": schema.display_name,
                "worst_severity": alert.get("severity", ""),
                "alerts": [],
            }
        _host_groups[host]["alerts"].append(
            {"severity": alert["severity"], "message": alert.get("message", ""), "category": alert.get("category", "")}
        )

    alert_groups = [_host_groups[h] for h in _host_order]
    totals = _count_alerts(queued_alerts)

    # Build fleets list for breadcrumb tree if site index is available
    nav_with_tree = {**nav} if nav else {}
    if hosts_data:
        # fleets
        current_plt_dir = hosts_data.get(next(iter(aggregated_hosts.keys()), "")) if aggregated_hosts else None
        if current_plt_dir:
            depth = len(current_plt_dir.split("/"))
            back_to_root = "../" * (depth + 1)

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
                    label = plt_dir.split("/")[-1].capitalize()
                    schema_name = plt_dir.split("/")[-1]

                fleets.append(
                    {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"}
                )

            # Add STIG fleet
            fleets.append({"name": "STIG", "report": f"{back_to_root}stig_fleet_report.html"})
            nav_with_tree["tree_fleets"] = fleets

    return {
        "meta": {
            "display_name": schema.display_name,
            "platform": schema.platform,
            "total_hosts": len(host_rows),
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "nav": nav_with_tree,
        "fleet_columns": [c.model_dump() for c in schema.fleet_columns],
        "hosts": host_rows,
        "active_alerts": queued_alerts,
        "alert_groups": alert_groups,
        "crit_count": totals["critical"],
        "warn_count": totals.get("warning", 0),
    }
