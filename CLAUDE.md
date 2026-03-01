# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
NCS is an Ansible-based infrastructure health monitoring and STIG compliance auditing system for heterogeneous fleets (Ubuntu Linux, VMware ESXi/vCenter, Windows). It generates HTML dashboards and STIG compliance reports (CKLB). A standalone Python CLI (`ncs_reporter`) is being developed to decouple reporting from Ansible execution.

## Commands

```bash
just all              # Run all checks (setup, lint, check, test, jinja-lint, ansible-lint)
just lint             # Ruff linting
just format           # Ruff formatting
just check            # MyPy & Basedpyright type checking
just test             # Pytest unit & E2E tests
just jinja-lint       # Jinja2 template validation
just ansible-lint     # Ansible-lint
just setup            # Install Ansible collections and tools

# Orchestration
just site             # Run full fleet audit
just audit-vmware     # Targeted VMware audit
just stig-vmware      # Targeted STIG audit

# Targeted Execution
just stig-audit-vm <vcenter> <vm_name>
just stig-harden-vm <vcenter> <vm_name>
just audit-linux-host <hostname>
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

- **core** — Shared state management, common roles, and path resolution filters.
- **linux** — Ubuntu discovery, STIG compliance, remediation
- **vmware** — VMware discovery, STIG compliance, snapshot collection
- **windows** — Windows audit, STIG compliance, ConfigMgr integration

### Decoupled Reporting Pipeline (2 stages)

1. **Collection (Ansible)** — Platform roles run modules and save raw module results to disk as `raw_*.yaml`.
2. **Processing (ncs-reporter)** — Standalone Python tool normalizes raw data, evaluates alerts, and renders HTML dashboards.

### Key Entry Points

- `playbooks/site.yml` — Main orchestration playbook
- `playbooks/*.yml` — Platform-specific and utility playbooks
- `tools/ncs_reporter/` — Standalone Python CLI (`ncs-reporter`)


## Key Conventions

**Data Collection**: Roles must focus purely on data collection. Use `ansible.builtin.set_stats` with the `ncs_collect` dictionary to emit telemetry.

**Path resolution**: Never hardcode paths in Ansible. The `ncs_collector` callback plugin and the `ncs-reporter` tool handle directory structures automatically.


**Logic in Python**: All health evaluation, status derivation, and view-model building MUST happen in `ncs_reporter.normalization` (Python), NOT in Ansible Jinja filters.

**View model contracts**: Builders return Pydantic models (see `ncs_reporter.models`) with standardized keys. Templates must only render the provided structure.


## Python Style

- Python 3.10+, line length 120
- Ruff rules: E, F, B, I, N, UP, RUF
- MyPy with `strict_optional` and `check_untyped_defs`
- Type annotations on all Python code
- External collections excluded from linting (`collections/ansible_collections/{cloud,community,vmware}`)

## Active Migration

Reporting is being decoupled from Ansible into `tools/ncs_reporter/` (standalone Python CLI). See `DECOUPLE_REPORTING.md` and `docs/REPORTING_ARCHITECTURE.md` for design details.
