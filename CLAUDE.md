# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

NCS (Non-Core Services) — an Ansible-based fleet management platform for auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure. It has two decoupled stages:

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
| `internal.core` | `dispatch`, `emit`, `stig_orchestrator` | Shared plugins: `ncs_collector` callback, `stig`/`pwsh` action+module plugins, filter plugins |
| `internal.vmware` | `common`, `esxi`, `vcsa`, `vm` | VMware audit, STIG audit/remediate |
| `internal.linux` | `ubuntu`, `photon` | Linux audit, STIG audit/remediate |
| `internal.windows` | `server`, `domain` | Windows audit, STIG audit/remediate, AD operations |

The `ncs_collector` callback plugin (`internal/core/plugins/callback/ncs_collector.py`) is the bridge between stages — it intercepts Ansible task results and persists them as `raw_*.yaml` files.

### Playbooks

**App layer** (`playbooks/`) — site orchestrators + NCS infrastructure:
- `site.yml`, `site_*.yml` — Master orchestrators (setup → audit platforms → report)
- `ncs/` — report dir init, report generation, samba share, schedule timers
- `core/send_alert_email.yml` — localhost alerting

**Collections** — each platform ships self-contained playbooks invoked by FQCN:
- `internal/vmware/playbooks/` → `ansible-playbook internal.vmware.esxi_stig_audit` etc.
- `internal/linux/playbooks/` → `ansible-playbook internal.linux.ubuntu_collect` etc.
- `internal/windows/playbooks/` → `ansible-playbook internal.windows.server_stig_audit` etc.

Playbook file naming inside collections is flat with a sub-platform prefix
(`esxi_stig_audit.yml`, `ubuntu_collect.yml`, `server_stig_audit.yml`). Shared
role interface is `ncs_action` / `ncs_profile` / `ncs_operation`.

### ncs-reporter (ncs-reporter/)

Standalone Python package (`ncs-reporter/src/ncs_reporter/`). Key modules:
- `cli.py` — Click entry point for all subcommands (`all`, `site`, `linux`, `vmware`, `windows`, `node`, `stig`, `cklb`, `stig-apply`)
- `normalization/` — Platform-specific data normalization and alert logic (health evaluation lives here, never in templates or Ansible)
- `view_models/` — Typed Pydantic view contracts consumed by templates
- `aggregation.py` — Multi-host state aggregation
- `_config.py` — Config schema loader supporting both canonical and alias keys

### Runtime Configs

Operator-editable configs live under the top-level `ncs_configs/` directory:
- `ncs_configs/ncs-reporter/` — reporter YAML schemas, `cklb_skeletons/`, and `scripts/` (consumed by ncs-reporter via `--config-dir`)
- `ncs_configs/schedules.yml` — systemd timer definitions consumed by `playbooks/core/manage_schedules.yml`

Each internal collection also has its own `internal/<col>/ncs_configs/` for collection-owned configuration data.

`ncs-reporter` no longer ships a bundled config/script copy; the Ansible tree is the single source of truth.

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
