# Reporting Pipeline Architecture

This repo uses a layered reporting pipeline for Linux, VMware, Windows, site dashboards, and STIG reports. Stages 2–6 are handled by the standalone `ncs_reporter` Python CLI; Ansible is responsible only for auditing systems and emitting raw data (Stage 1).

## Canonical Source Layout

- Collection code lives under `collections/ansible_collections/internal/...`
- The standalone reporting CLI lives under `tools/ncs_reporter/`

## Pipeline Stages

### 1. Raw Report Emitters (platform roles)

Platform roles write host-level YAML outputs into the reports tree (for example under `platform/ubuntu/<host>/`, `platform/vmware/<host>/`, and `platform/windows/<host>/`).

Examples:
- VMware discovery/audit export tasks
- Linux system audit and STIG export tasks
- Windows audit export tasks

These outputs are considered raw inputs for aggregation.

### 2. Aggregation

The `ncs_reporter collect` command collects host YAML files and builds aggregated fleet state files:

- `linux_fleet_state.yaml`
- `vmware_fleet_state.yaml`
- `windows_fleet_state.yaml`

The aggregated shape is the handoff between emitters and reporting views.

### 3. Normalization (Python adapters/helpers)

Normalization converts platform payload variants into canonical shapes for downstream builders.

Key modules:
- `tools/ncs_reporter/src/ncs_reporter/aggregation.py`
- `collections/ansible_collections/internal/core/plugins/module_utils/normalization.py`

Goal:
- keep payload adaptation out of playbooks and templates
- isolate compatibility logic in tested Python code

### 4. View-Model Builders (Python)

Template-facing data is built in view-model builders under:

- `tools/ncs_reporter/src/ncs_reporter/view_models/`

Platform modules:
- `vmware.py` — `build_vmware_fleet_view(...)`, `build_vmware_node_view(...)`
- `linux.py` — `build_linux_fleet_view(...)`, `build_linux_node_view(...)`
- `windows.py` — `build_windows_fleet_view(...)`, `build_windows_node_view(...)`
- `site.py` — `build_site_dashboard_view(...)`
- `common.py` — shared primitives and skip-key logic

Contract conventions:
- `status.raw` for normalized status/health display state
- `links.*` for template navigation links
- precomputed fleet totals / alert rollups / STIG finding lists

### 5. Rendering / Orchestration

The `ncs_reporter` CLI handles rendering: directory creation, template rendering, latest symlink maintenance, and archive/retention behavior. Ansible invokes it via `playbooks/common/generate_fleet_reports.yaml`.

### 6. Presentation (Jinja + Shared CSS)

Templates and shared CSS live in:

- `tools/ncs_reporter/src/ncs_reporter/templates/`

Templates focus on rendering, not aggregation:
- Linux fleet/node dashboards
- VMware fleet/node dashboards
- Windows fleet/node dashboards
- Global site dashboard
- STIG per-host and fleet compliance reports

## Skip Keys and Host Loops

Aggregated host maps include structural/state entries that are not real hosts (for example `platform`, `history`, `*_fleet_state`, and platform container directories like `ubuntu` / `vmware` / `windows`).

Canonical skip keys are centralized in:
- `tools/ncs_reporter/src/ncs_reporter/view_models/common.py`

And exposed via:
- `internal.core.report_skip_keys`

Use this for host-loop tasks/templates instead of hardcoding exclusions.

## Validation Strategy

### Fast checks
- Unit tests for view-model contracts and adapters
- `ansible-playbook --syntax-check` for playbooks/roles

### Recommended runtime checks
- Integration rendering runs with representative Linux/VMware/Windows/STIG payloads
- CI integration coverage (Molecule or equivalent) on the collection layout

## State Management & Context Flow

To ensure variable state is easy to reason about across collections and playbooks, Codex follows these standards:

### 1. The Context Pattern
Roles that consume discovery data must accept a `ncs_ctx` variable as input. This makes dependencies explicit in playbooks.

- **Producers (Discovery Roles):** Populate a role-prefixed fact (e.g., `ubuntu_ctx`).
- **Consumers (Audit/Remediation Roles):** Access data via `ncs_ctx`.
- **Usage in Playbooks:**
  ```yaml
  roles:
    - role: internal.linux.ubuntu_system_discover
    - role: internal.linux.ubuntu_system_audit
      vars:
        ncs_ctx: "{{ ubuntu_ctx }}"
  ```

### 2. Centralized Path Resolution
Never hardcode file paths or use repeated `default('/srv/samba/reports')` logic. Use the `internal.core.resolve_ncs_path` filter.

```yaml
# Example: Exporting host state
ncs_export_path: "{{ ncs_config | internal.core.resolve_ncs_path('ubuntu', inventory_hostname, 'system') }}"
```

### 3. Encapsulated Role State
- Use role-prefixed variables for all public facts.
- Use internal prefixes (e.g., `_`) for transient task-level variables (`set_fact`, `register`).
- Avoid mutating global configuration objects directly; return new objects or specific facts instead.

## Design Rules

- Prefer collection-path imports and collection-local code as canonical source of truth
- Keep compatibility normalization in Python, not Jinja
- Treat template-facing view models as contracts (test them)
- Avoid repo-layout string parsing when deriving paths; use role vars / `playbook_dir | dirname`
- Ansible handles audit/emit only; `ncs_reporter` CLI owns aggregation through presentation
