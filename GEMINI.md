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

## Architecture: The Totally Decoupled Reporting Pipeline

NCS employs a strictly decoupled architecture to ensure separation of concerns and peak performance:

1.  **Raw Report Emitters (Ansible):** Ansible roles (e.g., `ubuntu_system_discover`, `vmware.discovery`) collect raw data from modules and write it directly to disk as `raw_*.yaml`.
2.  **Normalization (Python):** The `ncs_reporter.normalization` layer in Python converts these raw payloads into canonical shapes.
3.  **Alert Logic (Python):** Business logic for health checks, alert generation, and status derivation happens in Python normalizers, not Jinja.
4.  **View-Model Builders (Python):** `ncs_reporter.view_models` shapes data into template-ready contracts, isolating logic from presentation.
5.  **Rendering (Python/Jinja):** `ncs_reporter` renders "dumb" templates into rich HTML dashboards.


## Development & Operations

### Key Commands

- `just all`: Execute all quality checks (linting, type-checking, tests).
- `just test`: Run all unit and E2E tests.
- `just lint`: Run `ruff` for Python linting.
- `just format`: Run `ruff` for Python formatting.
- `just check`: Run type checking (mypy + basedpyright).
- `just ansible-lint`: Run `ansible-lint` for Ansible best practices.
- `just jinja-lint`: Run `j2lint` for template validation.
- `just site`: Execute the full audit pipeline.
- `just stig-audit-vm <vcenter> <vm_name>`: Audit a specific VM.
- `just audit-linux-host <hostname>`: Audit a specific Linux server.


### Canonical Paths
- **Internal Collections:** `collections/ansible_collections/internal/`
  - `core/`: Shared reporting logic, view-models, and common roles.
  - `linux/`, `vmware/`, `windows/`: Platform-specific roles and plugins.
- **Playbooks:** `playbooks/`
  - `site.yml`: Main orchestration entry point.
  - `*_audit.yml`, `*_patch.yml`, etc.: Task-specific playbooks.
- **Inventory:** `inventory/production/`

## Engineering Standards & Conventions

- **Logic in Python, not Jinja:** All data shaping, alert logic, and status derivation must happen in the `ncs-reporter` normalization layer. Ansible roles must remain "dumb" collectors.
- **Emit Telemetry:** Use `ansible.builtin.set_stats` with the `ncs_collect` dictionary to emit module outputs. The `ncs_collector` callback plugin automatically persists this to disk. Do not attempt to normalize data within Ansible tasks.
- **Pydantic Models:** All reporting contracts must be defined as Pydantic models in `ncs_reporter.models`.

- **Contract Testing:** All normalization logic must have corresponding unit tests in `tools/ncs_reporter/tests/` to prevent regressions.
- **Type Safety:** Use type hints in all Python code and ensure `mypy` and `basedpyright` pass.
- **Declarative Playbooks:** Never hardcode paths or credentials in playbooks. Use role defaults and the `ncs_collector` callback for automated data lake management.
- **Collection-First:** Prefer standard collection structures and avoid custom `module_utils` hacks inside Ansible unless absolutely necessary for module execution.

