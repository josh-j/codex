"""Platform config scaffolding utilities for the `platform init` command."""

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


def annotated_template(name: str) -> str:
    """Generate a verbose config template with examples of every feature."""
    return f"""name: {name}
# title: "Human-Readable Display Name"  # optional, auto-derived from name

detection:
  keys_any: [{name}_raw_data]       # match if ANY key exists in raw bundle
  # keys_all: [key1, key2]          # match if ALL keys exist

# Reduces path repetition — paths starting with '.' become relative.
# path_prefix: "{name}_raw_data.data"

fields:
  # --- Path-based field (extract from raw data) ---
  hostname:
    path: "{name}_raw_data.data.hostname"   # aliases: 'from'
    fallback: "unknown"                     # aliases: 'default'

  # --- Short-form path (string expands to path-only spec) ---
  # os_name: "{name}_raw_data.data.os"

  # --- Computed field (expression with {{field}} references) ---
  example_pct:
    compute: "({{example_used}} / {{example_total}}) * 100"  # aliases: 'expr'
    type: float

  # --- Script field (runs a Python script) ---
  # complex_data:
  #   script:
  #     path: "my_script.py"         # aliases: 'run'
  #     args:                        # aliases: 'script_args'
  #       source: "raw_data"
  #     timeout: 30                  # aliases: 'script_timeout'
  #   type: list

  # --- List processing ---
  # filtered_items:
  #   path: ".items"
  #   type: list
  #   list_filter:
  #     exclude:
  #       status: [inactive, disabled]
  #       name: ["^test_"]           # regex patterns start with ^
  #     include:
  #       type: [server]
  #   list_map:
  #     usage_pct: "({{used}} / {{total}}) * 100"
  #
  # item_count:
  #   path: ".items"
  #   count_where:
  #     status: active

  example_used:
    path: "{name}_raw_data.data.used"
    type: float
  example_total:
    path: "{name}_raw_data.data.total"
    type: float

alerts:
  # --- Threshold alert ---
  - id: example_high
    category: "Capacity"
    severity: WARNING                # CRITICAL, WARNING, INFO
    condition:
      op: gt                         # gt, lt, gte, lte, eq, ne
      field: example_pct
      threshold: 80.0
    message: "Usage is high: {{example_pct:.1f}}%"
    # detail_fields: [example_used, example_total]
    # affected_items_field: filtered_items
    # suppress_if: [other_alert_id]

  # --- Other condition types (uncomment to use) ---
  # - id: range_alert
  #   severity: WARNING
  #   condition:
  #     op: range
  #     field: example_pct
  #     min: 75.0
  #     max: 90.0
  #
  # - id: missing_data
  #   severity: CRITICAL
  #   condition:
  #     op: not_exists
  #     field: hostname
  #
  # - id: date_alert
  #   severity: WARNING
  #   condition:
  #     op: age_gt                   # age_gt, age_lt, age_gte, age_lte
  #     field: last_update
  #     days: 30

widgets:
  # --- Alert panel (always recommended) ---
  - id: alerts
    title: "Active Alerts"
    type: alert_panel

  # --- Key-value pairs ---
  - id: overview
    title: "Overview"
    type: key_value
    fields:
      - {{ label: "Hostname", field: hostname }}
      - {{ label: "Usage", field: example_pct, format: "{{value:.1f}}%" }}
  # NOTE: key_value uses 'label:' (cell label). Tables use 'header:' (column header).

  # --- Table ---
  # - id: items_table
  #   title: "Items"
  #   type: table
  #   rows: filtered_items           # alias for rows_field
  #   columns:
  #     - {{ header: "Name", field: name }}
  #     - {{ header: "Status", field: status, as: status-badge }}

  # --- Progress bar ---
  # - id: usage_bar
  #   title: "Usage"
  #   type: progress_bar
  #   field: example_pct
  #   thresholds:
  #     warn_at: 75
  #     crit_at: 90

  # --- Stat cards ---
  # - id: kpis
  #   title: "Key Metrics"
  #   type: stat_cards
  #   cards:
  #     - {{ field: item_count, label: "Total Items" }}
  #     - {{ field: example_pct, label: "Usage %", format: "{{value:.0f}}" }}

  # --- Bar chart ---
  # - id: chart
  #   title: "By Category"
  #   type: bar_chart
  #   rows: filtered_items
  #   label_field: name
  #   value_field: usage_pct
  #   max: 100

  # --- Grouped table ---
  # - id: by_status
  #   title: "By Status"
  #   type: grouped_table
  #   rows: filtered_items
  #   group_by: status
  #   columns:
  #     - {{ header: "Name", field: name }}

  # --- Markdown ---
  # - id: notes
  #   title: "Notes"
  #   type: markdown
  #   content: "Report generated from **{{name}}** data."

  # --- List ---
  # - id: names
  #   title: "Names"
  #   type: list
  #   items_field: filtered_items
  #   display_field: name

# Fleet table columns (shown in fleet overview):
# fleet_columns:
#   - {{ field: hostname, header: "Host" }}
#   - {{ field: example_pct, header: "Usage %", format: "{{value:.0f}}%" }}

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
        "  - id: alerts",
        '    title: "Active Alerts"',
        "    type: alert_panel",
        "",
    ]

    return "\n".join(lines)
