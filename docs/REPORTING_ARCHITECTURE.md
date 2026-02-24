# Reporting Pipeline Architecture

This repo now uses a layered reporting pipeline for Linux, VMware, Windows, site dashboards, and STIG reports.

## Canonical Source Layout

- Collection code lives under `/Users/joshj/dev/codex/collections/ansible_collections/internal/...`
- Reporting helpers and shared tasks are centered in:
  - `/Users/joshj/dev/codex/collections/ansible_collections/internal/core`

## Pipeline Stages

### 1. Raw Report Emitters (platform roles)

Platform roles write host-level YAML outputs into the reports tree (for example under `platform/ubuntu/<host>/`, `platform/vmware/<host>/`, and `platform/windows/<host>/`).

Examples:
- VMware discovery/audit export tasks
- Linux system audit and STIG export tasks
- Windows audit export tasks

These outputs are considered raw inputs for aggregation.

### 2. Aggregation (Python)

The shared aggregation script collects host YAML files and builds an aggregated host map:

- `/Users/joshj/dev/codex/playbooks/scripts/aggregate_yaml_reports.py`

Output is typically written as:
- `all_hosts_state.yaml`
- `linux_fleet_state.yaml`
- `vmware_fleet_state.yaml`
- `windows_fleet_state.yaml`

The aggregated shape is the handoff between emitters and reporting views.

### 3. Normalization (Python adapters/helpers)

Normalization converts platform payload variants into canonical shapes for downstream builders.

Examples:
- Shared primitives and normalization helpers:
  - `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/plugins/module_utils/reporting_primitives.py`
  - `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/plugins/module_utils/report_view_models.py`

Goal:
- keep payload adaptation out of playbooks and templates
- isolate compatibility logic in tested Python code

### 4. View-Model Builders (Python)

Template-facing data is built in shared view-model builders:

- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/plugins/module_utils/report_view_models.py`

Key builders:
- `build_vmware_fleet_view(...)`
- `build_vmware_node_view(...)`
- `build_linux_fleet_view(...)`
- `build_linux_node_view(...)`
- `build_site_dashboard_view(...)`
- `build_stig_host_view(...)`
- `build_stig_fleet_view(...)`

Windows view-model builders currently live in the Windows collection filter layer (`internal.windows.windows_fleet_view`, `internal.windows.windows_node_view`) and may be promoted into shared module_utils if Windows reporting grows further.

Contract conventions:
- `status.raw` for normalized status/health display state
- `links.*` for template navigation links
- precomputed fleet totals / alert rollups / STIG finding lists

### 5. Rendering / Orchestration (Ansible)

Ansible roles orchestrate:
- directory creation
- template rendering
- latest symlink maintenance
- archive/retention behavior

Shared reporting task helpers:
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/roles/reporting/tasks/prepare_platform_state.yaml`
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/roles/reporting/tasks/host_loop_ensure_dirs.yaml`
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/roles/reporting/tasks/host_loop_render_template.yaml`
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/roles/reporting/tasks/host_loop_latest_symlink.yaml`
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/roles/reporting/tasks/site_dashboard.yaml`

Platform summary roles (Linux/VMware/Windows) now build view models and pass them into templates.

### 6. Presentation (Jinja + Shared CSS)

Templates should focus on rendering, not aggregation.

Examples:
- Linux fleet/node dashboards
- VMware fleet/node dashboards
- Windows fleet/node dashboards
- Global site dashboard
- Core STIG HTML report

Shared CSS/filter helpers are provided via core filters to keep styling and formatting centralized.

## Skip Keys and Host Loops

Aggregated host maps include structural/state entries that are not real hosts (for example `platform`, `history`, `*_fleet_state`, and platform container directories like `ubuntu` / `vmware` / `windows`).

Canonical skip keys are centralized in:
- `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/plugins/module_utils/report_view_models.py`

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

## Design Rules (current)

- Prefer collection-path imports and collection-local code as canonical source of truth
- Keep compatibility normalization in Python, not Jinja
- Treat template-facing view models as contracts (test them)
- Avoid repo-layout string parsing when deriving paths; use role vars / `playbook_dir | dirname`
