# {{ starter_platform_name }} Audit Role

This role provides automated health and compliance auditing for **{{ starter_platform_name }}** infrastructure. It follows the standard CODEX 3-phase lifecycle.

## 📋 Role Overview

- **Lifecycle Phase**: Execution
- **Collection**: internal.{{ collection_name }}
- **Objective**: Gather facts from {{ starter_platform_name }} and evaluate against health/security thresholds.

## 🔧 Interface

### Inputs (Variables)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `{{ starter_platform_name }}_skip_discovery` | Boolean | `false` | If true, skips fact gathering. |
| `{{ starter_platform_name }}_threshold` | Integer | `90` | Example threshold for alerts. |

### Outputs (Facts)

The role populates the global `ops` fact under the `{{ starter_platform_name }}` namespace:

```yaml
ops:
  {{ starter_platform_name }}:
    facts:
      # Key facts gathered during discovery
    status: "OK" # Summary status
```

## 🏗️ Structure

1. **Initialize (`init.yaml`)**: Sets up the `ops.{{ starter_platform_name }}` dictionary.
2. **Discover (`discover.yaml`)**: Gathers raw data (read-only).
3. **Check (`check.yaml`)**: Evaluates data and appends to `ops.alerts`.
4. **Export (`export.yaml`)**: Normalizes data for the reporting engine.

## 🚀 Usage

```yaml
- name: Audit {{ starter_platform_name }}
  ansible.builtin.import_role:
    name: internal.{{ collection_name }}.{{ starter_platform_name }}
```
