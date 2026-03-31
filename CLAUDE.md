# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

NCS (Network Control System) — an Ansible-based fleet management platform for auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure. It has two decoupled stages:

1. **Stage 1 — Collect** (Ansible): Roles run modules and emit `raw_*.yaml` artifacts via the `ncs_collector` callback plugin.
2. **Stage 2 — Report** (`ncs-reporter`): A standalone Python CLI that normalizes raw data, evaluates alerts, and renders HTML dashboards / STIG reports / CKLB artifacts.

## Common Commands

All commands use `just` (the Justfile runner). Run `just` at repo root to list everything.

```bash
# Setup
just setup-all              # Both venvs + all collections
just setup-main-venv        # Main .venv only (uses uv sync if available)

# Quality (repo root)
just lint                   # ruff check .
just format                 # ruff format .
just check                  # mypy + basedpyright
just test                   # pytest tests/unit
just lint-configs           # Lint ncs-reporter YAML configs

# ncs-reporter development (cd ncs-reporter/)
just test                   # pytest tests (all ncs-reporter tests)
just lint                   # ruff check
just check                  # mypy + basedpyright on src/
just test-all               # lint + check + test
```

## Architecture

### Ansible Collections (internal/)

Four internal Ansible collections live under `internal/` and are symlinked into `collections/ansible_collections/internal/`:

| Collection | Roles | Purpose |
|---|---|---|
| `internal.core` | — | Shared plugins: `ncs_collector` callback, `stig`/`pwsh` action+module plugins, filter plugins |
| `internal.vmware` | `common`, `esxi`, `vcsa`, `vm` | VMware audit, STIG audit/remediate |
| `internal.linux` | `ubuntu`, `photon` | Linux audit, STIG audit/remediate |
| `internal.windows` | `windows` | Windows audit, STIG audit/remediate |

The `ncs_collector` callback plugin (`internal/core/plugins/callback/ncs_collector.py`) is the bridge between stages — it intercepts Ansible task results and persists them as `raw_*.yaml` files.

### Playbooks (playbooks/)

Organized by platform subdirectory. Key patterns:
- `site.yml` — Master orchestrator (setup → audit all platforms → report)
- `*/audit.yml` — Read-only collection
- `*/stig_audit.yml` — Read-only STIG compliance check
- `*/stig_remediate.yml` — MUTATING STIG hardening
- Playbooks use `ncs_action`, `ncs_profile`, and `ncs_operation` as the shared role interface

### ncs-reporter (ncs-reporter/)

Standalone Python package (`ncs-reporter/src/ncs_reporter/`). Key modules:
- `cli.py` — Click entry point for all subcommands (`all`, `site`, `linux`, `vmware`, `windows`, `node`, `stig`, `cklb`, `stig-apply`)
- `normalization/` — Platform-specific data normalization and alert logic (health evaluation lives here, never in templates or Ansible)
- `view_models/` — Typed Pydantic view contracts consumed by templates
- `aggregation.py` — Multi-host state aggregation
- `configs/` — Bundled YAML config schemas (mirrored to `files/ncs-reporter_configs/`)
- `_config.py` — Config schema loader supporting both canonical and alias keys

### Config Sync

Reporter configs exist in two places that must stay in sync:
- `ncs-reporter/src/ncs_reporter/configs/` (bundled with the package)
- `files/ncs-reporter_configs/` (deployed by Ansible)

A pre-commit hook runs `scripts/check_config_sync.py` when either side is staged. Fix with: `python3 scripts/check_config_sync.py --fix`

## Two Ansible Environments

- **Main venv** (`.venv/`): ansible-core latest, used for everything except VCSA SSH
- **VCSA venv** (`.venv-vcsa/`): ansible-core 2.15, required because VCSA appliances run Python 3.7. Uses `ANSIBLE_CONFIG=ansible-vcsa.cfg` and `collections_vcsa/` path

## Key Conventions

- Ruff line length: 120, target Python 3.10+
- Type checking: mypy (strict) + basedpyright (standard)
- Inventory: `inventory/production/` (Ansible vault password in `.vaultpass`)
- Reports output to `/srv/samba/reports/` by default
- Telemetry lake path pattern: `<platform_root>/{category}/{sub_platform}/{hostname}/raw_{type}.yaml`
- YAML config schemas support concise aliases (e.g., `title` for `display_name`, `from` for `path`, `expr` for `compute`)
