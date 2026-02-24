# Custom Filters

This repo includes Ansible custom filter plugins used by the VMware roles and shared core collection helpers.

## `internal.core` filters

Source: `/Users/joshj/dev/codex/internal/core/plugins/filter/dates.py`

### `internal.core.filter_by_age(items, current_epoch, age_threshold_days, date_key="creation_time")`

Filters a list of dictionaries by age and injects `age_days` into returned items.

Notes:
- Expects an ISO-like timestamp string in `date_key`
- Ignores timezone suffix while parsing
- Skips items with unparseable dates

Example:

```jinja
{{ snapshots | internal.core.filter_by_age(ansible_facts['date_time']['epoch'] | int, 7, 'creation_time') }}
```

### `internal.core.safe_iso_to_epoch(raw, default=0)`

Safely parses an ISO timestamp into epoch seconds.

Behavior:
- Returns `default` if parsing fails (instead of raising)
- Useful in Jinja-heavy normalization blocks where one malformed timestamp should not fail the task

Example:

```jinja
{{ ts_str | internal.core.safe_iso_to_epoch(0) }}
```

Source: `/Users/joshj/dev/codex/internal/core/plugins/filter/alerts.py`

### `internal.core.build_alerts(checks)`

Builds alert objects from a list of check definitions where `condition` evaluates truthy.

Output fields include:
- `severity`
- `category`
- `message`
- `detail`

Also preserves optional enrichment fields such as `affected_items`, `recommendation`, `remediation`, `runbook`, `links`, `id`, `source`.

Example:

```jinja
{{ checks | internal.core.build_alerts }}
```

### `internal.core.threshold_alert(value, category, message, critical_pct, warning_pct, detail=None)`

Returns a single CRITICAL/WARNING alert (as a one-item list) when `value` exceeds the configured threshold, or an empty list otherwise.

Example:

```jinja
{{ usage_pct | internal.core.threshold_alert('capacity', 'Datastore usage high', 90, 80, {'datastore': ds_name}) }}
```

### `internal.core.health_rollup(alerts)`

Reduces a list of alerts to an overall status:
- `CRITICAL`
- `WARNING`
- `HEALTHY`

Example:

```jinja
{{ vmware_ctx.alerts | internal.core.health_rollup }}
```

### `internal.core.summarize_alerts(alerts)`

Summarizes alert counts by severity and category.

Returns a dict with:
- `total`
- `critical_count`
- `warning_count`
- `info_count`
- `by_category`

Example:

```jinja
{{ vmware_ctx.alerts | internal.core.summarize_alerts }}
```

Source: `/Users/joshj/dev/codex/internal/core/plugins/filter/validation.py`

### `internal.core.validate_schema_from_file(data, filepath, root_key)`

Validates a data structure against the nested key shape of a YAML schema file and root key.

Behavior:
- Raises an Ansible filter error when the file is missing, invalid, or required keys are absent
- Returns `True` when validation passes

Example:

```jinja
{{ vmware_ctx | internal.core.validate_schema_from_file('/path/to/defaults/main.yaml', 'vmware_ctx') }}
```

## `internal.vmware` filters

Source: `/Users/joshj/dev/codex/internal/vmware/plugins/filter/snapshot.py`

### `internal.vmware.enrich_snapshots(snapshots, owner_map=None)`

Enriches snapshot records (typically after `internal.core.filter_by_age`) with VMware-specific fields.

Adds/normalizes:
- `vm_name`
- `snapshot_name` (URL-decoded from `name`)
- `size_gb` (cast to float)
- `owner_email` (resolved from `owner_map`)

Example:

```jinja
{{
  raw_snapshots
  | internal.core.filter_by_age(ansible_facts['date_time']['epoch'] | int, 7)
  | internal.vmware.enrich_snapshots(vm_owner_map)
}}
```

Source: `/Users/joshj/dev/codex/internal/vmware/plugins/filter/discovery.py`

### `internal.vmware.normalize_compute_inventory(cluster_results)`

Normalizes `vmware.vmware.cluster_info` loop results into discovery-ready cluster and host collections.

Returns:
- `clusters_by_name`
- `clusters_list`
- `hosts_list`

Example:

```jinja
{{ (_clusters_per_dc.results | default([])) | internal.vmware.normalize_compute_inventory }}
```

### `internal.vmware.normalize_datastores(datastores, low_space_pct=10)`

Normalizes datastore records returned by `community.vmware.vmware_datastore_info`.

Returns a dict with:
- `list`
- `summary` (`total_count`, `inaccessible_count`, `low_space_count`, `maintenance_count`)

Example:

```jinja
{{ (_datastores_raw.datastores | default([])) | internal.vmware.normalize_datastores(10) }}
```

### `internal.vmware.analyze_workload_vms(virtual_machines, current_epoch, backup_overdue_days=2)`

Normalizes VM inventory and derives backup/ownership compliance fields.

Returns a dict with:
- `list`
- `summary`
- `metrics`

Behavior:
- Parses PowerProtect backup timestamps from VM attributes
- Treats malformed timestamps as `INVALID_FORMAT` without raising
- Marks non-parseable backup values as unprotected/overdue

Example:

```jinja
{{ (_vms_raw.virtual_machines | default([])) | internal.vmware.analyze_workload_vms(_vmware_controller_epoch | int, 2) }}
```

## Maintenance notes

- Current filter plugin files discovered:
  - `/Users/joshj/dev/codex/internal/core/plugins/filter/dates.py`
  - `/Users/joshj/dev/codex/internal/core/plugins/filter/alerts.py`
  - `/Users/joshj/dev/codex/internal/core/plugins/filter/validation.py`
  - `/Users/joshj/dev/codex/internal/vmware/plugins/filter/snapshot.py`
  - `/Users/joshj/dev/codex/internal/vmware/plugins/filter/discovery.py`
- Prefer adding generic date/time helpers to `internal.core` instead of role-specific collections.
- Keep VMware filters focused on VMware domain normalization/enrichment.
- When adding new filters, document the expected input shape and failure behavior here.
