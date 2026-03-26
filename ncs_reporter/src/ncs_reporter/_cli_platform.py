"""CLI platform config command group (extracted from cli.py)."""

from __future__ import annotations

import re
from pathlib import Path

import click
import yaml

from ._report_context import (
    ReportContext,
    generate_timestamps,
    get_jinja_env,
    report_context,
    write_report,
)
from ._schema_utils import annotated_template, schema_from_bundle, schema_template
from .models.report_schema import ReportSchema
from .schema_loader import (
    discover_schemas,
    load_example_bundle,
    load_schema_from_file,
    validate_schema_paths,
)
from .view_models.generic import build_generic_fleet_view, build_generic_node_view


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _validate_config_references(
    s: ReportSchema,
    config_file: Path,
) -> tuple[list[str], list[str]]:
    """Check field references, message formats, and script existence.

    Returns (warnings, errors).
    """
    warnings: list[str] = []
    errors: list[str] = []

    # Unused fields
    referenced: set[str] = set()
    for rule in s.alerts:
        cond = rule.condition
        if hasattr(cond, "field"):
            referenced.add(cond.field)
        for f in rule.detail_fields:
            referenced.add(f)
        if rule.affected_items_field:
            referenced.add(rule.affected_items_field)
    for widget in s.widgets:
        from .models.report_schema import KeyValueWidget, ProgressBarWidget, TableWidget
        if isinstance(widget, KeyValueWidget):
            for kv in widget.fields:
                referenced.add(kv.field)
        elif isinstance(widget, TableWidget):
            referenced.add(widget.rows_field)
        elif isinstance(widget, ProgressBarWidget):
            referenced.add(widget.field)
            if widget.label:
                referenced.add(widget.label)
    for col in s.fleet_columns:
        referenced.add(col.field)
    for spec in s.fields.values():
        for tmpl in [spec.compute or "", *((spec.script_args or {}).values())]:
            if isinstance(tmpl, str):
                for ref in re.findall(r"\{(\w+)\}", tmpl):
                    referenced.add(ref)

    unreferenced = {k for k in s.fields if not k.startswith("_") and k not in referenced}
    if unreferenced:
        warnings.append(f"Unused fields: {', '.join(sorted(unreferenced))}")

    # Message format string references
    import difflib
    declared = set(s.fields.keys())
    for rule in s.alerts:
        for match in re.finditer(r"\{(\w+)", rule.msg):
            ref = match.group(1)
            if ref != "value" and not ref.startswith("_") and ref not in declared:
                hint = difflib.get_close_matches(ref, list(declared), n=1, cutoff=0.6)
                suffix = f" (did you mean '{hint[0]}'?)" if hint else ""
                errors.append(f"alert '{rule.id}': message references undeclared field '{ref}'{suffix}")

    # Script file existence
    from .normalization._fields import _resolve_script
    for name, spec in s.fields.items():
        if spec.script is None:
            continue
        if _resolve_script(spec.script, str(config_file)) is None:
            errors.append(f"field '{name}': script '{spec.script}' not found")

    return warnings, errors


# ---------------------------------------------------------------------------
# platform config command group
# ---------------------------------------------------------------------------


@click.group("platform")
def platform() -> None:
    """Manage platform config files."""


@platform.command("list")
@click.option("--extra-config-dir", "-S", multiple=True, metavar="DIR")
def platform_list(extra_config_dir: tuple[str, ...]) -> None:
    """List all discovered platform configs and their source paths."""
    schemas = discover_schemas(extra_dirs=tuple(extra_config_dir))
    if not schemas:
        click.echo("No platform configs found.")
        return
    for name, s in sorted(schemas.items()):
        source = getattr(s, "_source_path", "unknown")
        example_status = "example OK" if load_example_bundle(s) else "no example file"
        click.echo(f"  {name:20s}  platform={s.platform:10s}  {example_status:14s}  {source}")


