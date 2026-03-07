"""Generic schema-driven view model builders."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ncs_reporter.models.report_schema import (
    AlertPanelWidget,
    BarChartWidget,
    GroupedTableWidget,
    KeyValueWidget,
    ListWidget,
    MarkdownWidget,
    ProgressBarWidget,
    ReportSchema,
    StatCardsWidget,
    TableWidget,
)
from ncs_reporter.normalization.schema_driven import evaluate_condition, normalize_from_schema
from ncs_reporter.view_models.common import _count_alerts, _iter_hosts, fleet_entry_for_dir, status_badge_meta


def _format_value(fmt: str | None, value: Any) -> str:
    """Apply a format string to a value, returning str(value) on failure or no format."""
    if not fmt:
        return str(value)
    try:
        if "{value" in fmt:
            return fmt.format(value=value)
        return fmt.replace("{value}", str(value))
    except (ValueError, KeyError, TypeError):
        return str(value)


def _resolve_threshold_color(
    value: float, thresholds: dict[int, str] | None, default_color: str = "blue"
) -> str:
    """Resolve a color name from sorted thresholds. Returns default_color if no thresholds."""
    if not thresholds:
        return default_color
    sorted_thresh = sorted([(int(k), v) for k, v in thresholds.items()])
    color = "green"
    for thresh_val, c_name in sorted_thresh:
        if value >= thresh_val:
            color = c_name
    return color


def _render_table_cell(
    col: Any,
    item: dict[str, Any],
    hosts_data: dict[str, Any] | None = None,
    current_platform_dir: str | None = None,
    generated_fleet_dirs: set[str] | None = None,
) -> dict[str, Any]:
    """Render a single table cell from a TableColumn and row item."""
    if "." in col.field:
        parts = col.field.split(".")
        value: Any = item
        for p in parts:
            if isinstance(value, dict):
                value = value.get(p, "")
            else:
                value = ""
                break
    else:
        value = item.get(col.field, "")
    link = None
    cell_class = ""

    if col.style_rules:
        temp_ctx = {col.field: value}
        if isinstance(item, dict):
            temp_ctx.update(item)
        for rule in col.style_rules:
            if evaluate_condition(rule.condition, temp_ctx):
                cell_class = rule.css_class
                break

    if col.link_field and hosts_data:
        link_val = str(item.get(col.link_field) or "")
        if link_val in hosts_data:
            target_platform = hosts_data[link_val]
            if generated_fleet_dirs is not None and target_platform not in generated_fleet_dirs:
                target_platform = ""
            if target_platform:
                depth = len(current_platform_dir.split("/")) + 1 if current_platform_dir else 2
                back_to_root = "../" * (depth + 1)
                link = f"{back_to_root}platform/{target_platform}/{link_val}/health_report.html"

    rendered_value = _format_value(col.format, value) if col.format else value

    return {"value": rendered_value, "badge": col.badge, "link": link, "css_class": cell_class}


# Widget types that are compact enough to sit side-by-side at half width
_COMPACT_WIDGET_TYPES = (KeyValueWidget, StatCardsWidget, ProgressBarWidget, ListWidget, BarChartWidget)

# Tables with this many columns or fewer auto-size to half width
_TABLE_HALF_WIDTH_MAX_COLS = 4


def _auto_layout(widget: Any) -> dict[str, Any]:
    """Return layout dict, auto-sizing compact widgets to half when no explicit width was set."""
    layout = widget.layout.model_dump() if hasattr(widget, "layout") else {"width": "full"}
    if widget.layout.model_fields_set.intersection({"width"}):
        return layout
    if isinstance(widget, _COMPACT_WIDGET_TYPES):
        layout["width"] = "half"
    elif isinstance(widget, (TableWidget, GroupedTableWidget)) and len(widget.columns) <= _TABLE_HALF_WIDTH_MAX_COLS:
        layout["width"] = "half"
    return layout


def _render_widget(
    widget: Any,
    fields: dict[str, Any],
    alerts: list[dict[str, Any]],
    hosts_data: dict[str, Any] | None = None,
    current_platform_dir: str | None = None,
    generated_fleet_dirs: set[str] | None = None,
) -> dict[str, Any] | None:
    """Render a single schema widget into a template-ready dict. Returns None if hidden by visible_if."""
    # visible_if guard
    if hasattr(widget, "visible_if") and widget.visible_if is not None:
        if not evaluate_condition(widget.visible_if, fields):
            return None

    if isinstance(widget, KeyValueWidget):
        rows = []
        for kv in widget.fields:
            value = fields.get(kv.field, "")
            rows.append({"label": kv.label, "value": _format_value(kv.format, value), "badge": kv.badge})
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "key_value",
            "layout": _auto_layout(widget),
            "rows": rows,
        }

    if isinstance(widget, TableWidget):
        raw_rows = fields.get(widget.rows_field, [])
        if not isinstance(raw_rows, list):
            raw_rows = []
        table_rows = []
        for item in raw_rows:
            if not isinstance(item, dict):
                item = {"value": item}
            rendered_cells = [
                _render_table_cell(col, item, hosts_data, current_platform_dir, generated_fleet_dirs)
                for col in widget.columns
            ]
            table_rows.append(rendered_cells)
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "table",
            "layout": _auto_layout(widget),
            "columns": [c.model_dump() for c in widget.columns],
            "rows": table_rows,
        }

    if isinstance(widget, ProgressBarWidget):
        value = fields.get(widget.field, 0.0)
        try:
            pct = max(0, min(100, float(value)))
        except (ValueError, TypeError):
            pct = 0.0

        label_text = ""
        if widget.label:
            label_text = str(fields.get(widget.label, ""))

        color: str = widget.color
        if color == "auto":
            color = _resolve_threshold_color(pct, widget.thresholds)

        return {
            "id": widget.id,
            "title": widget.title,
            "type": "progress_bar",
            "layout": _auto_layout(widget),
            "percent": pct,
            "label": label_text,
            "color": color,
        }

    if isinstance(widget, MarkdownWidget):
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "markdown",
            "layout": _auto_layout(widget),
            "content": widget.content,
        }

    if isinstance(widget, AlertPanelWidget):
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "alert_panel",
            "layout": _auto_layout(widget),
            "alerts": alerts,
        }

    if isinstance(widget, StatCardsWidget):
        cards_rendered = []
        for card in widget.cards:
            value = fields.get(card.field, 0)
            display = _format_value(card.format, value)

            resolved_color: str = card.color
            if resolved_color == "auto":
                try:
                    num_val = float(value)
                except (ValueError, TypeError):
                    num_val = 0.0
                resolved_color = _resolve_threshold_color(num_val, card.thresholds)

            cards_rendered.append({"label": card.label, "value": display, "color": resolved_color})
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "stat_cards",
            "layout": _auto_layout(widget),
            "cards": cards_rendered,
        }

    if isinstance(widget, BarChartWidget):
        raw_rows = fields.get(widget.rows_field, [])
        if not isinstance(raw_rows, list):
            raw_rows = []
        bars = []
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            label = str(item.get(widget.label_field, ""))
            try:
                val = float(item.get(widget.value_field, 0))
            except (ValueError, TypeError):
                val = 0.0
            width_pct = min(100.0, max(0.0, val / widget.max * 100)) if widget.max else 0.0
            color = _resolve_threshold_color(val, widget.thresholds)
            bars.append({"label": label, "value": val, "width_pct": width_pct, "color": color})
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "bar_chart",
            "layout": _auto_layout(widget),
            "bars": bars,
        }

    if isinstance(widget, ListWidget):
        raw_items = fields.get(widget.items_field, [])
        if not isinstance(raw_items, list):
            raw_items = []
        display_items = []
        for item in raw_items:
            if widget.display_field and isinstance(item, dict):
                display_items.append(str(item.get(widget.display_field, "")))
            else:
                display_items.append(str(item))
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "list",
            "layout": _auto_layout(widget),
            "items": display_items,
            "style": widget.style,
            "empty_text": widget.empty_text,
        }

    if isinstance(widget, GroupedTableWidget):
        raw_rows = fields.get(widget.rows_field, [])
        if not isinstance(raw_rows, list):
            raw_rows = []
        # Group by the group_by field, preserving insertion order
        groups: dict[str, list[list[dict[str, Any]]]] = {}
        for item in raw_rows:
            if not isinstance(item, dict):
                item = {"value": item}
            group_key = str(item.get(widget.group_by, ""))
            if group_key not in groups:
                groups[group_key] = []
            rendered_cells = [
                _render_table_cell(col, item, hosts_data, current_platform_dir, generated_fleet_dirs)
                for col in widget.columns
            ]
            groups[group_key].append(rendered_cells)
        return {
            "id": widget.id,
            "title": widget.title,
            "type": "grouped_table",
            "layout": _auto_layout(widget),
            "columns": [c.model_dump() for c in widget.columns],
            "groups": groups,
        }

    layout_val = {"width": "full"}
    if hasattr(widget, "layout"):
        lo = getattr(widget, "layout")
        if hasattr(lo, "model_dump"):
            layout_val = lo.model_dump()

    return {
        "id": getattr(widget, "id", ""),
        "title": getattr(widget, "title", ""),
        "type": "unknown",
        "layout": layout_val,
    }


def build_generic_node_view(
    schema: ReportSchema,
    hostname: str,
    bundle: dict[str, Any],
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: Mapping[str, Any] | None = None,
    hosts_data: dict[str, Any] | None = None,
    generated_fleet_dirs: set[str] | None = None,
    has_stig_fleet: bool = False,
    history: list[dict[str, str]] | None = None,
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
        rendered
        for w in schema.widgets
        if (
            rendered := _render_widget(
                w,
                fields,
                alerts,
                hosts_data=hosts_data,
                current_platform_dir=current_plt_dir,
                generated_fleet_dirs=generated_fleet_dirs,
            )
        )
        is not None
    ]

    # Build nav tree information if possible
    nav_with_tree = {**nav} if nav else {}
    if history:
        nav_with_tree["history"] = history
        
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
        if generated_fleet_dirs is not None:
            p_dirs = [d for d in p_dirs if d in generated_fleet_dirs]

        for plt_dir in p_dirs:
            label, schema_name = fleet_entry_for_dir(plt_dir)
            fleets.append(
                {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"}
            )

        # Add STIG fleet (only if it will be generated)
        if has_stig_fleet:
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
    generated_fleet_dirs: set[str] | None = None,
    has_stig_fleet: bool = False,
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
            if generated_fleet_dirs is not None:
                p_dirs = [d for d in p_dirs if d in generated_fleet_dirs]
            for plt_dir in p_dirs:
                label, schema_name = fleet_entry_for_dir(plt_dir)
                fleets.append(
                    {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"}
                )

            # Add STIG fleet (only if it will be generated)
            if has_stig_fleet:
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
