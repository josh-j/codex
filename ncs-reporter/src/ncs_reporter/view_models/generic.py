"""Generic schema-driven view model builders."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ncs_reporter._report_context import ReportContext
from ncs_reporter.models.report_schema import (
    AlertPanelWidget,
    GroupedTableWidget,
    KeyValueWidget,
    MarkdownWidget,
    ProgressBarWidget,
    ReportSchema,
    ReportWidget,
    StatCardsWidget,
    TableWidget,
)
from ncs_reporter.constants import FLEET_ALERT_SEVERITIES
from ncs_reporter.normalization._when import evaluate_when
from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.view_models.common import GenericNavContext, _count_alerts, _iter_hosts, status_badge_meta

_SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _resolve_field_ref(field_ref: str, context: dict[str, Any]) -> Any:
    """Resolve a field reference — Jinja2 expression ({{ var }}) or bare field name."""
    if "{{" in field_ref:
        from ncs_reporter.normalization._when import _compile_template
        try:
            return _compile_template(field_ref).render(**context)
        except Exception:
            return ""
    # Bare field name — support dot-notation for nested access
    if "." in field_ref:
        obj: Any = context
        for part in field_ref.split("."):
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return ""
        return obj
    return context.get(field_ref, "")


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
    value: float, thresholds: Any | None, default_color: str = "blue"
) -> str:
    """Resolve a color from a ThresholdSpec. `crit_if_above` → red, `warn_if_above` → yellow, else green."""
    if thresholds is None:
        return default_color
    if thresholds.crit_if_above is not None and value >= thresholds.crit_if_above:
        return "red"
    if thresholds.warn_if_above is not None and value >= thresholds.warn_if_above:
        return "yellow"
    return "green"


def _render_table_cell(
    col: Any,
    item: dict[str, Any],
    hosts_data: dict[str, Any] | None = None,
    current_platform_dir: str | None = None,
    generated_fleet_dirs: set[str] | None = None,
) -> dict[str, Any]:
    """Render a single table cell from a TableColumn and row item."""
    value: Any = _resolve_field_ref(col.value, item)
    link = None
    cell_class = ""

    if col.style_rules:
        temp_ctx = {col.value: value}
        if isinstance(item, dict):
            temp_ctx.update(item)
        for rule in col.style_rules:
            if evaluate_when(rule.when, temp_ctx):
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
                from ncs_reporter.models.platforms_config import FILENAME_HEALTH_REPORT, PLATFORM_DIR_PREFIX
                link = f"{back_to_root}{PLATFORM_DIR_PREFIX}/{target_platform}/{link_val}/{FILENAME_HEALTH_REPORT}"

    rendered_value = _format_value(col.format, value) if col.format else value

    return {"value": rendered_value, "as": col.as_, "link": link, "css_class": cell_class}


# Widget types that are compact enough to sit side-by-side at half width
_COMPACT_WIDGET_TYPES = (KeyValueWidget, StatCardsWidget, ProgressBarWidget)

# Tables with this many columns or fewer auto-size to half width
_TABLE_HALF_WIDTH_MAX_COLS = 4


def _auto_layout(widget: ReportWidget) -> dict[str, Any]:
    """Return layout dict, auto-sizing compact widgets to half when no explicit width was set."""
    layout = widget.layout.model_dump() if hasattr(widget, "layout") else {"width": "full"}
    if widget.layout.model_fields_set.intersection({"width"}):
        return layout
    if isinstance(widget, _COMPACT_WIDGET_TYPES):
        layout["width"] = "half"
    elif isinstance(widget, (TableWidget, GroupedTableWidget)) and len(widget.columns) <= _TABLE_HALF_WIDTH_MAX_COLS:
        layout["width"] = "half"
    return layout


def _widget_base(widget: ReportWidget, **extra: Any) -> dict[str, Any]:
    """Build the base dict common to all widget renderings."""
    return {"slug": widget.slug, "name": widget.name, "type": widget.type, "layout": _auto_layout(widget), **extra}


def _safe_rows(fields: dict[str, Any], key: str) -> list[Any]:
    """Return field value as a list, or empty list if not a list.

    *key* may be a bare field name (``clusters``), a dot-path (``foo.bar``),
    or a Jinja expression (``{{ clusters }}``).
    """
    val = _resolve_field_ref(key, fields)
    return val if isinstance(val, list) else []


def _render_key_value(widget: KeyValueWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a KeyValueWidget."""
    rows = [
        {"name": kv.name, "value": _format_value(kv.format, _resolve_field_ref(kv.value, fields)), "as": kv.as_}
        for kv in widget.fields
    ]
    return _widget_base(widget, rows=rows)


