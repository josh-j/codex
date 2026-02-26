# NCS Project Context

NCS is a sophisticated Ansible-based automation and reporting system designed for managing and auditing a heterogeneous fleet of servers, including Linux (Ubuntu), VMware (ESXi/vCenter), and Windows.

## Project Overview

The project provides comprehensive system auditing, STIG (Security Technical Implementation Guide) compliance reporting, and health monitoring. It features a custom-built, layered reporting pipeline that translates raw automation outputs into rich, human-readable HTML dashboards and STIG reports.

### Key Technologies
- **Ansible:** Primary orchestration and automation engine.
- **Python (3.10+):** Powering custom filters, module utilities, aggregation scripts, and reporting view-model builders.
- **Jinja2:** Template engine for generating HTML reports and configuration files.
- **Ruff & MyPy:** Used for Python code quality, formatting, and type safety.
- **Pytest:** Unit testing framework for the Python-based reporting logic.

## Architecture: The Reporting Pipeline

Codex employs a layered architecture to ensure separation of concerns and maintainability in reporting:

1.  **Raw Report Emitters (Platform Roles):** Ansible roles (e.g., `ubuntu_stig_audit`, `windows_audit`) write host-level YAML reports.
2.  **Aggregation (Python):** `playbooks/scripts/aggregate_yaml_reports.py` collects host-level YAML files into a unified fleet state.
3.  **Normalization (Python):** Python adapters in `internal.core` normalize varied platform payloads into canonical shapes.
4.  **View-Model Builders (Python):** `internal.core.plugins.module_utils.report_view_models` builds template-ready data structures (contracts), isolating logic from presentation.
5.  **Rendering & Orchestration (Ansible):** Shared roles and tasks manage directories, template rendering, and symlink maintenance.
6.  **Presentation (Jinja + CSS):** Templates focus exclusively on rendering the pre-computed view models.

## Development & Operations

### Key Commands

- `make all`: Execute all quality checks (linting, type-checking, tests).
- `make test`: Run unit tests for Python modules and builders.
- `make lint`: Run `ruff` for Python linting.
- `make format`: Run `ruff` for Python formatting.
- `make check`: Run `mypy` for static type checking.
- `make ansible-lint`: Run `ansible-lint` for Ansible best practices.
- `make jinja-lint`: Run `j2lint` for template validation.

### Canonical Paths
- **Internal Collections:** `collections/ansible_collections/internal/`
  - `core/`: Shared reporting logic, view-models, and common roles.
  - `linux/`, `vmware/`, `windows/`: Platform-specific roles and plugins.
- **Playbooks:** `playbooks/`
  - `ubuntu/`, `vmware/`, `windows/`: Platform-specific orchestration.
  - `common/`: Shared utility playbooks (e.g., site health generation).
- **Inventory:** `inventory/production/`

## Engineering Standards & Conventions

- **Logic in Python, not Jinja:** Complex data shaping, alert counting, and status derivation must happen in Python view-model builders. Templates should be "dumb" and only render the provided structure.
- **Contract Testing:** All reporting view-models and platform adapters must have corresponding unit tests in `tests/unit/` to prevent regressions.
- **Type Safety:** Use type hints in all Python code and ensure `mypy` passes.
- **Avoid Path Hardcoding:** Do not use brittle string parsing for repository paths. Use `playbook_dir | dirname` or role variables to derive paths relative to the project root.
- **Skip Keys:** Use `internal.core.report_skip_keys` for filtering host loops in reporting tasks to avoid including metadata/fleet entries.
- **Collection-First:** Prefer importing code via collection paths (e.g., `ansible_collections.internal.core.plugins.module_utils`) to ensure consistency.
- **STIG Compliance:** STIG reporting should follow the shared view-model architecture (`stig_host_view`, `stig_fleet_view`).
- **No Console Logs:** Use a logger for Python scripts; do not use `print()` or `console.log` equivalent in non-CLI contexts.
