"""Platform config scaffolding utilities for the `platform init` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml


def schema_template(name: str) -> str:
    """Generate a minimal starter schema YAML template."""
    return f"""# yaml-language-server: $schema=../../.schemas/ncs_reporter_config_schema.json
config:
  platform: {name}
  display_name: "{name.replace('_', ' ').title()}"
  detection:
    keys_any: [{name}_raw_data]

vars:
  hostname:
    path: "{name}_raw_data.data.hostname"
    fallback: "unknown"

  example_metric:
    path: "{name}_raw_data.data.some_metric"
    type: float

  example_pct:
    compute: "{{{{ example_metric * 100 }}}}"
    type: float
    thresholds:
      warn_if_above: 80
      crit_if_above: 90

alerts:
  - id: example_high
    category: "Capacity"
    severity: WARNING
    when: example_pct >= 80
    msg: "Usage is high: {{{{ example_pct | round(1) }}}}%"

widgets:
  - type: stat-cards
    cards:
      - name: Hostname
        value: "{{{{ hostname }}}}"
      - name: Example
        value: "{{{{ example_pct | round(1) }}}}%"
"""


def annotated_template(name: str) -> str:
    """Generate a verbose config template with examples of every feature."""
    return f"""# yaml-language-server: $schema=../../.schemas/ncs_reporter_config_schema.json
config:
  platform: {name}
  display_name: "{name.replace('_', ' ').title()}"
  detection:
    keys_any: [{name}_raw_data]      # match if ANY key exists in raw bundle
    # keys_all: [key1, key2]         # match if ALL keys exist

vars:
  # --- Path-based field ---
  hostname:
    path: "{name}_raw_data.data.hostname"   # alias: 'from'
    fallback: "unknown"                     # alias: 'default'

  # --- Computed field — Jinja2 expression over other fields ---
  example_pct:
    compute: "{{{{ (example_used / example_total) * 100 }}}}"  # alias: 'expr'
    type: float
    thresholds:
      warn_if_above: 80
      crit_if_above: 90

  # --- Path leaves (used by the compute above) ---
  example_used:
    path: "{name}_raw_data.data.used"
    type: float
  example_total:
    path: "{name}_raw_data.data.total"
    type: float

  # --- normalize: declarative shaping (see FIELDS.md § normalize) ---
  # filtered_items:
  #   type: list
  #   normalize:
  #     list:
  #       source: items
  #       include_where: {{type: server}}

  # --- Script field (subprocess escape hatch — prefer normalize:) ---
  # complex_data:
  #   script:
  #     path: "my_script.py"         # alias: 'run'
  #     args: {{}}                    # alias: 'script_args'
  #     timeout: 30                  # alias: 'script_timeout'
  #   type: list

alerts:
  - id: example_high
    category: "Capacity"
    severity: WARNING                # CRITICAL, WARNING, INFO
    when: example_pct >= 80
    msg: "Usage is high: {{{{ example_pct | round(1) }}}}%"
    # suppress_if: [other_alert_id]

widgets:
  # --- Stat cards ---
  - type: stat-cards
    cards:
      - name: Hostname
        value: "{{{{ hostname }}}}"
      - name: Usage
        value: "{{{{ example_pct | round(1) }}}}%"

  # --- Key/value list ---
  - type: key-value
    name: "Overview"
    fields:
      - name: Hostname
        value: "{{{{ hostname }}}}"
      - name: Usage
        value: "{{{{ example_pct | round(1) }}}}%"

  # --- Table (per-row data) ---
  # - type: table
  #   name: "Items"
  #   rows: "{{{{ filtered_items }}}}"
  #   columns:
  #     - name: Name
  #       value: "{{{{ name }}}}"
  #     - name: Status
  #       value: "{{{{ status }}}}"
  #       as: status-badge

  # --- Progress bar ---
  # - type: progress-bar
  #   name: "Usage"
  #   value: "{{{{ example_pct }}}}"
  #   thresholds:
  #     warn_if_above: 75
  #     crit_if_above: 90

  # --- Alert panel — auto-injected by the renderer; declare to control placement ---
  # - type: alert-panel
  #   name: "Active Alerts"

  # --- Grouped table ---
  # - name: "By Status"
  #   type: grouped_table
  #   rows: "{{{{ filtered_items }}}}"
  #   group_by: "{{{{ status }}}}"
  #   columns:
  #     - {{ name: "Name", value: "{{{{ name }}}}" }}

  # --- Markdown ---
  # - name: "Notes"
  #   type: markdown
  #   content: "Report generated from **{{name}}** data."

# Fleet table columns (shown in fleet overview):
# fleet_columns:
#   - {{ value: "{{{{ hostname }}}}", name: "Host" }}
#   - {{ value: "{{{{ example_pct }}}}", name: "Usage %", format: "{{value:.0f}}%" }}

# Tip: run 'ncs-reporter platform info widgets' for all widget types.
# Tip: run 'ncs-reporter platform info conditions' for all condition operators.
# Tip: run 'ncs-reporter platform info transforms' for pipe transforms.
# Tip: run 'ncs-reporter platform info aliases' for YAML shorthand aliases.
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
        '  - name: "Active Alerts"',
        "    type: alert_panel",
        "",
    ]

    return "\n".join(lines)