def _render_row_cells(columns: list[Any], item: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Render all cells for a single table row."""
    hosts_data = ctx.get("hosts_data")
    platform_dir = ctx.get("current_platform_dir")
    fleet_dirs = ctx.get("generated_fleet_dirs")
    return [_render_table_cell(col, item, hosts_data, platform_dir, fleet_dirs) for col in columns]


def _render_table(widget: TableWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a TableWidget."""
    table_rows = []
    for item in _safe_rows(fields, widget.rows_field):
        if not isinstance(item, dict):
            item = {"value": item}
        table_rows.append(_render_row_cells(widget.columns, item, ctx))
    return _widget_base(widget, columns=[c.model_dump() for c in widget.columns], rows=table_rows)


def _render_progress_bar(widget: ProgressBarWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a ProgressBarWidget."""
    value = _resolve_field_ref(widget.value, fields)
    try:
        pct = max(0, min(100, float(value)))
    except (ValueError, TypeError):
        pct = 0.0

    label_text = ""
    if widget.value_label:
        label_text = str(_resolve_field_ref(widget.value_label, fields))

    color: str = widget.color
    if color == "auto":
        color = _resolve_threshold_color(pct, widget.thresholds)

    return _widget_base(widget, percent=pct, label=label_text, color=color)


def _render_markdown(widget: MarkdownWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a MarkdownWidget."""
    return _widget_base(widget, content=widget.content)


def _render_alert_panel(widget: AlertPanelWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render an AlertPanelWidget."""
    return _widget_base(widget, alerts=ctx.get("alerts", []))


def _render_stat_cards(widget: StatCardsWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a StatCardsWidget."""
    import re as _re
    field_specs = ctx.get("field_specs", {})
    cards_rendered = []
    for card in widget.cards:
        resolved = _resolve_field_ref(card.value, fields)
        display = _format_value(card.format, resolved) if card.format else str(resolved)

        # Look up thresholds: per-card first, then from var's FieldSpec
        thresholds = card.thresholds
        if thresholds is None:
            var_match = _re.search(r"\{\{\s*(\w+)", str(card.value))
            if var_match:
                spec = field_specs.get(var_match.group(1))
                if spec and hasattr(spec, "thresholds"):
                    thresholds = spec.thresholds

        resolved_color: str = card.color
        if resolved_color == "auto" and thresholds is not None:
            try:
                num_val = float(resolved)
            except (ValueError, TypeError):
                num_val = 0.0
            resolved_color = _resolve_threshold_color(num_val, thresholds)

        cards_rendered.append({"name": card.name, "value": display, "color": resolved_color})
    return _widget_base(widget, cards=cards_rendered)


def _render_grouped_table(widget: GroupedTableWidget, fields: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Render a GroupedTableWidget."""
    groups: dict[str, list[list[dict[str, Any]]]] = {}
    for item in _safe_rows(fields, widget.rows_field):
        if not isinstance(item, dict):
            item = {"value": item}
        group_key = str(item.get(widget.group_by, ""))
        groups.setdefault(group_key, []).append(_render_row_cells(widget.columns, item, ctx))
    return _widget_base(widget, columns=[c.model_dump() for c in widget.columns], groups=groups)


_WidgetHandler = Callable[[Any, dict[str, Any], dict[str, Any]], dict[str, Any]]

# Dispatch dictionary mapping widget classes to their render handlers.
_WIDGET_DISPATCH: dict[type, _WidgetHandler] = {
    KeyValueWidget: _render_key_value,
    TableWidget: _render_table,
    ProgressBarWidget: _render_progress_bar,
    MarkdownWidget: _render_markdown,
    AlertPanelWidget: _render_alert_panel,
    StatCardsWidget: _render_stat_cards,
    GroupedTableWidget: _render_grouped_table,
}


def _render_widget(
    widget: ReportWidget,
    fields: dict[str, Any],
    alerts: list[dict[str, Any]],
    hosts_data: dict[str, Any] | None = None,
    current_platform_dir: str | None = None,
    generated_fleet_dirs: set[str] | None = None,
    field_specs: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render a single schema widget into a template-ready dict. Returns None if hidden by when."""
    # when guard (conditional visibility)
    if hasattr(widget, "when") and widget.when is not None:
        if not evaluate_when(widget.when, fields):
            return None

    ctx: dict[str, Any] = {
        "alerts": alerts,
        "hosts_data": hosts_data,
        "current_platform_dir": current_platform_dir,
        "generated_fleet_dirs": generated_fleet_dirs,
        "field_specs": field_specs or {},
    }

    handler = _WIDGET_DISPATCH.get(type(widget))
    if handler is not None:
        return handler(widget, fields, ctx)

    # Fallback for unknown widget types
    return {"slug": widget.slug, "name": widget.name, "type": "unknown", "layout": _auto_layout(widget)}


# ---------------------------------------------------------------------------
# STIG widget helpers
# ---------------------------------------------------------------------------

def stig_view_to_node_widgets(
    stig_host_view: dict[str, Any],
    include_all_findings: bool = False,
) -> list[dict[str, Any]]:
    """Convert a stig_host_view dict into node widget dicts.

    Produces a ``stig_summary`` widget (half-width, always) and a
    ``stig_findings`` widget for open findings (when any exist).
    Optionally appends a full findings table when *include_all_findings* is True.

    The returned dicts are appended directly to ``node_view["widgets"]`` and
    rendered by the ``generic_node_report.html.j2`` template — they bypass
    ``_render_widget`` entirely since they are not schema-model instances.
    """
    target = stig_host_view.get("target", {})
    summary = stig_host_view.get("summary", {})
    by_status = summary.get("by_status", {})
    findings_summary = summary.get("findings", {})
    findings = stig_host_view.get("findings", [])

    label = (target.get("target_type") or "STIG").upper()
    # Stable slug for widget IDs — avoids TOC anchor collisions when multiple
    # STIG types (e.g. esxi + photon) are embedded on the same node report.
    slug = label.lower().replace(" ", "_")

    open_findings = [
        f for f in findings
        if str(f.get("status", "")).lower() in ("open", "fail", "non-compliant")
    ]

    widgets: list[dict[str, Any]] = [
        {
            "slug": f"stig-summary-{slug}",
            "name": f"{label} STIG — Evaluation Summary",
            "type": "stig_summary",
            "layout": {"width": "half"},
            "total": findings_summary.get("total", len(findings)),
            "by_status": by_status,
            "by_severity": {
                "critical": findings_summary.get("critical", 0),
                "warning": findings_summary.get("warning", 0),
                "info": findings_summary.get("info", 0),
            },
            # Preserve the link to the dedicated STIG host report when it exists
            "stig_report_url": stig_host_view.get("_report_url"),
        },
    ]

    if open_findings:
        widgets.append({
            "slug": f"stig-open-{slug}",
            "name": f"{label} STIG — Open Findings ({len(open_findings)})",
            "type": "stig_findings",
            "layout": {"width": "full"},
            "findings": open_findings,
        })

    if include_all_findings and findings:
        widgets.append({
            "slug": f"stig-all-{slug}",
            "name": f"{label} STIG — All Findings ({len(findings)})",
            "type": "stig_findings",
            "layout": {"width": "full"},
            "findings": findings,
        })

    return widgets


def merge_stig_into_node_view(
    node_view: dict[str, Any],
    stig_host_views: list[dict[str, Any]],
    include_all_findings: bool = False,
) -> None:
    """Append STIG widgets to an existing node_view in-place.

    Accepts a list so that hosts with multiple STIG audit types (e.g. a vCenter
    node that has both an ESXi STIG and a VCSA STIG) can all be embedded in a
    single pass.  Each view produces its own independently slugged widget group,
    so TOC anchors never collide.
    """
    widgets = node_view.setdefault("widgets", [])
    for stig_view in stig_host_views:
        widgets.extend(
            stig_view_to_node_widgets(stig_view, include_all_findings=include_all_findings)
        )


# ---------------------------------------------------------------------------
# Node + fleet view builders
# ---------------------------------------------------------------------------

def build_generic_node_view(
    schema: ReportSchema,
    hostname: str,
    bundle: dict[str, Any],
    *,
    ctx: ReportContext | None = None,
    nav_ctx: GenericNavContext | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a single host report."""
    nc = nav_ctx or GenericNavContext()
    normalized = normalize_from_schema(schema, bundle)
    fields = normalized["fields"]
    alerts = normalized["alerts"]
    alerts.sort(key=lambda a: (
        _SEVERITY_ORDER.get(a.get("severity", "INFO"), 3),
        a.get("category", ""),
        a.get("message", ""),
    ))

    health = normalized["health"]
    summary = normalized["summary"]

    # siblings in the same platform (as indexed in hosts_data)
    current_plt_dir = nc.hosts_data.get(hostname) if nc.hosts_data else None
    # Auto-inject alert panel as first widget if not declared
    effective_widgets: list[ReportWidget] = list(schema.widgets)
    if not any(isinstance(w, AlertPanelWidget) for w in effective_widgets):
        effective_widgets.insert(0, AlertPanelWidget(slug="active_alerts", name="Active Alerts", type="alert_panel"))

    widgets_rendered = [
        rendered
        for w in effective_widgets
        if (
            rendered := _render_widget(
                w,
                fields,
                alerts,
                hosts_data=nc.hosts_data,
                current_platform_dir=current_plt_dir,
                generated_fleet_dirs=nc.generated_fleet_dirs,
                field_specs=schema.fields,
            )
        )
        is not None
    ]

    # Build nav tree
    if nc.nav_builder is not None:
        nav_with_tree = nc.nav_builder.build_for_node(hostname, base_nav=nc.nav, history=nc.history)
    else:
        nav_with_tree = {**nc.nav} if nc.nav else {}
        if nc.history:
            nav_with_tree["history"] = nc.history

    rc = ctx or ReportContext()
    return {
        "meta": {
            "host": hostname,
            "display_name": schema.display_name,
            "platform": schema.platform,
            "report_stamp": rc.report_stamp,
            "report_date": rc.report_date,
            "report_id": rc.report_id,
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
    *,
    ctx: ReportContext | None = None,
    nav_ctx: GenericNavContext | None = None,
) -> dict[str, Any]:
    """Build a template context dict for a fleet-level report."""
    nc = nav_ctx or GenericNavContext()
    schema_key = f"schema_{schema.name}"
    host_rows: list[dict[str, Any]] = []
    fleet_alerts: list[dict[str, Any]] = []

    from ncs_reporter.models.platforms_config import (
        FILENAME_HEALTH_REPORT as _FHR,
    )

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
            "node_report": f"{hostname}/{_FHR}",
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
            row[f"col_{col.value}"] = _resolve_field_ref(col.value, fields)

        host_rows.append(row)

    host_rows.sort(key=lambda r: r["hostname"])

    # Group fleet alerts by host, similar to the site report logic
    _host_order: list[str] = []
    _host_groups: dict[str, dict[str, Any]] = {}

    queued_alerts = [a for a in fleet_alerts if a.get("severity") in FLEET_ALERT_SEVERITIES]

    for alert in sorted(queued_alerts, key=lambda a: (a.get("severity") != "CRITICAL", str(a.get("host", "")))):
        host = str(alert.get("host", ""))
        if host not in _host_groups:
            _host_order.append(host)
            _host_groups[host] = {
                "host": host,
                "node_report": f"{host}/{_FHR}",
                "platform": schema.display_name,
                "worst_severity": alert.get("severity", ""),
                "alerts": [],
            }
        _host_groups[host]["alerts"].append(
            {
                "severity": alert["severity"],
                "message": alert.get("message", ""),
                "category": alert.get("category", ""),
                "affected_items": alert.get("affected_items", []),
                "detail": alert.get("detail", {}),
            }
        )

    alert_groups = [_host_groups[h] for h in _host_order]
    totals = _count_alerts(queued_alerts)

    # Build fleets list for breadcrumb tree
    if nc.nav_builder is not None:
        current_plt_dir = nc.hosts_data.get(next(iter(aggregated_hosts.keys()), "")) if nc.hosts_data and aggregated_hosts else None
        nav_with_tree = nc.nav_builder.build_for_fleet(current_plt_dir or "", base_nav=nc.nav, display_name=schema.display_name) if current_plt_dir else ({**nc.nav} if nc.nav else {})
    else:
        nav_with_tree = {**nc.nav} if nc.nav else {}

    rc = ctx or ReportContext()
    return {
        "meta": {
            "display_name": schema.display_name,
            "platform": schema.platform,
            "total_hosts": len(host_rows),
            "report_stamp": rc.report_stamp,
            "report_date": rc.report_date,
            "report_id": rc.report_id,
        },
        "nav": nav_with_tree,
        "fleet_columns": [c.model_dump() for c in schema.fleet_columns],
        "hosts": host_rows,
        "active_alerts": queued_alerts,
        "alert_groups": alert_groups,
        "crit_count": totals["critical"],
        "warn_count": totals.get("warning", 0),
    }
