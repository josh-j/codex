# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
NCS is an Ansible-based infrastructure health monitoring and STIG compliance auditing system for heterogeneous fleets (Ubuntu Linux, VMware ESXi/vCenter, Windows). It generates HTML dashboards, STIG compliance reports (CKLB), and CSV exports. A standalone Python CLI (`ncs_reporter`) is being developed to decouple reporting from Ansible execution.

## Commands

```bash
make all              # Run all checks (setup, lint, check, test, jinja-lint, ansible-lint)
make lint             # Ruff linting
make format           # Ruff formatting
make check            # MyPy type checking
make test             # Pytest unit tests
make jinja-lint       # Jinja2 template validation
make ansible-lint     # Ansible-lint
make setup            # Install Ansible collections from requirements.yml

# Single test file
pytest tests/unit/test_core_reporting_filter.py

# Single test
pytest tests/unit/test_core_reporting_filter.py::TestClassName::test_method -v
```

### ncs_reporter CLI (tools/ncs_reporter/)

Has its own `justfile` for development:
```bash
just setup            # Install in dev mode
just lint / just check / just test
just site <input> <groups> [output]
just linux <input> [output]
just vmware <input> [output]
just windows <input> [output]
```

## Architecture

### Collections (`collections/ansible_collections/internal/`)

- **core** — Shared reporting, validation, state management, common roles. Contains custom Ansible filters (`plugins/filter/`) and Python module utilities (`plugins/module_utils/`) used across all platforms.
- **linux** — Ubuntu audit, discovery, STIG compliance, remediation
- **vmware** — VMware audit, discovery, STIG compliance, snapshot analysis
- **windows** — Windows audit, STIG compliance, ConfigMgr integration

### Reporting Pipeline (6 stages)

1. **Raw Report Emitters** — Platform roles write host-level YAML
2. **Aggregation** — Collects host YAML into fleet state files
3. **Normalization** — Python adapters normalize payloads to canonical shapes
4. **View-Model Builders** — Python functions build template-ready dicts (`plugins/module_utils/report_view_models*.py`)
5. **Rendering** — Ansible orchestrates directory/symlink/template management
6. **Presentation** — Jinja templates + shared CSS render final HTML

### Key Entry Points

- `playbooks/master_audit.yaml` — Main orchestration playbook
- `playbooks/{ubuntu,vmware,windows}/` — Platform-specific playbooks
- `tools/ncs_reporter/` — Standalone Python CLI (Click-based)

## Key Conventions

**Context flow**: Discovery roles populate role-prefixed facts (e.g., `ubuntu_ctx`, `vmware_ctx`). Audit/reporting roles consume via `ncs_ctx` variable.

**Path resolution**: All output paths resolved via `internal.core.resolve_ncs_path` filter. Never hardcode paths.

**Skip keys**: Host loops must skip structural entries (`platform`, `history`, `*_fleet_state`, container dirs). Use `internal.core.report_skip_keys`.

**View model contracts**: Builders return dicts with standardized keys (`status.raw`, `links.*`, `summary`, `alerts`). Tested via contract tests.

**Test pattern**: Tests dynamically load collection modules via `importlib` from collection paths. See existing tests for the loader pattern.

## Python Style

- Python 3.10+, line length 120
- Ruff rules: E, F, B, I, N, UP, RUF
- MyPy with `strict_optional` and `check_untyped_defs`
- Type annotations on all Python code
- External collections excluded from linting (`collections/ansible_collections/{cloud,community,vmware}`)

## Active Migration

Reporting is being decoupled from Ansible into `tools/ncs_reporter/` (standalone Python CLI). See `DECOUPLE_REPORTING.md` and `docs/REPORTING_ARCHITECTURE.md` for design details.