@platform.command("validate")
@click.argument("config_file", type=click.Path(exists=True, path_type=Path))
def platform_validate(config_file: Path) -> None:
    """Validate a platform config file with comprehensive checks."""
    try:
        s = load_schema_from_file(config_file)
    except ValueError as exc:
        click.echo(f"INVALID: {exc}", err=True)
        raise SystemExit(1)

    warnings, errors = _validate_config_references(s, config_file)

    # Path validation against example bundle
    example = load_example_bundle(s)
    if example is not None:
        for msg in validate_schema_paths(s, example).values():
            errors.append(msg)

    click.echo(f"Config '{s.name}' — {len(s.fields)} fields, {len(s.alerts)} alerts, {len(s.widgets)} widgets")
    for w in warnings:
        click.echo(f"  WARNING: {w}")
    if errors:
        click.echo(f"FAIL: {len(errors)} error(s):")
        for e in errors:
            click.echo(f"  {e}")
        raise SystemExit(1)
    if example is None:
        click.echo(f"  WARNING: no example file ({s.name}.example.yaml) — path validation skipped")
    else:
        path_fields = sum(1 for spec in s.fields.values() if spec.path is not None)
        click.echo(f"  OK: all {path_fields} path field(s) resolve against {s.name}.example.yaml")
    click.echo("Valid!")


@platform.command("init")
@click.option("--name", required=True)
@click.option("--from-bundle", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--annotated", is_flag=True, default=False, help="Include commented examples of every feature.")
def platform_init(name: str, from_bundle: Path | None, output: Path | None, annotated: bool) -> None:
    """Generate a starter platform config YAML template."""
    if from_bundle:
        content = schema_from_bundle(name, from_bundle)
    elif annotated:
        content = annotated_template(name)
    else:
        content = schema_template(name)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        click.echo(f"Config written to {output}")
    else:
        click.echo(content)


@platform.command("run")
@click.argument("config_file", type=click.Path(exists=True, path_type=Path))
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--hostname", "-n", default="host", show_default=True)
@click.option("--report-stamp")
@click.option("--site-report", "site_report_href", default=None)
def platform_run(
    config_file: Path,
    input_file: str,
    output_dir: str,
    hostname: str,
    report_stamp: str | None,
    site_report_href: str | None,
) -> None:
    """Run a single platform config report against a raw YAML bundle."""
    try:
        s = load_schema_from_file(config_file)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f) or {}

    from .models.platforms_config import (
        FILENAME_HEALTH_REPORT as _FHR,
        FILENAME_FLEET_SUFFIX as _FFS,
        TEMPLATE_NODE as _TN,
        TEMPLATE_FLEET as _TF,
    )
    common_vars = generate_timestamps(report_stamp)
    rc = report_context(common_vars)
    env = get_jinja_env()
    fleet_filename = f"{s.name}{_FFS}"
    node_nav: dict[str, str] = {"fleet_report": f"../{fleet_filename}", "fleet_label": f"{s.display_name} Fleet"}
    fleet_nav: dict[str, str] = {}
    if site_report_href:
        fleet_nav["site_report"] = site_report_href
        node_nav["site_report"] = f"../{site_report_href}"

    from .view_models.common import GenericNavContext
    node_view = build_generic_node_view(s, hostname, bundle, ctx=rc, nav_ctx=GenericNavContext(nav=node_nav))
    host_dir = output_path / hostname
    host_dir.mkdir(exist_ok=True)
    content = env.get_template(_TN).render(generic_node_view=node_view, **common_vars)
    write_report(host_dir, _FHR, content, common_vars["report_stamp"])
    click.echo(f"Node report: {host_dir}/{_FHR}")

    fleet_view = build_generic_fleet_view(s, {hostname: bundle}, ctx=rc, nav_ctx=GenericNavContext(nav=fleet_nav))
    content = env.get_template(_TF).render(generic_fleet_view=fleet_view, **common_vars)
    write_report(output_path, fleet_filename, content, common_vars["report_stamp"])
    click.echo(f"Fleet report: {output_path}/{fleet_filename}")
    click.echo("Done!")


# ---------------------------------------------------------------------------
# platform info subcommands
# ---------------------------------------------------------------------------


@platform.group("info")
def platform_info() -> None:
    """Show reference information about platform config features."""


@platform_info.command("widgets")
def info_widgets() -> None:
    """List available widget types for platform configs."""
    widgets = [
        ("alert_panel", "Active alerts panel"),
        ("key_value", "Key-value pairs display"),
        ("table", "Data table with columns"),
        ("progress_bar", "Progress/gauge bar with thresholds"),
        ("stat_cards", "KPI summary cards"),
        ("bar_chart", "Horizontal bar chart"),
        ("markdown", "Rendered markdown text"),
        ("list", "Bulleted/numbered list"),
        ("grouped_table", "Table grouped by a field"),
    ]
    click.echo("Widget Types:")
    for name, desc in widgets:
        click.echo(f"  {name:20s} {desc}")


