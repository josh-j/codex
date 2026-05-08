# ncs-reporter config reference

How to write and wire the YAML config files that drive `ncs-reporter` — the schemas that define what a report looks like, which hosts it targets, which fields get computed, which alerts fire, and what happens when they do.

## Where configs live

| Path | Contents |
|---|---|
| `ncs-ansible/ncs_configs/` | Orchestrator-level: `config.yaml` (points at per-collection dirs), `inventory_root.yaml` (tree-rendered flat-platform root), `schedules.yml` (systemd timers) |
| `ncs-ansible-<name>/ncs_configs/` | Per-collection: platform schemas (`ubuntu.yaml`, `esxi.yaml`, …), base include files (`*_base_alerts.yaml`, `*_base_fields.yaml`, `*_base_widgets.yaml`), `scripts/` (assembler helpers), `cklb_skeletons/` (DISA STIG checklist templates) |

`ncs-reporter` discovers configs from `--config-dir` (typically `ncs-ansible/ncs_configs`) and follows the `extra_config_dirs` list in that directory's `config.yaml` to pick up each collection's schemas.

## Docs in this folder

- [CONFIG_SCHEMA.md](CONFIG_SCHEMA.md) — top-level schema shape (`config`, `vars`, `alerts`, `widgets`, `detection`), platform identifiers, `$include` composition, file-name conventions
- [FIELDS.md](FIELDS.md) — the `vars:` block — `path`, `compute`, `normalize`, `const`, `script`, thresholds, type coercion, transform pipelines, full DSL operator reference
- [ALERTS.md](ALERTS.md) — alert rules — severity ladder, `when` expressions, `suppress_if` dedup, action wiring
- [WIDGETS.md](WIDGETS.md) — widget catalog — `stat-cards`, `key-value`, `table`, `grouped-table`, `progress-bar`, `alert-panel`, `markdown`
- [SCHEDULING_AND_ALERT_ACTIONS.md](SCHEDULING_AND_ALERT_ACTIONS.md) — clock-driven (`schedules.yml` → systemd timers) vs. state-driven (`action:` on an alert) execution
- [NORMALIZE_DSL_ROLLOUT.md](NORMALIZE_DSL_ROLLOUT.md) — migration plan + status for moving raw-bundle shaping out of Ansible playbooks into `normalize:` schemas

## JSON schema for IDE autocomplete

Add this header to every config file for editor autocomplete + warnings on unknown keys:

```yaml
# yaml-language-server: $schema=../../.schemas/ncs_reporter_config_schema.json
```

The schema lives at `ncs-reporter/schemas/ncs_reporter_config_schema.json` and is regenerated from the Pydantic models via `uv run python ncs-reporter/generate_schema.py`. It includes a typed `NormalizeSpec` definition so every DSL op (sort, unique, slice, list, first_of, …) surfaces in completion. Re-run the generator whenever you add a new DSL op or change a model field.

## Design principles

- **Auto-import by default.** Flat keys in a raw bundle become referenceable Jinja vars automatically. Declare a field in `vars:` only when you need to compute it, apply thresholds, coerce the type, or navigate nested structure.
- **Jinja2 everywhere it's a string.** `value`, `when`, `message`, `compute`, column values — all get rendered against the per-host context.
- **Shorthand aliases.** `title` for `display_name`, `from` for `path`, `expr` for `compute`. Pick whichever reads better in context.
- **Compose with `$include`.** `alerts:`, `widgets:`, and `vars:` can take `$include: <file>.yaml` in place of an inline list/dict. Siblings in the same config dir. Use this to share base definitions across related platforms (`ubuntu.yaml` / `photon.yaml` both include `linux_base_*.yaml`).
- **Health evaluation lives in the reporter, never in templates or Ansible.** Alert `when:` expressions are the single source of truth for "is this host healthy."
- **Schema owns shaping; collect playbooks emit raw.** Per [NORMALIZE_DSL_ROLLOUT.md](NORMALIZE_DSL_ROLLOUT.md), every transform on raw collector output belongs in `normalize:` (or `compute:` for one-liners). `roles/<sub_platform>/tasks/collect.yaml` should not contain `selectattr` / `items2dict` / `map(attribute=…)` / `dict2items` / `rejectattr` / `| zip` in any public-key `set_fact`. A repo-wide pytest guardrail (`ncs-reporter/tests/test_normalize_dsl_guardrails.py`) enforces this.

## Quick example

Minimal `myplatform.yaml` under `ncs-ansible-myplatform/ncs_configs/`:

```yaml
# yaml-language-server: $schema=../../.schemas/ncs_reporter_config_schema.json
config:
  platform: myplatform
  display_name: My Platform
  detection:
    keys_any: [my_unique_key]

vars:
  uptime_days:
    compute: "{{ uptime_seconds / 86400 }}"
  cpu_load_pct:
    path: ".cpu.load_avg_1m"
    type: float
    thresholds:
      warn_if_above: 70
      crit_if_above: 90

alerts:
  - id: cpu_hot
    severity: CRITICAL
    when: cpu_load_pct >= 90
    message: "CPU load {{ cpu_load_pct | round(1) }}% on {{ hostname }}"

widgets:
  - type: stat-cards
    cards:
      - name: Uptime (d)
        value: "{{ uptime_days | round(0) }}"
      - name: CPU load %
        value: "{{ cpu_load_pct | round(1) }}%"
```

Then register the config dir in `ncs-ansible/ncs_configs/config.yaml`:

```yaml
extra_config_dirs:
  - ../../ncs-ansible-myplatform/ncs_configs
```

On the next `ncs-reporter all` run the new platform renders alongside the built-ins.
