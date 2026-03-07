# Raw YAML Envelope Contract

This document specifies the YAML envelope format that `ncs-reporter` expects as input. Any tool (Ansible, scripts, custom collectors) can produce compatible input by following this contract.

## Envelope Structure

```yaml
metadata:
  host: "hostname"           # Required: hostname this data belongs to
  audit_type: "raw_discovery" # Optional: used for routing/filtering
  timestamp: "2026-03-06T12:00:00Z" # Optional: ISO 8601 collection time
  engine: "custom_collector"  # Optional: identifies the data source

data:
  # Platform-specific payload — structure depends on the schema
  # that will process this file. See schema YAML files for field paths.
  field_name: value
  nested:
    sub_field: value
```

## Required Fields

| Field | Location | Description |
|-------|----------|-------------|
| `host` | `metadata.host` | Hostname identifier. Used as the directory name and report label. |

## Optional Fields

| Field | Location | Description |
|-------|----------|-------------|
| `audit_type` | `metadata.audit_type` | Routing key (e.g., `raw_discovery`, `raw_vcenter`). Derived from filename if absent. |
| `timestamp` | `metadata.timestamp` | ISO 8601 timestamp of data collection. |
| `target_type` | root or `data.target_type` | For STIG artifacts: identifies the compliance target (e.g., `esxi`, `vcsa`, `ubuntu`). |

## Directory Placement

Files must be placed under a platform input directory matching the `input_dir` from `platforms.yaml`:

```
<platform-root>/
  <input_dir>/
    <hostname>/
      raw_discovery.yaml      # Health/audit data
      raw_stig_<target>.yaml  # STIG compliance data
```

Example for a Linux host:
```
platform/linux/ubuntu/myhost/raw_discovery.yaml
```

Example for a VMware STIG artifact:
```
platform/vmware/esxi/esxi-01/raw_stig_esxi.yaml
```

## STIG Artifacts

STIG artifacts use a slightly different envelope with `target_type` at the root:

```yaml
metadata:
  host: "esxi-01"
  audit_type: "stig_esxi"
  timestamp: "2026-03-06T12:00:00Z"
data:
  - id: "V-256379"
    status: "failed"
    severity: "medium"
    title: "Rule title"
    rule_version: "ESXI-70-000001"
target_type: "esxi"
```

The `data` field for STIG is a list of finding rows. Each row should contain at minimum:
- `id` or `rule_id`: Rule identifier
- `status`: One of `failed`/`open`, `pass`/`passed`/`compliant`, `na`/`not_applicable`
- `severity`: One of `high`/`CAT_I`, `medium`/`CAT_II`, `low`/`CAT_III`

## Adding a New Platform

To add a new platform with zero Python changes:

1. Create a schema YAML in a schema directory (see existing schemas for format)
2. Add an entry to `platforms.yaml` (or `platforms_default.yaml`) with:
   - `input_dir` / `report_dir` / `platform` / `state_file` / `target_types` / `paths`
   - Optional metadata: `display_name`, `asset_label`, `inventory_groups`, `schema_names`
   - Optional STIG: `stig_skeleton_map`, `stig_rule_prefixes`
   - Optional site dashboard: `site_audit_key`, `site_category`, `fleet_link`
3. Place raw YAML files in `<platform-root>/<input_dir>/<hostname>/`
4. Run `ncs-reporter all` — the new platform is automatically discovered and rendered
