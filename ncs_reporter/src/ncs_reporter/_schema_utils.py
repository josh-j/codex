"""Schema scaffolding utilities for the `schema init` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml


def schema_template(name: str) -> str:
    """Generate a minimal starter schema YAML template."""
    return f"""name: {name}

detection:
  keys_any: [{name}_raw_data]

# Uncomment to reduce path repetition — paths starting with '.' are relative.
# path_prefix: "{name}_raw_data.data"

fields:
  hostname:
    path: "{name}_raw_data.data.hostname"
    fallback: "unknown"

  example_metric:
    path: "{name}_raw_data.data.some_metric"
    type: float

  example_computed:
    compute: "{{example_metric}} * 100"
    type: float

alerts:
  - id: example_alert
    category: "Example"
    severity: WARNING
    condition:
      op: gt
      field: example_metric
      threshold: 90.0
    message: "Example metric is high: {{example_metric:.1f}}"

widgets:
  - id: alerts
    title: "Active Alerts"
    type: alert_panel

  - id: overview
    title: "Overview"
    type: key_value
    fields:
      - {{ label: "Hostname", field: hostname }}
      - {{ label: "Example Metric", field: example_metric }}
"""


def infer_type(value: Any) -> str:
    """Infer a schema field type string from a Python value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "str"


def walk_keys(data: Any, prefix: str, result: list[tuple[str, str, str]]) -> None:
    """Recursively walk a nested dict, collecting (path, field_name, type) tuples."""
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        full_path = f"{prefix}.{key}" if prefix else key
        safe_name = full_path.replace(".", "_").replace("-", "_")
        if isinstance(value, dict):
            walk_keys(value, full_path, result)
        else:
            ftype = "list" if isinstance(value, list) else infer_type(value)
            result.append((full_path, safe_name, ftype))


def schema_from_bundle(name: str, bundle_path: Path) -> str:
    """Generate a schema from a raw YAML data bundle by walking its key tree."""
    with open(bundle_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise click.ClickException(f"Bundle {bundle_path} is not a YAML mapping")

    entries: list[tuple[str, str, str]] = []
    walk_keys(data, "", entries)

    top_key = next(iter(data.keys())) if data else name

    lines = [
        f"name: {name}",
        "",
        "detection:",
        f"  keys_any: [{top_key}]",
        "",
        "# Uncomment and adjust to reduce path repetition:",
        f'# path_prefix: "{top_key}.data"',
        "",
        f"# Generated from {bundle_path.name} — {len(entries)} leaf keys discovered",
        "fields:",
    ]

    for path, field_name, ftype in entries:
        lines.append(f"  {field_name}:")
        lines.append(f'    path: "{path}"')
        if ftype != "str":
            lines.append(f"    type: {ftype}")
        lines.append("")

    lines += [
        "alerts: []",
        "",
        "widgets:",
        "  - id: alerts",
        '    title: "Active Alerts"',
        "    type: alert_panel",
        "",
    ]

    return "\n".join(lines)
