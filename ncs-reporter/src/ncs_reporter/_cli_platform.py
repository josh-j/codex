"""CLI platform config command group (extracted from cli.py)."""

from __future__ import annotations

import re
from pathlib import Path

import click
from ._schema_utils import annotated_template, schema_from_bundle, schema_template
from .models.report_schema import ReportSchema
from .schema_loader import (
    discover_schemas,
    load_example_bundle,
    load_schema_from_file,
    validate_schema_paths,
)


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
        for ref in re.findall(r"\b(\w+)\b", rule.when):
            if ref in s.fields:
                referenced.add(ref)
    for widget in s.widgets:
        from .models.report_schema import KeyValueWidget, ProgressBarWidget, TableWidget
        if isinstance(widget, KeyValueWidget):
            for kv in widget.fields:
                referenced.add(kv.value)
        elif isinstance(widget, TableWidget):
            referenced.add(widget.rows_field)
        elif isinstance(widget, ProgressBarWidget):
            referenced.add(widget.value)
            if widget.value_label:
                referenced.add(widget.value_label)
    for col in s.fleet_columns:
        referenced.add(col.value)
    for spec in s.fields.values():
        for tmpl in [spec.compute or "", *(spec.script.args if spec.script else {}).values()]:
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
        if _resolve_script(spec.script.path, str(config_file)) is None:
            errors.append(f"field '{name}': script '{spec.script.path}' not found")

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
        ("run", "script.path", "Script to execute"),
        ("script_args", "script.args", "Script arguments (nested under script:)"),
        ("script_timeout", "script.timeout", "Script timeout (nested under script:)"),
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

