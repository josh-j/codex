"""Generic schema-driven view model builders."""

from __future__ import annotations

from typing import Any

from ncs_reporter.models.report_schema import (
    AlertPanelSection,
    KeyValueSection,
    ReportSchema,
    TableSection,
)
from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.view_models.common import _count_alerts, _iter_hosts, status_badge_meta


def _render_section(section: Any, fields: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Render a single schema section into a template-ready dict."""
    if isinstance(section, KeyValueSection):
        rows = []
        for kv in section.fields:
            value = fields.get(kv.field, "")
            label_str = kv.format.replace("{value}", str(value)) if kv.format else str(value)
            rows.append({"label": kv.label, "value": label_str})
        return {"id": section.id, "title": section.title, "type": "key_value", "rows": rows}

    if isinstance(section, TableSection):
        raw_rows = fields.get(section.rows_field, [])
        if not isinstance(raw_rows, list):
            raw_rows = []
        table_rows = []
        for item in raw_rows:
            if not isinstance(item, dict):
                item = {"value": item}
            rendered_cols = []
            for col in section.columns:
                cell_value = item.get(col.field, "")
                rendered_cols.append({
                    "label": col.label,
                    "value": cell_value,
                    "badge": col.badge,
                })
            table_rows.append(rendered_cols)
        return {
            "id": section.id,
            "title": section.title,
            "type": "table",
            "columns": [{"label": c.label, "badge": c.badge} for c in section.columns],
            "rows": table_rows,
        }

    if isinstance(section, AlertPanelSection):
        return {"id": section.id, "title": section.title, "type": "alert_panel", "alerts": alerts}

    return {"id": getattr(section, "id", ""), "title": getattr(section, "title", ""), "type": "unknown"}


def build_generic_node_view(
    schema: ReportSchema,
    hostname: str,
    bundle: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a single host report."""
    normalized = normalize_from_schema(schema, bundle)
    fields = normalized["fields"]
    alerts = normalized["alerts"]
    health = normalized["health"]
    summary = normalized["summary"]

    sections_rendered = [_render_section(s, fields, alerts) for s in schema.sections]

    return {
        "meta": {
            "host": hostname,
            "display_name": schema.display_name,
            "platform": schema.platform,
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "nav": nav or {},
        "health": health,
        "health_badge": status_badge_meta(health),
        "summary": summary,
        "alerts": alerts,
        "fields": fields,
        "sections": sections_rendered,
    }


def build_generic_fleet_view(
    schema: ReportSchema,
    aggregated_hosts: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: dict[str, str] | None = None,
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
        counts = _count_alerts(alerts)

        for alert in alerts:
            fleet_alerts.append({**alert, "host": hostname})

        host_rows.append({
            "hostname": hostname,
            "node_report": f"{hostname}/health_report.html",
            "health": health,
            "health_badge": status_badge_meta(health),
            "critical_count": counts["critical"],
            "warning_count": counts["warning"],
            "total_alerts": counts["total"],
            "summary": summary,
        })

    host_rows.sort(key=lambda r: r["hostname"])

    return {
        "meta": {
            "display_name": schema.display_name,
            "platform": schema.platform,
            "total_hosts": len(host_rows),
            "report_stamp": report_stamp,
            "report_date": report_date,
            "report_id": report_id,
        },
        "nav": nav or {},
        "hosts": host_rows,
        "active_alerts": [a for a in fleet_alerts if a.get("severity") in ("CRITICAL", "WARNING")],
    }
