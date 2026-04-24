# Config schema

Top-level shape of a per-platform YAML under `ncs-ansible-<name>/ncs_configs/`. Validated by [`ncs-reporter/schemas/ncs_reporter_config_schema.json`](../../ncs-reporter/schemas/ncs_reporter_config_schema.json); the `yaml-language-server` pragma on line 1 of each schema wires VS Code autocomplete.

## Skeleton

```yaml
# yaml-language-server: $schema=../../.schemas/ncs_reporter_config_schema.json
config:
  platform: <id>               # required — unique platform identifier
  display_name: <string>       # optional — shown in headers; alias: title
  path_prefix: <string>        # optional — overrides default report tree subdir
  detection:                   # optional — rules that pick the schema for a bundle
    keys_any: [<field>, ...]
  extra_inventory_widget_columns:   # optional — extra cols in the tree-rendered inventory
    - name: Distribution
      value: "{{ distribution }}"
  stig:                        # optional — only for platforms that carry STIG tasks
    ansible_playbook:
      path: internal.<ns>.<name>_stig_remediate
      target_var: <target_hosts>
    rule_prefix_to_platform:
      UBTU: ubuntu
      GEN:  ubuntu

vars: {...}                    # field definitions — see FIELDS.md
alerts: [...]                  # alert rules     — see ALERTS.md
widgets: [...]                 # report body     — see WIDGETS.md
```

All four top-level sections are individually optional. A config with only a `config:` block and an `alerts:` array is valid — it just produces a minimal report.

## Platform identifiers

`config.platform` is the join key between the raw bundle, the schema, and the rendered report tree. Flat platforms use a single segment (`ubuntu`, `windows`, `aci`); nested platforms use slash-separated (`linux/ubuntu`, `vmware/esxi`, `vmware/vm`). The collector writes artifacts under `<platform_root>/<platform>/<hostname>/raw_*.yaml` using this same identifier.

## Detection

When `ncs-reporter` scans a raw bundle it walks every registered schema and asks, "does this one match?" `detection:` expresses the answer:

```yaml
detection:
  keys_any: [vmware_raw_esxi]        # match if any listed key is present
  keys_all: [hostname, ip_address]   # …and all listed keys are present
  any: ["host_is_linux == true"]     # …or any listed Jinja expression is truthy
  all: ["distribution == 'ubuntu'"]  # …and all listed Jinja expressions are truthy
```

All four clauses are ANDed together; within each clause the list is `all`/`any` as named. A schema with no `detection:` matches only when explicitly targeted by CLI flag or inventory mapping.

## $include

Any of `vars:`, `alerts:`, and `widgets:` can take an `$include:` stanza instead of an inline block, resolving against a sibling file in the same config directory:

```yaml
vars:
  $include: linux_base_fields.yaml
alerts:
  $include: linux_base_alerts.yaml
widgets:
  $include: linux_base_widgets.yaml
```

Include files must contain **only** the referenced shape (a dict for `vars`, a list for `alerts` / `widgets`). Base files are conventionally named `<platform>_base_<section>.yaml` so the workspace schema (`ncs-framework.code-workspace`) can exclude them from the normal report-schema validation path — they aren't full reports on their own.

An alert-only file (matching `*_base_alerts.yaml` or a standalone alert list) is validated against [`alert_list_schema.json`](../../ncs-reporter/schemas/) instead of the full report schema.

## File discovery

`ncs-reporter` finds a platform config by:

1. Loading `--config-dir` (orchestrator's `ncs-ansible/ncs_configs/`).
2. Expanding each entry in `config.yaml`'s `extra_config_dirs:` list (relative to the config dir).
3. Reading every `*.yaml` / `*.yml` under each resolved dir, keyed by `config.platform`.

Config-collision rule: first-wins. Adding a second schema for an existing `platform:` is silently ignored; rename the second schema or drop the first.

## Tree-rendered inventory roots

`ncs-ansible/ncs_configs/inventory_root.yaml` is the schema the reporter picks up for every flat platform (Ubuntu, Photon, Windows Server, ACI). It exposes `hosts` (list of child summaries) and `host_count` in the rendering context; each concrete platform's schema contributes `extra_inventory_widget_columns` so the inventory landing page mixes platform-specific columns (Distribution, Uptime, alert counts) into the shared table.

Nested platforms (vSphere) have their own top-level schemas (`vsphere.yaml`, `datacenter.yaml`, `cluster.yaml`) describing each tier of the tree. Those tier schemas are compute-only — they derive their data from aggregations the reporter pre-computes and do not own raw bundles.
