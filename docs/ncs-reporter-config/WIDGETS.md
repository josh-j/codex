# Widgets (`widgets:` block)

Widgets are the visible body of a report. Each widget is a YAML dict discriminated on `type:`. Order in the list is render order.

## Common keys

Every widget accepts:

| Key | Purpose |
|---|---|
| `type` | Required. One of the seven below. |
| `name` | Section header shown above the widget. Alias: `title`. |
| `slug` | Stable HTML id / anchor. Auto-derived from `name` if omitted. |
| `layout` | Optional layout hint (`full`, `half`, `third`). Defaults to `full`. |
| `when` | Jinja2 boolean — widget is omitted entirely when false. |

`when:` is the right tool for "hide this table if there's no data" — don't use it for per-row filtering, that's what `list_filter` / column-level `when` are for.

## stat-cards

A row of labeled numeric tiles. Best for the top-of-report KPI band.

```yaml
- type: stat-cards
  slug: headline_kpis
  name: Key Metrics
  cards:
    - name: Uptime (d)
      value: "{{ uptime_days | round(0) }}"
    - name: Mem Used %
      value: "{{ memory_used_pct | round(1) }}%"
    - name: Failed Svcs
      value: "{{ failed_services_count }}"
```

Threshold coloring is inherited from the underlying field's `thresholds:` — if `memory_used_pct` declares `warn_if_above: 85`, the card paints amber past 85 automatically.

## key-value

Two-column label/value list. For dense host metadata that doesn't need a table.

```yaml
- type: key-value
  name: System Overview
  fields:
    - name: Hostname
      value: "{{ hostname }}"
    - name: Distribution
      value: "{{ distribution }} {{ distribution_version }}"
    - name: Kernel
      value: "{{ kernel }}"
```

## table

Tabular data over a list. `rows` is a Jinja expression yielding the list, `columns` describes each column.

```yaml
- type: table
  name: Hosts
  when: host_count > 0
  rows: "{{ hosts }}"
  columns:
    - name: Host
      value: "{{ title }}"
      link_field: report_url   # renders value as a link to row.report_url
    - name: Alerts
      value: "{{ _critical_count + _warning_count }}"
```

`rows_field:` is shorthand for `rows: "{{ <field> }}"` when the expression is just a single field lookup.

## grouped-table

Tables where rows cluster under a `group_by:` key — for instance "VMs grouped by cluster." Otherwise identical to `table`.

```yaml
- type: grouped-table
  name: VMs by Cluster
  rows_field: vms
  group_by: cluster
  columns:
    - name: VM
      value: "{{ name }}"
    - name: Power
      value: "{{ power_state }}"
```

## progress-bar

Single numeric metric shown as a filled bar with threshold bands.

```yaml
- type: progress-bar
  name: Storage used
  value: "{{ storage_used_pct }}"
  value_label: "{{ storage_used_gb | round(1) }} / {{ storage_total_gb | round(1) }} GB"
  thresholds:
    warn_if_above: 70
    crit_if_above: 90
```

Thresholds declared here shade the bar; if the underlying field already declares them, omit the widget-level block and let the field drive.

## alert-panel

Renders the host's fired alerts (severity, category, message, action status) as a structured panel. Zero config — it pulls from the alert evaluation the reporter just did.

```yaml
- type: alert-panel
  name: Health Alerts
  when: _critical_count + _warning_count > 0
```

## markdown

Freeform operator notes or context. Rendered as Markdown with Jinja2 expansion first.

```yaml
- type: markdown
  content: |
    **Last collection:** {{ collected_at }}  
    Inventory group: `{{ inventory_group }}`
```

Use sparingly — if a label reappears across platforms, promote it to a `key-value` row in a shared `*_base_widgets.yaml`.

## Composition via `$include`

Every collection's `*_base_widgets.yaml` is an `$include` target for its per-subplatform schemas:

```yaml
widgets:
  $include: linux_base_widgets.yaml
```

The included file is a flat list of widgets (no wrapping dict). Add a widget there to lift it into every variant at once; override by defining a different widget with the same `slug:` after the include.