@platform_info.command("conditions")
def info_conditions() -> None:
    """List available alert condition operators."""
    click.echo("Numeric Comparisons:")
    for op, desc in [
        ("gt", "Greater than threshold"),
        ("lt", "Less than threshold"),
        ("gte", "Greater than or equal to threshold"),
        ("lte", "Less than or equal to threshold"),
        ("eq", "Equal to threshold"),
        ("ne", "Not equal to threshold"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nRange:")
    click.echo(f"  {'range':20s} Value within min/max bounds")

    click.echo("\nPresence:")
    for op, desc in [
        ("exists", "Field is present and non-empty"),
        ("not_exists", "Field is absent or empty"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nString:")
    for op, desc in [
        ("eq_str", "String equals value"),
        ("ne_str", "String does not equal value"),
        ("in_str", "String is in list of values"),
        ("not_in_str", "String is not in list of values"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nList Filtering:")
    for op, desc in [
        ("filter_count", "Count items matching field=value > threshold"),
        ("filter_multi", "Count items matching multiple filters > threshold"),
        ("computed_filter", "Evaluate expression on each item"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nDate/Time:")
    for op, desc in [
        ("age_gt", "Timestamp age > N days"),
        ("age_lt", "Timestamp age < N days"),
        ("age_gte", "Timestamp age >= N days"),
        ("age_lte", "Timestamp age <= N days"),
    ]:
        click.echo(f"  {op:20s} {desc}")


@platform_info.command("transforms")
def info_transforms() -> None:
    """List available pipe transforms for field paths."""
    from .normalization._transforms import _PARAM_TRANSFORMS, _TRANSFORMS

    click.echo("Simple Transforms (usage: path | transform_name):")
    for name, fn in sorted(_TRANSFORMS.items()):
        doc = (fn.__doc__ or "").strip().split("\n")[0] if fn.__doc__ else ""
        click.echo(f"  {name:20s} {doc}")

    click.echo("\nParameterized Transforms (usage: path | name(args)):")
    for name, fn in sorted(_PARAM_TRANSFORMS.items()):
        doc = (fn.__doc__ or "").strip().split("\n")[0] if fn.__doc__ else ""
        click.echo(f"  {name:20s} {doc}")


@platform_info.command("types")
def info_types() -> None:
    """List available field types and their default fallbacks."""
    from .models.report_schema import _TYPE_DEFAULT_FALLBACKS

    from .normalization._fields import _TYPE_COERCERS

    click.echo("Field Types:")
    for type_name in sorted({*_TYPE_DEFAULT_FALLBACKS.keys(), *_TYPE_COERCERS.keys()}):
        fallback = _TYPE_DEFAULT_FALLBACKS.get(type_name)
        click.echo(f"  {type_name:20s} default: {fallback!r}")


@platform_info.command("aliases")
def info_aliases() -> None:
    """List YAML shorthand aliases for config fields."""
    aliases = [
        ("from", "path", "Field data source path"),
        ("expr", "compute", "Computed expression"),
        ("run", "script", "Script to execute"),
        ("args", "script_args", "Script arguments"),
        ("timeout", "script_timeout", "Script timeout"),
        ("default", "fallback", "Default value when null"),
        ("title", "display_name", "Human-readable name"),
        ("title", "label", "Widget/column label"),
        ("rows", "rows_field", "Table data source"),
        ("any", "keys_any", "Detection: match any key"),
        ("all", "keys_all", "Detection: match all keys"),
    ]
    click.echo("YAML Aliases (shorthand → canonical):")
    for alias, canonical, desc in aliases:
        click.echo(f"  {alias:20s} → {canonical:20s} {desc}")


# ---------------------------------------------------------------------------
# Deprecated alias — keep `schema` working with a warning
# ---------------------------------------------------------------------------


@click.group("schema", hidden=True)
def schema() -> None:
    """Deprecated: use 'platform' instead."""
    click.echo("Warning: 'schema' command is deprecated, use 'platform' instead.", err=True)


schema.add_command(platform_list, "list")
schema.add_command(platform_validate, "validate")
schema.add_command(platform_init, "init")
schema.add_command(platform_run, "run")
